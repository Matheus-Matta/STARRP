"""A varredura da precificação e as decisões (aprovar/recusar) — ver models/market.py.

`run()` (Celery, de hora em hora) passa pelas contas com o rastreamento ligado e lê os produtos
que estão na vez (nunca lidos primeiro; depois o mais antigo), até `PRICE_TRACKING_BATCH` por
conta a cada rodada. Serviço e kit ficam de fora (não têm equivalente no mercado).

A leitura para assim que chega ao mínimo de concorrentes da conta (`_read`), para não gastar consulta à toa.

Quem pede pela tela não espera: `start` cria o processo na hora, com os dados mínimos, marca `reading_since` e manda a
leitura para o worker (`tasks.market.price_read`). A tela relê até `reading` virar falso.
"""
import logging
import threading
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone
from kombu.exceptions import OperationalError

from starrp.core.errors import BusinessError
from starrp.models import Account, BackgroundTask, MarketOffer, Module, PriceCheck, Product, ProductVariant
from starrp.services import background, batches
from starrp.services.market import ai as market_ai
from starrp.services.market import matching, pricing, scope
from starrp.services.market.sources import SourceError, active, label_of, take_budget, used_this_month

logger = logging.getLogger(__name__)

# Recusou e o mercado quase não mudou: não volta a pedir na semana.
REJECT_QUIET = timedelta(days=7)
REJECT_MOVE = Decimal("0.02")
# Fonte sem saldo ou fora do ar: até quando a oferta guardada ainda vale como mercado.
KEEP_OFFERS = timedelta(days=14)
MAX_OFFERS = 60
NOT_IN_MARKET = (Product.Type.SERVICE, Product.Type.KIT)  # não têm equivalente no mercado
PRODUCT_MAX_VARIANTS = 50  # o botão "Precificar" responde na hora


def _cost(variant):
    return variant.average_cost or variant.last_cost or Decimal("0")


def _ours(variant):
    product = variant.product
    codes = sorted(variant.barcodes.all(), key=lambda b: not b.is_primary)
    # Da grade, só a medida (128GB) separa produtos: anúncio não cita tamanho nem cor, e eles não mudam o preço.
    kept = [part.strip() for part in variant.name.split("/") if matching.MEASURE.search(matching.normalize(part))]
    brand = product.brand.name if product.brand_id else ""
    return matching.Ours(title=matching.full_title(" ".join([product.name, *kept]), brand, product.model_name), brand=brand,
                         gtins=tuple(b.code for b in codes), reference=f"{product.reference} {product.model_name}".strip())


def _check_of(variant):
    check = PriceCheck.all_objects.filter(variant=variant, deleted_at__isnull=True).first()
    return check or PriceCheck(account_id=variant.account_id, variant=variant)


def _kept(check, source):
    """As ofertas guardadas desta fonte: valem quando ela falha, o teto do dia acabou ou não era para reler."""
    if not check.pk:
        return []
    since = timezone.now() - KEEP_OFFERS
    rows = MarketOffer.all_objects.filter(price_check=check, source=source.key, observed_at__gte=since)
    return [({"external_id": r.external_id, "title": r.title, "url": r.url, "seller": r.seller, "price": r.price,
              "free_shipping": r.free_shipping, "source": r.source, "observed_at": r.observed_at, "query": r.query},
             matching.Match(r.match_score, r.match_reason)) for r in rows]


def _score(ours, offer, query=""):
    """Veio da busca pelo código: critério do código. O resto, o do título."""
    if offer.get("trusted"):
        return matching.Match(Decimal("100"), "Informado pela equipe.")
    if query and query in ours.gtins:
        return matching.score_by_code(ours, offer["title"], brand=offer["brand"], gtins=offer["gtins"], model=offer["model"])
    return matching.score(ours, offer["title"], gtins=offer["gtins"])


def _pairs(scored):
    """(preço, nota). A fonte manda float: sem `str`, 10.39 viraria 10.3900000000000005 e sairia da faixa das usadas."""
    return [(Decimal(str(o["price"])), m.score) for o, m in scored]


def _enough(scored, rules):
    kept, _ = pricing.reference(_pairs(scored), rules)
    return len(kept) >= rules.min_competitors


def _same_offer(offer):
    return offer["seller"].casefold(), offer["title"].casefold(), Decimal(str(offer["price"]))


