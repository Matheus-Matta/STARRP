"""A nota e as sugestões de um produto. Só lê o cadastro: quem grava é `apply`, depois de alguém aprovar.

Cada problema diz de onde veio: "regra" (do dicionário e das boas práticas) ou "busca" (dados de busca do Google). Sem
dados de busca, a nota é calculada sobre os outros critérios e a tela avisa. A nota mede o preenchimento: não promete
posição no Google. SKU, referência e finalidade fiscal são internos e nunca viram palavra-chave.
"""
import logging
import re
import threading
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify
from kombu.exceptions import OperationalError

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import BackgroundTask, CosmosFinding, Product, ProductVariant, SeoCheck
from starrp.services import background, catalog
from starrp.services.market import scope
from starrp.services.market.matching import full_title
from starrp.services.seo import ai as seo_ai
from starrp.services.seo import dictionary, keywords

logger = logging.getLogger(__name__)

TITLE_MAX, TITLE_MIN = 70, 30
DESCRIPTION_MAX, DESCRIPTION_MIN = 160, 70
SLUG_MAX = 75
KEYWORDS_SHOWN = 15
APPLICABLE = {"name": "suggested_name", "seo_title": "suggested_seo_title", "seo_description": "suggested_seo_description",
              "slug": "suggested_slug"}
CRITERIA = (("name", "Nome comercial", 25), ("demand", "Procura no Google", 25), ("seo_title", "Título no Google", 15),
            ("seo_description", "Resumo no Google", 15), ("slug", "Endereço (slug)", 10),
            ("identity", "Marca, categoria e tags", 10))


@dataclass
class Result:
    points: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    suggested: dict = field(default_factory=dict)
    keywords: list = field(default_factory=list)

    def problem(self, name, severity, message, origin="regra"):
        self.issues.append({"field": name, "severity": severity, "message": message, "origin": origin})


