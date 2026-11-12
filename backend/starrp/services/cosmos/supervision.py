"""Supervisão da equipe: o que cada um fez e o que ficou errado — e o aviso, sem ninguém perguntar.

Duas fontes de alerta (`CosmosFinding`):

1. **No ato** (`check_instance`, chamado depois de gravar produto, variante, cliente, fornecedor
   e venda): cadastro incompleto ou incoerente (CPF/CNPJ inválido, documento repetido, preço
   zerado ou abaixo do custo, produto sem NCM/categoria), venda com desconto alto ou abaixo do custo.
2. **Na varredura** (`sweep`, a cada 30 min pelo Celery): padrões que só aparecem no conjunto —
   muitos cancelamentos do mesmo usuário no dia, estoque negativo, diferença de caixa em aberto, entregas e
   recebimentos parados, organização do estoque.

Cada alerta diz QUEM fez (o `actor`), tem uma impressão digital (`fingerprint`) para não repetir,
e vai na hora para o widget de quem supervisiona aquela filial (`cosmos.supervise`).

`team_activity` responde "quem está fazendo o quê": as gravações de cada pessoa no período,
lidas do histórico (django-simple-history) de todas as models.
"""
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone

from starrp.core.text import only_digits
from starrp.models import (
    Account, CashDiscrepancy, CosmosFinding, Customer, Product, ProductVariant, Sale, StockBalance, StockDocument,
    StockMovement, Supplier, UserProfile,
)
from starrp.services.cosmos import events

logger = logging.getLogger(__name__)

HIGH_DISCOUNT_PERCENT = Decimal("20")
CANCELLATIONS_PER_DAY = 3
SWEEP_SECONDS = 30 * 60
Severity = CosmosFinding.Severity


# ── validação de documento ─────────────────────────────────────────────────
def _cpf_ok(digits):
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=False))
        if (total * 10 % 11) % 10 != int(digits[size]):
            return False
    return True


def _cnpj_ok(digits):
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    for size, weights in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        rest = sum(int(d) * w for d, w in zip(digits[:size], weights, strict=True)) % 11
        if (0 if rest < 2 else 11 - rest) != int(digits[size]):
            return False
    return True


def document_ok(value):
    digits = only_digits(value or "")
    return not digits or (_cpf_ok(digits) if len(digits) == 11 else _cnpj_ok(digits))


def _money(value):
    """R$ 1.234,56 (o título do alerta é lido por gente)."""
    return "R$ " + f"{value or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _qty(value):
    text = f"{value or 0:,.3f}".rstrip("0").rstrip(".")
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


# ── regras por registro ────────────────────────────────────────────────────
def _who(instance):
    return getattr(instance, "updated_by", None) or getattr(instance, "created_by", None)


def _party(instance, kind, endpoint):
    model = type(instance)
    label = "cliente" if kind == "customer" else "fornecedor"
    found = []
    if instance.document and not document_ok(instance.document):
        found.append(("documento_invalido", Severity.WARNING,
                      f"{label.capitalize()} '{instance.name}' com CPF/CNPJ inválido ({instance.document})",
                      "Os dígitos verificadores não conferem: a nota fiscal será recusada."))
    if instance.document:
        twin = (model.all_objects.filter(account_id=instance.account_id, document=instance.document,
                                         deleted_at__isnull=True).exclude(pk=instance.pk).first())
        if twin is not None:
            found.append(("documento_repetido", Severity.WARNING,
                          f"{label.capitalize()} '{instance.name}' repete o documento de '{twin.name}'",
                          "Dois cadastros com o mesmo CPF/CNPJ dividem histórico e crédito; una os dois."))
    if kind == "customer" and not instance.phone and not instance.email:
        found.append(("contato_ausente", Severity.INFO, f"Cliente '{instance.name}' sem telefone e sem e-mail",
                      "Sem contato não há como avisar entrega nem pedir avaliação."))
    return [(rule, sev, title, detail, endpoint) for rule, sev, title, detail in found]


def _product(instance):
    found = []
    if instance.type != "service" and not instance.fiscal_ncm:
        found.append(("produto_sem_ncm", Severity.WARNING, f"Produto '{instance.name}' sem NCM",
                      "Sem NCM a venda não sai em NFC-e/NF-e.", "catalog/products"))
    if not instance.category_id:
        found.append(("produto_sem_categoria", Severity.INFO, f"Produto '{instance.name}' sem categoria",
                      "Fica fora dos relatórios por categoria e das regras de serviço.", "catalog/products"))
    return found