def _search(source, variant, ours, memo, rules, now, scored, searches, errors):
    """As buscas da fonte, uma de cada vez, até dar o mínimo. Devolve se alguma respondeu e se alguma oferta foi aceita."""
    answered = accepted = False
    for query in source.searches(ours):
        key = (source.key, query) if source.shared and memo is not None else None
        if key in (memo or {}):
            found = memo[key]
        else:
            blocked = take_budget(source, variant.account)
            if blocked:
                errors.append(blocked)
                break
            try:
                found = source.fetch(variant, ours, variant.account, query)
            except SourceError as error:
                errors.append(str(error))
                break
            if key:
                memo[key] = found
        answered = True
        seen = {_same_offer(offer) for offer, _ in scored}  # a mesma loja volta na outra busca e na outra fonte do Google
        rows = [({**offer, "source": source.key, "observed_at": now, "query": query}, _score(ours, offer, query))
                for offer in found]
        scored += [row for row in rows if _same_offer(row[0]) not in seen]
        matched = sum(m.score >= rules.match_min for _, m in rows)
        accepted = accepted or matched > 0
        if query:
            searches.append({"source": source.key, "query": query, "offers": len(found), "matched": matched})
        if matched or _enough(scored, rules):  # o EAN é para quando o título não trouxe nenhuma aceitável
            break
    return answered, accepted


def _read(variant, ours, check, sources, fresh, now, memo, rules):
    """Ofertas das fontes, em ordem. Uma fora do ar ou sem saldo não atrapalha as outras.

    A pesquisa da equipe sempre entra. As fontes de busca seguem a ordem da conta: com `Account.SearchMode.FALLBACK`, a
    próxima só roda se a anterior falhou (erro, limite ou nenhuma oferta aceita); com `ALL`, rodam todas, sempre.
    As fontes de código entram por último, só se faltar para o mínimo de concorrentes.

    `memo`: o que já veio nesta rodada, para variações com a mesma busca não gastarem outra consulta."""
    scored, errors, searches, stale = [], [], [], []
    run_all = variant.account.price_search_mode == Account.SearchMode.ALL
    solved = False
    for source in sorted(sources, key=lambda s: s.turn):  # estável: dentro de cada grupo, a ordem da conta
        if fresh is not None and source.key not in fresh:
            scored += _kept(check, source)
            continue
        if fresh is None and source.turn:
            skip = not run_all and (solved or _enough(scored, rules)) if source.queries else _enough(scored, rules)
            if skip:
                continue
        if source.needs_gtin and not ours.gtins:
            continue
        answered, accepted = _search(source, variant, ours, memo, rules, now, scored, searches, errors)
        solved = solved or (accepted and bool(source.queries))
        if not answered:
            stale += _kept(check, source)
    seen = {_same_offer(offer) for offer, _ in scored}  # as guardadas não contam para decidir quem roda: quem falhou passa a vez
    scored += [row for row in stale if _same_offer(row[0]) not in seen]
    return scored, errors, searches


def check_variant(variant, rules=None, sources=None, fresh=None, memo=None):
    """Lê o mercado deste produto e atualiza o processo dele. Devolve o `PriceCheck`.

    `fresh`: só estas fontes consultam de novo; as outras entram com as ofertas guardadas
    (salvar um preço de concorrente recalcula na hora, sem gastar consulta nenhuma)."""
    rules = rules or pricing.Rules.of(variant.account)
    sources = active(variant.account) if sources is None else sources
    check = _check_of(variant)
    ours = _ours(variant)
    now = timezone.now()
    scored, errors, searches = _read(variant, ours, check, sources, fresh, now, memo, rules)
    if fresh is None:  # recalcular com o preço da equipe não gasta token
        scored, check.ai_note = market_ai.review(variant.account, ours, scored, rules)
    pairs = _pairs(scored)
    decision = pricing.decide(variant.price, _cost(variant), pairs, rules)
    kept, _ = pricing.reference(pairs, rules)
    low, high = (kept[0], kept[-1]) if kept else (None, None)
    before = check.status
    old_suggestion = check.suggested_price
    for field, value in decision.items():
        setattr(check, field, value)
    if fresh is None:  # recalcular com o preço da equipe não adia a próxima leitura das outras fontes
        check.error, check.checked_at, check.searches = " ".join(errors)[:300], now, searches
        check.reading_since = None
    check.source = ", ".join(sorted({label_of(o["source"]) for o, _ in scored}))[:120]
    check.status = _next_status(check, before, old_suggestion)
    with transaction.atomic():
        check.save()
        models.QuerySet.delete(MarketOffer.all_objects.filter(price_check=check))  # só a última leitura
        MarketOffer.all_objects.bulk_create([
            MarketOffer(account_id=variant.account_id, price_check=check, source=o["source"],
                        observed_at=o["observed_at"], query=o.get("query", "")[:300], external_id=o["external_id"][:60],
                        title=o["title"][:300], url=o["url"][:500], seller=o["seller"][:120],
                        price=Decimal(str(o["price"])).quantize(pricing.CENT), free_shipping=o["free_shipping"],
                        match_score=m.score, match_reason=m.reason[:200],
                        used=bool(kept and m.score >= rules.match_min and low <= Decimal(str(o["price"])) <= high))
            for o, m in sorted(scored, key=lambda pair: -pair[1].score)[:MAX_OFFERS]])
    return check