def _cut(text, limit):
    """Corta sem partir palavra."""
    if len(text) <= limit:
        return text
    return text[:limit + 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")


def _description_of(product, name):
    plain = " ".join(strip_tags(product.description or "").split())
    if len(plain) >= DESCRIPTION_MIN:
        return _cut(plain, DESCRIPTION_MAX)
    return _cut(f"{name}: veja preço, formas de pagamento e condições de entrega.", DESCRIPTION_MAX)


def _check_name(product, result):
    name, points = product.name, 25
    text, found = dictionary.expand(name)
    for problem in dict.fromkeys(found):
        result.problem("name", "warning", f"{problem} no nome do produto.")
        points -= 8
    if dictionary.is_shouting(name):
        result.problem("name", "info", "Nome todo em maiúsculas é mais difícil de ler.")
        points -= 4
        text = dictionary.nice_case(text, product.brand.name if product.brand_id else "", product.model_name)
    for message in dictionary.ambiguous(name):
        result.problem("name", "warning", message)
        points -= 5
    if len(name.split()) < 2:
        result.problem("name", "warning", "Nome com uma palavra só diz pouco sobre o produto.")
        points -= 10
    for internal in filter(None, (product.reference, product.default_variant.sku if product.default_variant else "")):
        if re.search(rf"\b{re.escape(internal)}\b", name, re.I):
            result.problem("name", "warning", "Código interno no nome: o cliente não busca por ele.")
            points -= 5
            break
    if text != name:
        result.suggested["name"] = text[:180]
    result.points["name"] = max(points, 0)
    return text


def _check_demand(product, name, result, metrics, ideas):
    """Compara o termo do cadastro com o equivalente. Sinônimo correto só perde ponto com dados a favor do outro."""
    terms = dictionary.terms_of(name)
    volumes = {term: (metrics[term].avg_monthly_searches or 0) for term in terms if term in metrics}
    best = max(volumes.values(), default=0)
    points = 25
    if not best:
        result.problem("demand", "info", "O Google não informou volume de busca para os termos deste nome.", "busca")
        points = 5
    lower = name.lower()
    for ours, other in dictionary.SYNONYMS:
        if not re.search(rf"\b{ours}\b", lower):
            continue
        mine, theirs = volumes.get(dictionary.search_term(ours), 0), volumes.get(dictionary.search_term(other), 0)
        if theirs and theirs >= max(mine, 1) * dictionary.SYNONYM_MIN_RATIO:
            result.problem("demand", "warning", f"\"{other}\" tem {theirs:,} buscas por mês; \"{ours}\" tem {mine:,}.".replace(",", "."), "busca")
            points = min(points, 15)
            replaced = re.sub(rf"\b{ours}\b", other.title(), result.suggested.get("name", name), flags=re.I)
            result.suggested["name"] = replaced[:180]
    result.points["demand"] = points
    rows = {term: "cadastro" for term in terms}
    rows.update({idea: "ideia" for idea in ideas if idea not in rows})
    listed = [metrics[term] for term in rows if term in metrics]
    listed.sort(key=lambda row: (rows[row.term] != "cadastro", -(row.avg_monthly_searches or 0)))
    result.keywords = [{"term": row.term, "avg_monthly_searches": row.avg_monthly_searches, "competition": row.competition,
                        "origin": rows[row.term]} for row in listed[:KEYWORDS_SHOWN]]


def _check_title(product, name, result):
    brand = product.brand.name if product.brand_id else ""
    wanted = _cut(full_title(name, brand, product.model_name), TITLE_MAX)
    title, points = product.seo_title.strip(), 15
    if not title:
        result.problem("seo_title", "warning", "Título no Google não preenchido.")
        points = 0
    else:
        if len(title) < TITLE_MIN:
            result.problem("seo_title", "info", f"Título curto ({len(title)} caracteres): cabe mais detalhe.")
            points -= 5
        if brand and brand.lower() not in title.lower():
            result.problem("seo_title", "info", "O título não cita a marca.")
            points -= 3
        if dictionary.expand(title)[1]:
            result.problem("seo_title", "warning", "O título tem abreviações.")
            points -= 5
    if not title or points < 15:
        if wanted != title:
            result.suggested["seo_title"] = wanted
    result.points["seo_title"] = max(points, 0)


def _check_description(product, name, result):
    text, points = product.seo_description.strip(), 15
    if not text:
        result.problem("seo_description", "warning", "Resumo no Google não preenchido.")
        points = 0
    else:
        if len(text) < DESCRIPTION_MIN:
            result.problem("seo_description", "info", f"Resumo curto ({len(text)} caracteres).")
            points -= 5
        if text.lower() == product.seo_title.strip().lower():
            result.problem("seo_description", "warning", "O resumo repete o título.")
            points -= 8
    if points < 15:
        wanted = _description_of(product, name)
        if wanted != text:
            result.suggested["seo_description"] = wanted
    result.points["seo_description"] = max(points, 0)


def _check_slug(product, name, result):
    slug, points = product.slug, 10
    wanted = catalog.free_slug(Product, product.account_id, name, product.pk)[:180]
    if not slug:
        result.problem("slug", "warning", "Sem endereço na loja virtual.")
        points = 0
    else:
        if len(slug) > SLUG_MAX:
            result.problem("slug", "info", "Endereço muito longo.")
            points -= 3
        if slug != slugify(slug):
            result.problem("slug", "warning", "Endereço com caracteres fora do padrão.")
            points -= 5
        if dictionary.expand(slug.replace("-", " "))[1]:
            result.problem("slug", "info", "O endereço tem abreviações. Trocar exige redirecionar o endereço antigo, se já foi publicado.")
            points -= 3
    if points < 10 and wanted != slug:
        result.suggested["slug"] = wanted
    result.points["slug"] = max(points, 0)


def _check_identity(product, result):
    points = 10
    if not product.brand_id:
        result.problem("identity", "info", "Sem marca cadastrada.")
        points -= 4
    if not product.category_id:
        result.problem("identity", "warning", "Sem categoria.")
        points -= 4
    if not product.tags.exists():
        result.problem("identity", "info", "Sem tags.")
        points -= 2
    result.points["identity"] = max(points, 0)


def analyze(product, metrics=None, ideas=()):
    """`metrics=None`: sem dados de busca; o critério da procura sai da conta, e a nota é proporcional ao resto."""
    result = Result()
    name = _check_name(product, result)
    if metrics is not None:
        _check_demand(product, name, result, metrics, ideas)
    name = result.suggested.get("name", name)
    _check_title(product, name, result)
    _check_description(product, name, result)
    _check_slug(product, name, result)
    _check_identity(product, result)
    return result


def _score(result):
    breakdown = [{"key": key, "label": label, "points": result.points[key], "max": most}
                 for key, label, most in CRITERIA if key in result.points]
    total = sum(row["max"] for row in breakdown)
    return round(sum(row["points"] for row in breakdown) * 100 / total), breakdown


def _save_result(check, result, error=""):
    check.score, check.breakdown = _score(result)
    check.has_search_data = "demand" in result.points
    check.issues, check.keywords = result.issues, result.keywords
    for name, column in APPLICABLE.items():
        setattr(check, column, result.suggested.get(name, ""))
    check.error, check.checked_at, check.reading_since = error[:300], timezone.now(), None
    if result.suggested:
        if check.status != SeoCheck.Status.REJECTED:
            check.status = SeoCheck.Status.PENDING
    else:
        check.status = SeoCheck.Status.APPLIED if check.status == SeoCheck.Status.APPLIED else SeoCheck.Status.NONE
    check.save()
    return check


ROUND_ALERT = "seo-rodada"


def _pending(account):
    return SeoCheck.all_objects.filter(account=account, status=SeoCheck.Status.PENDING, deleted_at__isnull=True).count()


def _ai_on(account):
    return account.cosmos_active and account.cosmos_seo_ai


def _alert_product(check, product):
    """Avisa quem supervisiona que há o que olhar neste produto, e fecha sozinho quando não há mais."""
    from starrp.services.cosmos import supervision

    if not _ai_on(product.account):
        return
    print_key = f"seo:{product.pk}"
    count = sum(bool(getattr(check, column)) for column in APPLICABLE.values())
    if check.status != SeoCheck.Status.PENDING or not count:
        supervision._settle(product.account, print_key, set())
        if not _pending(product.account):
            supervision._settle(product.account, ROUND_ALERT, set())
        return
    supervision.open_finding(product.account_id, print_key, rule="seo_melhorias", severity=CosmosFinding.Severity.INFO,
                             title=f"SEO de '{product.name}': há pontos a olhar",
                             detail="Há sugestões esperando aprovação no Analítico de SEO. Abra para aprovar o que fizer sentido.",
                             entity="seocheck", object_id=str(check.pk), endpoint="seo-checks/")


def batch_after(account, task):
    """A rodada avisa uma vez só, com o total: um alerta por produto encheria a lista de quem supervisiona."""
    from starrp.services.cosmos import supervision

    if not _ai_on(account):
        return
    count = _pending(account)
    supervision._settle(account, ROUND_ALERT, set())  # a rodada nova substitui o aviso da anterior, com o total de agora
    if count:
        products = "1 produto" if count == 1 else f"{count} produtos"
        supervision.open_finding(account.pk, f"{ROUND_ALERT}:{task.pk}", rule="seo_rodada", severity=CosmosFinding.Severity.INFO,
                                 title=f"Análise de SEO: {products} com pontos a olhar",
                                 detail="Há sugestões esperando aprovação. Abra o Analítico de SEO para aprovar o que fizer sentido.",
                                 entity="seocheck", endpoint="seo-checks/")


def _check_of(product):
    check = SeoCheck.all_objects.filter(product=product, deleted_at__isnull=True).first()
    return check or SeoCheck(account_id=product.account_id, product=product)


def read_product(product, bulk=False):
    """Analisa um produto. Os dados de busca são um extra: fora do ar ou sem saldo, a análise por regras continua.

    `bulk`: na rodada, os volumes já vieram de uma vez (`batch_before`), então este produto só lê o que está guardado."""
    check, metrics, ideas, error = _check_of(product), None, [], ""
    if bulk:
        metrics = keywords.cached(dictionary.terms_of(dictionary.expand(product.name)[0])) or None
    elif keywords.configured(product.account):
        terms = dictionary.terms_of(dictionary.expand(product.name)[0])
        try:
            metrics, ideas = keywords.fetch(product.account, terms)
        except keywords.KeywordError as failure:
            error = str(failure)
    result = analyze(product, metrics, ideas)
    seo_ai.improve(check, product, result)
    check = _save_result(check, result, error)
    if not bulk:
        _alert_product(check, product)
    return check


def read_products(account_id, product_ids, bulk=False):
    """O trabalho do worker. Um produto com problema não segura os outros nem fica "analisando" para sempre."""
    rows = Product.all_objects.filter(account_id=account_id, pk__in=product_ids, deleted_at__isnull=True).select_related(
        "brand", "account").prefetch_related("variants", "tags")
    done = 0
    for product in rows:
        try:
            read_product(product, bulk=bulk) if bulk else read_product(product)
            done += 1
        except Exception:  # noqa: BLE001
            logger.exception("SEO: falha em %s", product.pk)
            SeoCheck.all_objects.filter(product=product, deleted_at__isnull=True).update(
                reading_since=None, error="A análise falhou. Tente de novo.")
    return done


def _send(account, product_ids, user=None):
    from starrp.tasks.seo import seo_read

    ids = [str(pk) for pk in product_ids]
    task = background.begin(account, BackgroundTask.Kind.SEO_READ, len(ids), user)
    if settings.PRICE_READ_IN_THREAD:  # sem Redis não há worker: a tela não pode travar
        threading.Thread(target=seo_read, args=(str(account.pk), ids, str(task.pk)), daemon=True).start()
        return
    try:
        seo_read.delay(str(account.pk), ids, str(task.pk))
    except OperationalError as error:
        SeoCheck.all_objects.filter(product_id__in=product_ids, deleted_at__isnull=True).update(reading_since=None)
        background.fail(task.pk, "A fila está fora do ar. Tente de novo em instantes.")
        logger.exception("SEO: fila fora do ar")
        raise BusinessError("A fila da análise está fora do ar. Tente de novo em instantes.", code="seo_queue_down") from error


def _prepare(products):
    """Cria a análise de cada produto na hora e marca que está analisando."""
    checks, to_send, now = [], [], timezone.now()
    for product in products:
        check = _check_of(product)
        checks.append(check)
        if check.reading:
            continue
        check.reading_since = now
        check.save()
        to_send.append(product.pk)
    return checks, to_send


def start(account, products, user=None):
    """O clique em um produto ou item: cria a análise na hora e manda o trabalho para o worker. A tela espera e relê."""
    checks, to_send = _prepare(products)
    if to_send:
        _send(account, to_send, user)
    return checks


def start_product(account, product_id, user=None):
    product = Product.all_objects.filter(account=account, pk=product_id, deleted_at__isnull=True).first()
    if product is None:
        raise BusinessError("Produto não encontrado.", code="seo_product_missing")
    return start(account, [product], user)[0]


def _in_scope(account, started):
    """Dentro das regras da conta e ainda não analisados nesta rodada: nunca analisados primeiro, depois os mais antigos."""
    variants = (ProductVariant.all_objects.filter(account=account, deleted_at__isnull=True, is_active=True,
                                                  product__deleted_at__isnull=True))
    in_scope = scope.apply(variants, account, "seo_scope").values("product_id")
    last = SeoCheck.all_objects.filter(product=OuterRef("pk"), deleted_at__isnull=True).values("checked_at")[:1]
    return (Product.all_objects.filter(account=account, deleted_at__isnull=True, is_active=True, pk__in=in_scope)
            .annotate(last_check=Subquery(last)).filter(Q(last_check__isnull=True) | Q(last_check__lt=started))
            .order_by(F("last_check").asc(nulls_first=True)))


def in_scope_count(account):
    return _in_scope(account, timezone.now()).count()


def batch_total(account, started):
    return _in_scope(account, started).count()


def batch_next(account, started, size):
    return list(_in_scope(account, started)[:size])


def batch_before(account, started):
    """Antes do primeiro lote: os termos de todos os produtos da rodada, sem repetir, em uma consulta só.
    Devolve o aviso, se falhar: a análise segue com as regras."""
    if not keywords.configured(account):
        return ""
    terms = []
    for name in _in_scope(account, started).values_list("name", flat=True):
        terms += dictionary.terms_of(dictionary.expand(name)[0])
    try:
        keywords.fetch_many(account, terms)
    except keywords.KeywordError as failure:
        return str(failure)
    return ""


def batch_process(account, products):
    to_read = _prepare(products)[1]
    if to_read:
        read_products(str(account.pk), to_read, bulk=True)


@transaction.atomic
def apply(check, user, fields):
    """Grava no cadastro as sugestões aprovadas. O histórico do produto registra quem aprovou e o que mudou."""
    unknown = set(fields) - set(APPLICABLE)
    if unknown or not fields:
        raise BusinessError("Escolha ao menos uma sugestão.", code="seo_fields_invalid")
    product = Product.all_objects.select_for_update().get(pk=check.product_id, account_id=check.account_id)
    changed = []
    for name in fields:
        value = getattr(check, APPLICABLE[name])
        if not value:
            raise StateConflict("Esta sugestão não está mais disponível. Analise de novo.")
        if name == "slug":
            value = catalog.free_slug(Product, product.account_id, value, product.pk)[:180]
        setattr(product, name, value)
        changed.append(name)
    product.updated_by = user
    product.save(update_fields=[*changed, "updated_by", "updated_at"])
    check.status, check.decided_by, check.decided_at = SeoCheck.Status.APPLIED, user, timezone.now()
    product = Product.all_objects.select_related("brand", "account").get(pk=product.pk)
    # Reavalia só com o que já está guardado: aplicar nunca gasta consulta.
    terms = dictionary.terms_of(dictionary.expand(product.name)[0])
    saved = keywords.cached(terms) if check.has_search_data else None
    result = analyze(product, saved)
    seo_ai.merge(result, check.ai_result or {}, skip=fields)  # as outras sugestões da Cosmos continuam; aplicar não gasta token
    check.updated_by = user
    check = _save_result(check, result)
    _alert_product(check, product)
    return check


def reject(check, user):
    if check.status != SeoCheck.Status.PENDING:
        raise StateConflict("Estas sugestões não estão aguardando aprovação.")
    check.status, check.decided_by, check.decided_at, check.updated_by = SeoCheck.Status.REJECTED, user, timezone.now(), user
    check.save()
    _alert_product(check, check.product)
    return check