def _variant(instance):
    found = []
    name = f"{instance.product.name}{f' ({instance.name})' if instance.name else ''}"
    if instance.is_active and instance.price <= 0 and instance.product.type != "service":
        found.append(("preco_zerado", Severity.CRITICAL, f"'{name}' está com preço zerado",
                      "O PDV venderia de graça.", "catalog/products"))
    cost = instance.average_cost or instance.last_cost or Decimal("0")
    if instance.is_active and cost > 0 and 0 < instance.price < cost:
        found.append(("preco_abaixo_custo", Severity.CRITICAL,
                      f"'{name}' com preço {_money(instance.price)} abaixo do custo {_money(cost)}",
                      "Cada venda dá prejuízo.", "catalog/products"))
    return found


def _sale(instance):
    found = []
    if instance.status != Sale.Status.COMPLETED:
        return found
    gross = instance.subtotal or Decimal("0")
    discount = (instance.discount or 0) + (instance.coupon_discount or 0)
    if gross > 0 and discount / gross * 100 >= HIGH_DISCOUNT_PERCENT:
        pct = discount / gross * 100
        found.append(("desconto_alto", Severity.WARNING, f"Venda nº {instance.number} com {pct:.0f}% de desconto",
                      f"{_money(discount)} de desconto sobre {_money(gross)}.", "sales"))
    below = [item for item in instance.items.filter(status="active", parent_item__isnull=True)
             if item.unit_cost and item.quantity and item.total < item.unit_cost * item.quantity]
    if below:
        names = ", ".join(i.description for i in below[:3])
        found.append(("venda_abaixo_custo", Severity.CRITICAL, f"Venda nº {instance.number} com item abaixo do custo",
                      f"Vendido abaixo do custo: {names}.", "sales"))
    return found


def _actor_of_sale(sale):
    return sale.operator or sale.seller or _who(sale)


RULES = {
    Customer: lambda i: _party(i, "customer", "customers"),
    Supplier: lambda i: _party(i, "supplier", "suppliers"),
    Product: _product,
    ProductVariant: _variant,
    Sale: _sale,
}


def _subject(instance):
    """O registro que a tela abre (a variante abre o produto)."""
    if isinstance(instance, ProductVariant):
        return "product", instance.product_id
    return instance._meta.model_name, instance.pk


def check_instance(instance):
    """Reavalia um registro: abre o que está errado e fecha sozinho o que já foi corrigido."""
    rule_fn = RULES.get(type(instance))
    if rule_fn is None or instance.deleted_at is not None or not instance.account.cosmos_active:
        return []
    try:
        found = rule_fn(instance)
    except Exception:  # noqa: BLE001 — supervisão nunca derruba a gravação de ninguém
        logger.exception("Cosmos: falha na supervisão de %s %s", type(instance).__name__, instance.pk)
        return []
    entity, object_id = _subject(instance)
    actor = _actor_of_sale(instance) if isinstance(instance, Sale) else _who(instance)
    store_id = getattr(instance, "store_id", None)
    rules_now = {rule for rule, *_ in found}
    prefix = f"{type(instance)._meta.model_name}:{instance.pk}:"
    stale = CosmosFinding.all_objects.filter(account_id=instance.account_id, status=CosmosFinding.Status.OPEN,
                                             fingerprint__startswith=prefix)
    for finding in stale:
        if finding.rule not in rules_now:
            finding.status, finding.resolved_at = CosmosFinding.Status.RESOLVED, timezone.now()
            finding.save(update_fields=["status", "resolved_at", "updated_at"])
    created = []
    for rule, severity, title, detail, endpoint in found:
        finding = open_finding(instance.account_id, f"{prefix}{rule}", rule=rule, severity=severity, title=title,
                               detail=detail, actor=actor, store_id=store_id, entity=entity,
                               object_id=str(object_id), endpoint=endpoint)
        if finding is not None:
            created.append(finding)
    return created