def _next_status(check, before, old_suggestion):
    S = PriceCheck.Status
    if check.suggested_price is None:
        return S.NONE if before == S.PENDING else (before or S.NONE)
    if before == S.REJECTED and check.decided_at and timezone.now() - check.decided_at < REJECT_QUIET \
            and old_suggestion and abs(check.suggested_price - old_suggestion) <= old_suggestion * REJECT_MOVE:
        return S.REJECTED
    if before != S.PENDING:
        check.decided_by, check.decided_at = None, None
    return S.PENDING


def trackable(account):
    """O que a leitura pode pegar: produto ativo, sem serviço e kit, dentro das regras da conta."""
    rows = (ProductVariant.all_objects
            .filter(account=account, deleted_at__isnull=True, is_active=True, product__deleted_at__isnull=True,
                    product__is_active=True)
            .exclude(product__type__in=NOT_IN_MARKET))
    return scope.apply(rows, account)


def due(account, limit):
    """Os produtos na vez: nunca lidos primeiro, depois quem foi lido há mais tempo."""
    last = PriceCheck.all_objects.filter(variant=OuterRef("pk"), deleted_at__isnull=True).values("checked_at")[:1]
    limit_time = timezone.now() - timedelta(hours=max(account.price_tracking_hours, 1))
    rows = (trackable(account)
            .annotate(last_check=Subquery(last))
            .filter(models.Q(last_check__isnull=True) | models.Q(last_check__lt=limit_time))
            .select_related("product__brand", "account").prefetch_related("barcodes")
            .order_by(F("last_check").asc(nulls_first=True)))
    return list(rows[:limit])


def batch_total(account, started):
    """Quantos entram na rodada: o que está na vez, até o que ainda cabe no limite mensal de consultas da conta."""
    last = PriceCheck.all_objects.filter(variant=OuterRef("pk"), deleted_at__isnull=True).values("checked_at")[:1]
    limit_time = started - timedelta(hours=max(account.price_tracking_hours, 1))
    total = (trackable(account).annotate(last_check=Subquery(last))
             .filter(models.Q(last_check__isnull=True) | models.Q(last_check__lt=limit_time)).count())
    limit = account.price_monthly_requests
    if limit and any(source.metered for source in active(account)):
        return min(total, max(limit - used_this_month(account), 0))
    return total


def batch_next(account, started, size):
    return due(account, size)


def batch_process(account, variants):
    """Cria os itens que faltam (aparecem na lista) e lê este lote."""
    to_read = _prepare(variants)[1]
    if to_read:
        read_variants(str(account.pk), to_read)


def _send(account, variant_ids, user=None):
    """Para o worker. Sem Redis (desenvolvimento) o Celery rodaria aqui dentro e travaria a tela: vai para uma thread."""
    from starrp.tasks.market import price_read

    ids = [str(pk) for pk in variant_ids]
    task = background.begin(account, BackgroundTask.Kind.PRICE_READ, len(ids), user)
    if settings.PRICE_READ_IN_THREAD:
        threading.Thread(target=price_read, args=(str(account.pk), ids, str(task.pk)), daemon=True).start()
        return
    try:
        price_read.delay(str(account.pk), ids, str(task.pk))
    except OperationalError as error:
        PriceCheck.all_objects.filter(variant_id__in=variant_ids, deleted_at__isnull=True).update(reading_since=None)
        background.fail(task.pk, "A fila está fora do ar. Tente de novo em instantes.")
        logger.exception("Precificação: fila fora do ar")
        raise BusinessError("A fila da precificação está fora do ar. Tente de novo em instantes.",
                            code="price_queue_down") from error