def open_finding(account_id, fingerprint, **fields):
    """Cria o alerta se ainda não há um aberto igual; avisa quem supervisiona. `None` = já existia.

    Alerta que uma PESSOA fechou (descartou ou marcou como resolvido) não volta: a varredura acha a
    mesma diferença de caixa ou o mesmo estoque negativo a cada 30 min, e reabrir seria ignorar a
    decisão dela. Só o que o próprio sistema fechou (o registro foi corrigido) pode reabrir se
    estragar de novo. Mudou o problema (outro valor, outro dia) → outra impressão digital, alerta novo."""
    fingerprint = fingerprint[:200]
    same = CosmosFinding.all_objects.filter(account_id=account_id, fingerprint=fingerprint, deleted_at__isnull=True)
    if same.filter(Q(status=CosmosFinding.Status.OPEN) | Q(status=CosmosFinding.Status.DISMISSED)
                   | Q(status=CosmosFinding.Status.RESOLVED, resolved_by__isnull=False)).exists():
        return None
    try:
        with transaction.atomic():
            finding = CosmosFinding.all_objects.create(account_id=account_id, fingerprint=fingerprint, **fields)
    except IntegrityError:  # outra gravação abriu o mesmo alerta ao mesmo tempo
        return None
    transaction.on_commit(lambda: notify(finding), robust=True)
    return finding


def supervisors(account_id, store_id):
    """Ids dos usuários que recebem o alerta desta filial (admin ou `cosmos.supervise`)."""
    out = []
    profiles = (UserProfile.all_objects.filter(account_id=account_id, is_active=True, deleted_at__isnull=True)
                .select_related("role", "user").prefetch_related("extra_roles", "stores"))
    for profile in profiles:
        if not profile.user.is_active:
            continue
        if not (profile.is_account_admin or "cosmos.supervise" in profile.permission_codes()):
            continue
        allowed = profile.allowed_store_ids()
        if store_id is None or allowed is None or store_id in allowed:
            out.append(profile.user_id)
    return out


def finding_payload(finding):
    actor = finding.actor
    return {"id": str(finding.pk), "rule": finding.rule, "severity": finding.severity, "title": finding.title,
            "detail": finding.detail, "entity": finding.entity, "object_id": finding.object_id,
            "endpoint": finding.endpoint, "status": finding.status, "created_at": finding.created_at.isoformat(),
            "actor": (actor.get_full_name() or actor.username) if actor else None,
            "message": alert_text(finding)}


def alert_text(finding):
    """A fala da Cosmos no widget: quem fez, o que está errado e por quê."""
    who = finding.actor.get_full_name() or finding.actor.username if finding.actor else "Alguém da equipe"
    return f"{who}: {finding.title}. {finding.detail}".strip()


def notify(finding):
    payload = finding_payload(finding)
    for user_id in supervisors(finding.account_id, finding.store_id):
        if finding.actor_id == user_id and finding.severity != Severity.CRITICAL:
            continue  # quem errou e supervisiona vê na lista, sem ser cutucado por si mesmo
        events.send(user_id, {"type": "alert", "finding": payload})


# ── varredura ───────────────────────────────────────────────────────────────
def sweep(account=None):
    """Padrões do dia para cada conta ativa (ou só a informada). Devolve quantos alertas abriu."""
    accounts = [account] if account else Account.objects.filter(status=Account.Status.ACTIVE)
    opened = 0
    for acc in accounts:
        if not acc.cosmos_active:  # sem o módulo, a Cosmos não trabalha nem avisa
            continue
        for check in (_cancellations, _negative_stock, _cash_discrepancies, _deliveries, _receiving, _stock_advice):
            try:
                opened += check(acc)
            except Exception:  # noqa: BLE001 — uma regra com defeito não derruba as outras
                logger.exception("Cosmos: falha na varredura %s da conta %s", check.__name__, acc.pk)
        # O status do widget usa este sinal para não repetir uma varredura que o Celery acabou de fazer.
        cache.set(f"cosmos:sweep:{acc.pk}", 1, SWEEP_SECONDS)
    return opened


def _cancellations(account):
    today = timezone.localdate()
    rows = (Sale.all_objects.filter(account=account, status=Sale.Status.CANCELLED, cancelled_at__date=today,
                                    cancelled_by__isnull=False)
            .values("cancelled_by", "store").annotate(n=Count("id")).filter(n__gte=CANCELLATIONS_PER_DAY))
    users = get_user_model().objects.in_bulk([r["cancelled_by"] for r in rows])
    opened = 0
    for row in rows:
        user = users.get(row["cancelled_by"])
        title = f"{row['n']} vendas canceladas hoje pelo mesmo usuário"
        opened += bool(open_finding(account.pk, f"cancel:{row['cancelled_by']}:{row['store']}:{today}",
                                    rule="muitos_cancelamentos", severity=Severity.WARNING, title=title,
                                    detail="Acima do normal para um dia; confira os motivos no relatório de cancelamentos.",
                                    actor=user, store_id=row["store"], entity="sale", endpoint="sales"))
    return opened


def _negative_stock(account):
    opened = 0
    last_operator = (StockMovement.all_objects.filter(
        account=account, variant_id=OuterRef("variant_id"), warehouse_id=OuterRef("warehouse_id"))
        .order_by("-created_at").values("operator_id")[:1])
    rows = (StockBalance.all_objects.filter(account=account, quantity__lt=0, variant__deleted_at__isnull=True)
            .select_related("variant__product", "warehouse").annotate(last_operator_id=Subquery(last_operator))[:50])
    users = get_user_model().objects.in_bulk([row.last_operator_id for row in rows if row.last_operator_id])
    for balance in rows:
        title = f"Estoque negativo: {balance.variant.product.name} ({_qty(balance.quantity)} em {balance.warehouse.name})"
        opened += bool(open_finding(account.pk, f"negstock:{balance.pk}", rule="estoque_negativo",
                                    severity=Severity.WARNING, title=title,
                                    detail="Saiu mais do que entrou: falta lançar uma entrada ou houve erro de contagem.",
                                    actor=users.get(balance.last_operator_id), store_id=balance.warehouse.store_id,
                                    entity="product", object_id=str(balance.variant.product_id),
                                    endpoint="catalog/products"))
    still = {f"negstock:{pk}" for pk in StockBalance.all_objects.filter(account=account, quantity__lt=0)
             .values_list("pk", flat=True)}
    _settle(account, "negstock:", still)
    return opened


def _cash_discrepancies(account):
    opened = 0
    rows = (CashDiscrepancy.all_objects.filter(account=account, status="open", deleted_at__isnull=True)
            .select_related("session")[:50])
    for item in rows:
        session = item.session
        operator = getattr(session, "operator", None) or getattr(session, "opened_by", None)
        opened += bool(open_finding(account.pk, f"cashdiff:{item.pk}", rule="diferenca_caixa",
                                    severity=Severity.CRITICAL if abs(item.amount) >= 50 else Severity.WARNING,
                                    title=f"Diferença de caixa de {_money(item.amount)} sem resolução",
                                    detail=item.reason[:300], actor=operator, store_id=getattr(session, "store_id", None),
                                    entity="cashsession", object_id=str(session.pk), endpoint="cash/sessions"))
    still = {f"cashdiff:{pk}" for pk in CashDiscrepancy.all_objects.filter(account=account, status="open",
                                                                           deleted_at__isnull=True)
             .values_list("pk", flat=True)}
    _settle(account, "cashdiff:", still)
    return opened


# (situação, campo da data, dias de tolerância, texto). O sistema não tem data prometida: conta o tempo parado em cada etapa.
DELIVERY_STAGES = (
    ("pending", "completed_at", 2, "aguardando separação"),
    ("ready", "ready_at", 1, "separadas e sem sair para entrega"),
    ("shipped", "shipped_at", 5, "em rota e sem confirmação de entrega"),
)
RECEIVING_DAYS = 3


def _stock_on(account):
    from starrp.services.cosmos import slotting

    return slotting.enabled(account)


def _deliveries(account):
    """Um alerta por dia, filial e etapa, com o total. Fecha sozinho no dia seguinte ou quando não há mais nada parado."""
    still, opened, now = set(), 0, timezone.now()
    if _stock_on(account):
        for stage, moment, days, text in DELIVERY_STAGES:
            rows = (Sale.all_objects.filter(account=account, status=Sale.Status.COMPLETED, fulfillment_status=stage, deleted_at__isnull=True,
                                            shipping_address__isnull=False, **{f"{moment}__lt": now - timedelta(days=days)})
                    .order_by(moment).values("store", "number"))
            stores = defaultdict(list)
            for row in rows:
                stores[row["store"]].append(row["number"])
            for store, numbers in stores.items():
                key = f"delivery:{stage}:{store}:{timezone.localdate()}"
                still.add(key)
                sample = ", ".join(str(n) for n in numbers[:5]) + (" e outras" if len(numbers) > 5 else "")
                opened += bool(open_finding(account.pk, key, rule="entrega_parada", severity=Severity.WARNING,
                                            title=f"{len(numbers)} entrega(s) {text} há mais de {days} dia(s)",
                                            detail=f"Vendas {sample}. Confira com a logística e avise o cliente, se for atrasar.",
                                            store_id=store, entity="sale", endpoint="sales"))
    _settle(account, "delivery:", still)
    return opened