def _prepare(variants):
    """Cria o processo de cada variação (só com os dados mínimos, se for novo) e marca que está lendo."""
    checks, to_send = [], []
    now = timezone.now()
    for variant in variants:
        check = _check_of(variant)
        checks.append(check)
        if check.reading:  # já está na fila: o segundo clique não gasta outra consulta
            continue
        if check._state.adding:  # o id já existe antes de salvar: `pk` não diz se é novo
            cost = _cost(variant)
            check.current_price, check.cost = variant.price, cost
            check.current_margin = pricing.margin(variant.price, cost)
            check.reason = "Lendo o mercado..."
        check.reading_since = now
        check.save()
        to_send.append(variant.pk)
    return checks, to_send


def start(account, variants, user=None):
    """O clique em um produto ou item: cria os processos na hora e manda a leitura para o worker."""
    checks, to_send = _prepare(variants)
    if to_send:
        _send(account, to_send, user)
    return checks


def read_variants(account_id, variant_ids):
    """O trabalho do worker. Uma variação com problema não segura as outras nem fica "lendo" para sempre."""
    account = Account.objects.get(pk=account_id)
    rows = (ProductVariant.all_objects.filter(account=account, pk__in=variant_ids, deleted_at__isnull=True)
            .select_related("product__brand", "account").prefetch_related("barcodes"))
    memo, done = {}, 0
    for variant in rows:
        try:
            check_variant(variant, memo=memo)
            done += 1
        except Exception:  # noqa: BLE001
            logger.exception("Precificação: falha em %s", variant.pk)
            PriceCheck.all_objects.filter(variant=variant, deleted_at__isnull=True).update(
                reading_since=None, error="A leitura falhou. Tente de novo.")
    return done


def start_product(account, product_id, user=None):
    """O botão "Precificar" do produto: todas as variações dele, fora das regras e da vez."""
    rows = (ProductVariant.all_objects
            .filter(account=account, product_id=product_id, deleted_at__isnull=True, is_active=True,
                    product__deleted_at__isnull=True)
            .select_related("product__brand", "account").prefetch_related("barcodes"))
    variants = list(rows[:PRODUCT_MAX_VARIANTS])
    if not variants:
        raise BusinessError("Produto não encontrado ou sem variação ativa.", code="price_product_missing")
    if variants[0].product.type in NOT_IN_MARKET:
        raise BusinessError("Serviço e kit não têm preço de mercado para comparar.", code="price_product_type")
    return start(account, variants, user)


def run():
    """A varredura de hora em hora: uma rodada em lotes por conta, até `PRICE_TRACKING_BATCH` produtos."""
    total = 0
    accounts = Account.objects.filter(status=Account.Status.ACTIVE, price_tracking_enabled=True)
    for account in accounts.select_related("subscription__plan"):
        if account.has_module(Module.PRICING):
            total += batches.start(BackgroundTask.Kind.PRICE_ROUND, account, cap=settings.PRICE_TRACKING_BATCH)["total"]
    return total


# ── decisões ───────────────────────────────────────────────────────────────
def approve(check, user, price=None):
    """Aplica o novo preço no cadastro (com histórico). `price` = outro valor que a pessoa escolheu."""
    if check.status != PriceCheck.Status.PENDING or check.suggested_price is None:
        raise BusinessError("Esta sugestão não está aguardando aprovação.", code="price_not_pending")
    new = Decimal(str(price)).quantize(pricing.CENT) if price not in (None, "") else check.suggested_price
    if new <= 0:
        raise BusinessError("Informe um preço maior que zero.", code="price_invalid")
    with transaction.atomic():
        variant = ProductVariant.all_objects.select_for_update().get(pk=check.variant_id)
        check.previous_price = variant.price
        variant.price, variant.updated_by = new, user
        variant.save(update_fields=["price", "updated_by", "updated_at"])
        check.status, check.applied_price = PriceCheck.Status.APPLIED, new
        check.current_price = new
        check.current_margin = pricing.margin(new, check.cost)
        check.decided_by, check.decided_at, check.updated_by = user, timezone.now(), user
        check.save()
    return check


def reject(check, user):
    if check.status != PriceCheck.Status.PENDING:
        raise BusinessError("Esta sugestão não está aguardando aprovação.", code="price_not_pending")
    check.status, check.decided_by, check.decided_at, check.updated_by = (
        PriceCheck.Status.REJECTED, user, timezone.now(), user)
    check.save()
    return check