def _receiving(account):
    """Entrada lançada e não confirmada: a mercadoria chegou, ou deveria, e o saldo não subiu."""
    still, opened = set(), 0
    if _stock_on(account):
        rows = (StockDocument.all_objects.filter(account=account, kind=StockDocument.Kind.ENTRY, status=StockDocument.Status.DRAFT, deleted_at__isnull=True,
                                                 created_at__lt=timezone.now() - timedelta(days=RECEIVING_DAYS))
                .order_by("created_at").values("store", "number"))
        stores = defaultdict(list)
        for row in rows:
            stores[row["store"]].append(row["number"])
        for store, numbers in stores.items():
            key = f"receiving:{store}:{timezone.localdate()}"
            still.add(key)
            sample = ", ".join(str(n) for n in numbers[:5]) + (" e outras" if len(numbers) > 5 else "")
            opened += bool(open_finding(account.pk, key, rule="recebimento_parado", severity=Severity.WARNING,
                                        title=f"{len(numbers)} recebimento(s) sem confirmar há mais de {RECEIVING_DAYS} dias",
                                        detail=f"Entradas {sample}. O saldo só sobe quando a entrada é confirmada.",
                                        store_id=store, entity="stockdocument", endpoint="stock/documents"))
    _settle(account, "receiving:", still)
    return opened


def _stock_advice(account):
    """Uma análise por dia: a varredura roda de 30 em 30 minutos, e o armazém não muda de padrão tão rápido."""
    from starrp.services.cosmos import slotting

    if not _stock_on(account) or not cache.add(f"cosmos:stock-advice:{account.pk}:{timezone.localdate()}", 1, 24 * 3600):
        return 0
    return slotting.analyze(account)


def _settle(account, prefix, still):
    """O problema da varredura sumiu (estoque voltou ao positivo, diferença resolvida no caixa):
    o alerta aberto fecha sozinho, e o fechado por alguém é "arquivado" — se o problema voltar
    um dia, é um episódio novo e avisa de novo."""
    done = (CosmosFinding.all_objects.filter(account=account, fingerprint__startswith=prefix, deleted_at__isnull=True)
            .exclude(fingerprint__contains=":fim:"))
    for finding in done:
        if finding.fingerprint in still:
            continue
        if finding.status == CosmosFinding.Status.OPEN:
            finding.status, finding.resolved_at = CosmosFinding.Status.RESOLVED, timezone.now()
        finding.fingerprint = f"{finding.fingerprint}:fim:{finding.pk}"[:200]
        finding.save(update_fields=["status", "resolved_at", "fingerprint", "updated_at"])


# ── quem fez o quê ──────────────────────────────────────────────────────────
HISTORY_LABEL = {"+": "criou", "~": "alterou", "-": "excluiu"}


def _history_models():
    from starrp.models import HISTORY_TRACKED  # noqa: F401 — garante o registro antes de ler
    from starrp.models.base import TimeStampedModel
    from starrp.models.history import _concrete

    for model in dict.fromkeys(_concrete(TimeStampedModel)):
        attribute = getattr(model._meta, "simple_history_manager_attribute", None)
        if model.__name__.startswith("Historical") or not attribute:
            continue
        if "account" in {f.name for f in model._meta.fields}:
            yield model, getattr(model, attribute).model


def _visible_users(actor):
    from starrp.services.store_access import visible_profiles

    actor.bind()
    return set(visible_profiles(UserProfile.objects.all()).values_list("user_id", flat=True))


def _admins(account):
    return {p.user_id for p in UserProfile.all_objects.filter(account=account, deleted_at__isnull=True)
            .select_related("role").prefetch_related("extra_roles") if p.is_account_admin}


def team_activity(actor, date_from=None, date_to=None, user_id=None, limit=40, skip_admins=False):
    """{"people": [{"user", "counts": {"Produto": {"criou": 3}}, "total"}], "recent": [...]}"""
    from starrp.services.reports import period

    start, end = period({"date_from": date_from or str(timezone.localdate()), "date_to": date_to or ""})
    visible = _visible_users(actor)
    if skip_admins:
        visible -= _admins(actor.account)
    if user_id:
        visible &= {int(user_id)}
    counts = defaultdict(lambda: defaultdict(Counter))
    recent = []
    for model, history in _history_models():
        qs = history.objects.filter(account_id=actor.account.pk, history_date__range=(start, end),
                                    history_user_id__in=visible)
        label = str(model._meta.verbose_name).capitalize()
        for row in qs.values("history_user_id", "history_type").annotate(n=Count("history_id")):
            counts[row["history_user_id"]][label][HISTORY_LABEL[row["history_type"]]] += row["n"]
        if user_id:
            name_field = next((f for f in ("name", "description", "title", "number") if hasattr(history, f)), None)
            fields = ["history_date", "history_type", "id"] + ([name_field] if name_field else [])
            for row in qs.order_by("-history_date").values(*fields)[:limit]:
                recent.append({"at": row["history_date"], "what": label, "action": HISTORY_LABEL[row["history_type"]],
                               "record": str(row.get(name_field) or row["id"])})
    users = get_user_model().objects.in_bulk(list(counts))
    people = []
    for uid, by_model in counts.items():
        user = users.get(uid)
        total = sum(sum(c.values()) for c in by_model.values())
        people.append({"user": (user.get_full_name() or user.username) if user else str(uid), "user_id": uid,
                       "total": total, "counts": {k: dict(v) for k, v in by_model.items()}})
    people.sort(key=lambda p: -p["total"])
    recent.sort(key=lambda r: r["at"], reverse=True)
    findings = (CosmosFinding.all_objects.filter(account=actor.account, deleted_at__isnull=True, actor_id__in=visible)
                .values("actor_id").annotate(
                    abertos=Count("id", filter=Q(status=CosmosFinding.Status.OPEN)),
                    no_periodo=Count("id", filter=Q(created_at__range=(start, end)))))
    by_user = {r["actor_id"]: r for r in findings}
    for person in people:
        row = by_user.get(person["user_id"], {})
        person["alertas_abertos"] = row.get("abertos", 0)
        person["alertas_no_periodo"] = row.get("no_periodo", 0)  # qualidade: erros apontados no período
    return {"period": {"from": str(start.date()), "to": str(end.date())}, "people": people[:50],
            "recent": [{**r, "at": timezone.localtime(r["at"]).strftime("%d/%m %H:%M")} for r in recent[:limit]]}


# O que a pessoa mais faz no sistema → os atalhos da Cosmos para ela (tema → models do histórico).
HABIT_TOPICS = {
    "product": "products", "productvariant": "products", "category": "products", "brand": "products",
    "sale": "sales", "saleitem": "sales", "salereturn": "sales",
    "customer": "customers", "customeraddress": "customers", "supplier": "suppliers",
    "stockbalance": "stock", "stockmovement": "stock", "stocklot": "stock", "stockdocument": "stock",
    "cashsession": "cash", "cashmovement": "cash", "cashdiscrepancy": "cash",
    "financialtitle": "finance", "installment": "finance", "financialtransaction": "finance",
}
HABIT_DAYS = 30


def habits(user, account_id):
    """Temas que o usuário mais grava nos últimos 30 dias, do mais frequente ao menos (ex.: ["sales", "stock"])."""
    since = timezone.now() - timedelta(days=HABIT_DAYS)
    score = Counter()
    for model, history in _history_models():
        topic = HABIT_TOPICS.get(model._meta.model_name)
        if topic is None:
            continue
        score[topic] += history.objects.filter(account_id=account_id, history_user_id=user.pk,
                                               history_date__gte=since).count()
    return [topic for topic, n in score.most_common() if n]


def open_findings(actor, limit=30):
    """Alertas abertos que o usuário enxerga (filiais dele), do mais grave ao mais leve."""
    actor.bind()
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    qs = CosmosFinding.objects.filter(status=CosmosFinding.Status.OPEN).select_related("actor")
    if actor.store is not None:
        qs = qs.filter(Q(store=actor.store) | Q(store__isnull=True))
    rows = sorted(qs[:200], key=lambda f: (order.get(f.severity, 3), -f.created_at.timestamp()))
    return [finding_payload(f) for f in rows[:limit]]

