"""De onde vêm os preços da precificação. A plataforma escolhe, por conta, no admin do Django.

A conta nunca vê qual API foi usada: `public_key`, `public_sources` e `public_error` trocam o nome real por
"Google Shopping" (scraping), "Banco colaborativo" (bases abertas) ou "Pesquisa da equipe" em tudo que sai pela API.
A pesquisa da equipe é sempre ativa, com o módulo ligado.

- `manual`: preços de concorrentes que a equipe informa (tela ou planilha). Grátis, sem limite.
- `open_prices`: base aberta da Open Food Facts, preços enviados por pessoas, por código de barras.
  Grátis e sem chave, mas com pouca cobertura no Brasil (mais mercado e alimento).
- `cosmos`: preço médio do catálogo Bluesoft Cosmos, por código de barras (`BLUESOFT_COSMOS_TOKEN`).
- `google_shopping`: ofertas do Google Shopping pela ferramenta própria (projeto search-shop: `SHOPPING_SEARCH_URL` e
  `SHOPPING_SEARCH_TOKEN`).
- `serpapi`: ofertas do Google Shopping pela SerpApi (`SERPAPI_KEY`).
- `brightdata`: ofertas do Google Shopping pela SERP API da Bright Data (`BRIGHTDATA_API_KEY` e `BRIGHTDATA_ZONE`).

Ordem da leitura (ver `tracker._read`): a pesquisa da equipe sempre entra; depois Google Shopping, SerpApi e Bright Data, na
ordem da conta e conforme `Account.price_search_mode`, cada um pelo título com marca e modelo e, se nenhuma oferta passar
da confiança mínima da conta, pelo EAN; ainda abaixo do mínimo de concorrentes, as de código.

A chave vem da conta (`PriceSourceToken`, só no admin do Django) e, sem ela, a global do `.env`. O mesmo vale para o
endereço da ferramenta própria e a zona da Bright Data (`PriceSourceToken.option`).
As fontes com chave (`metered`) têm dois limites: o mensal da conta (`Account.price_monthly_requests`, vale com
qualquer chave) e o teto por dia da plataforma (`PRICE_DAILY_LIMITS`, só para a chave global). Passou de um deles,
a leitura usa as ofertas guardadas da última vez (ver `tracker`).
Cada fonte devolve ofertas no mesmo formato; `SourceError` não derruba as outras.
"""
import re
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from starrp.models import Account, CompetitorPrice, PriceSourceToken, PriceUsage

TIMEOUT = 15
SEARCH_TIMEOUT = 45  # o serviço abre um navegador por busca (até 20 s) e pode ter fila
SEARCH_MAX_QUERY = 200  # o serviço recusa mais que isso
USER_AGENT = "Starrp-ERP"
MANUAL_DAYS = 60  # preço informado há mais tempo que isto não vale como mercado de hoje
OPEN_PRICES_DAYS = 180


class SourceError(Exception):
    """A fonte não respondeu como devia (fora do ar, chave recusada, limite de chamadas)."""


def _offer(external_id, title, price, *, url="", seller="", free_shipping=False, brand="", model="", gtins=(),
           trusted=False):
    return {"external_id": str(external_id), "title": title or "", "url": url or "", "seller": seller or "",
            "price": price, "free_shipping": free_shipping, "brand": brand or "", "model": model or "",
            "gtins": list(gtins), "trusted": trusted}


def _get(label, url, **kwargs):
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        return requests.get(url, headers=headers, **kwargs)
    except requests.RequestException as error:
        raise SourceError(f"{label} fora do ar.") from error


def _json(label, response):
    if response.status_code in (401, 403):
        raise SourceError(f"{label} recusou a chave ({response.status_code}).")
    if response.status_code == 429:
        raise SourceError(f"{label}: limite de consultas atingido.")
    if response.status_code != 200:
        raise SourceError(f"{label} respondeu {response.status_code}.")
    try:
        return response.json()
    except ValueError as error:
        raise SourceError(f"{label} respondeu algo inesperado.") from error


def read_manual(variant, ours):
    since = timezone.localdate() - timedelta(days=MANUAL_DAYS)
    rows = CompetitorPrice.all_objects.filter(variant=variant, deleted_at__isnull=True, observed_on__gte=since)
    latest = {}
    for row in rows.order_by("-observed_on", "-created_at"):  # o mais novo de cada concorrente
        latest.setdefault(row.competitor.strip().casefold(), row)
    return [_offer(row.pk, ours.title, row.price, url=row.url, seller=row.competitor, trusted=True)
            for row in latest.values()]


def read_open_prices(variant, ours):
    if not ours.gtins:
        return []
    since = timezone.localdate() - timedelta(days=OPEN_PRICES_DAYS)
    label = "Open Prices"
    body = _json(label, _get(label, "https://prices.openfoodfacts.org/api/v1/prices", params={
        "product_code": ours.gtins[0], "currency": "BRL", "date__gte": str(since), "size": 50, "order_by": "-date"}))
    latest = {}
    for item in body.get("items") or []:
        if item.get("duplicate_of") or item.get("price_per") or not item.get("price"):
            continue
        latest.setdefault(item.get("location_id"), item)  # já vem do mais novo para o mais velho
    offers = []
    for item in latest.values():
        product = item.get("product") or {}
        offers.append(_offer(item.get("id"), product.get("product_name") or ours.title, item["price"],
                             seller=(item.get("location") or {}).get("osm_name") or "",
                             brand=product.get("brands") or "", gtins=[item.get("product_code") or ours.gtins[0]]))
    return offers


def read_cosmos(variant, ours, token):
    label = "Bluesoft Cosmos"
    response = _get(label, f"https://api.cosmos.bluesoft.com.br/gtins/{ours.gtins[0]}.json",
                    headers={"X-Cosmos-Token": token})
    if response.status_code == 404:
        return []
    body = _json(label, response)
    if not body.get("avg_price"):
        return []
    return [_offer(body.get("gtin") or ours.gtins[0], body.get("description") or ours.title, body["avg_price"],
                   seller="Preço médio do mercado", brand=(body.get("brand") or {}).get("name") or "",
                   gtins=[str(body.get("gtin") or ours.gtins[0])])]


def _market_codes(ours):
    """Os códigos que o mercado conhece (EAN e GTIN), o principal primeiro. Prefixo 2 é etiqueta interna da loja: fora
    dela não existe. O mesmo número com zero à esquerda (07891... = 7891...) conta uma vez."""
    codes = {}
    for code in ours.gtins:
        if code.isdigit() and 8 <= len(code) <= 14 and not code.startswith("2"):
            codes.setdefault(code.lstrip("0"), code)
    return list(codes.values())


def _shopping_queries(ours):
    """O título (já com marca e modelo, ver `matching.full_title`) e depois cada EAN/GTIN do mercado.

    O resultado da busca por EAN NÃO confirma o produto: vem junto coisa nada a ver. Por isso a oferta
    não leva o GTIN e passa pelo critério da busca por código (`matching.score_by_code`)."""
    return [ours.title, *_market_codes(ours)]


def read_serpapi(query, token):
    label = "SerpApi"
    body = _json(label, _get(label, "https://serpapi.com/search.json", params={
        "engine": "google_shopping", "q": query, "gl": "br", "hl": "pt-br", "google_domain": "google.com.br",
        "api_key": token}))
    if body.get("error") and not body.get("shopping_results"):
        if "any results" in str(body["error"]):
            return []
        raise SourceError(f"{label}: {str(body['error'])[:120]}")
    offers = []
    for item in body.get("shopping_results") or []:
        # Só o que veio em reais: com gl=br ainda pode aparecer loja de fora.
        if not item.get("extracted_price") or not str(item.get("price", "")).startswith("R$"):
            continue
        offers.append(_offer(item.get("product_id") or item.get("position"), item.get("title"), item["extracted_price"],
                             url=item.get("product_link"), seller=item.get("source")))
    return offers


def _free_shipping(text):
    return bool(re.search(r"gr[aá]tis", text or "", re.I))


def _reais(text):
    """ "R$ 1.299,90" → Decimal("1299.90"). Outra moeda ou texto sem preço: `None`."""
    match = re.match(r"\s*R\$\s*([\d.,]+)", str(text or ""))
    if not match:
        return None
    number = match.group(1).rstrip(".,")
    number = number.replace(".", "").replace(",", ".") if "," in number or re.fullmatch(r"\d{1,3}(\.\d{3})+", number) else number
    try:
        return Decimal(number) or None
    except InvalidOperation:
        return None


def _brightdata_price(item):
    """O preço de agora. Em promoção, `price` traz outro valor ("R$2624.79") e o certo vem em `price_details`
    ("R$ 1.264,79 agora"), junto com a parcela ("R$ 136/mês x 10"), que nunca é o preço.
    "R$ 1.300+" é um "a partir de" de vários vendedores: não é a oferta de uma loja."""
    for detail in item.get("price_details") or []:
        text = str(detail.get("price") or "") if isinstance(detail, dict) else ""
        if text.rstrip().endswith("agora"):
            return _reais(text)
    text = str(item.get("price") or "")
    return None if text.rstrip().endswith("+") else _reais(text)


def read_brightdata(query, token, zone):
    """SERP API da Bright Data: o preço vem como texto, só na moeda da loja, e o link nem sempre vem."""
    label = "Bright Data"
    url = "https://www.google.com/search?" + urlencode({"q": query, "tbm": "shop", "gl": "br", "hl": "pt-br", "brd_json": 1})
    try:
        response = requests.post("https://api.brightdata.com/request", timeout=SEARCH_TIMEOUT,
                                 headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"},
                                 json={"zone": zone, "url": url, "format": "raw"})
    except requests.RequestException as error:
        raise SourceError(f"{label} fora do ar.") from error
    offers = []
    for item in _json(label, response).get("shopping") or []:
        price = _brightdata_price(item)
        if price is None:
            continue
        offers.append(_offer(item.get("global_rank") or item.get("rank") or "", item.get("title"), price,
                             url=item.get("link"), seller=item.get("shop"), free_shipping=_free_shipping(item.get("shipping"))))
    return offers


def read_google_shopping(query, token, url):
    """A ferramenta própria. Só entra o que veio em reais; o link já é o da loja, quando o card traz."""
    label = "Google Shopping"
    response = _get(label, f"{url.rstrip('/')}/v1/search", params={"q": query[:SEARCH_MAX_QUERY]},
                    headers={"X-API-Token": token}, timeout=SEARCH_TIMEOUT)
    if response.status_code == 429:
        raise SourceError(f"{label}: o Google bloqueou a consulta, tente mais tarde.")
    offers = []
    for item in _json(label, response).get("products") or []:
        in_reais = item.get("currency") == "BRL" or str(item.get("price_text") or "").startswith("R$")
        if not item.get("price") or not in_reais:
            continue
        offers.append(_offer(item.get("offer_id") or item.get("product_id") or "", item.get("title"), item["price"],
                             url=item.get("url"), seller=item.get("merchant"),
                             free_shipping=_free_shipping(item.get("shipping"))))
    return offers


def _own_option(account, key):
    return PriceSourceToken.objects.filter(account_id=account.pk, source=key).values_list("option", flat=True).first() or ""


def _own_token(account, key):
    return PriceSourceToken.objects.filter(account_id=account.pk, source=key).values_list("token", flat=True).first() or ""


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    read: Callable
    setting: str = ""  # a chave global, no `.env`; a fonte com chave recebe a que vale como terceiro argumento
    metered: bool = False
    needs_gtin: bool = False  # sem código de barras não há o que consultar (nem o que gastar)
    shared: bool = False  # variações com a mesma busca aproveitam uma consulta só (a camiseta em 9 cores e tamanhos)
    turn: int = 2  # o grupo na leitura: 0 sempre entra, 1 busca (ver `tracker._read`), 2 só se faltar para o mínimo
    queries: Callable = None  # o que pesquisar, em ordem; quem tem recebe `read(query, token)`
    public: str = "google_shopping"  # como a conta vê esta fonte (ver `PUBLIC`)
    requires: str = ""  # outra configuração sem a qual a fonte não funciona (o endereço da ferramenta, a zona); vai para `read`

    def searches(self, ours):
        """O que esta fonte vai pesquisar. Vazio = não é uma busca (a pesquisa da equipe)."""
        if self.queries:
            return self.queries(ours)
        return _market_codes(ours) if self.needs_gtin else [""]

    def token(self, account):
        return _own_token(account, self.key) or getattr(settings, self.setting, "")

    def option(self, account):
        return _own_option(account, self.key) or getattr(settings, self.requires, "")

    def configured(self, account):
        return not self.setting or bool(self.token(account) and (not self.requires or self.option(account)))

    def fetch(self, variant, ours, account, query=""):
        if self.queries:
            extra = (self.option(account),) if self.requires else ()
            return self.read(query, self.token(account), *extra)
        if self.needs_gtin:  # as fontes de código leem o primeiro: uma leitura para cada código
            ours = replace(ours, gtins=(query,))
        return self.read(variant, ours, self.token(account)) if self.setting else self.read(variant, ours)


SOURCES = {s.key: s for s in (
    Source("manual", "Pesquisa da equipe", read_manual, turn=0, public="manual"),
    Source("open_prices", "Open Prices", read_open_prices, needs_gtin=True, public="collaborative"),
    Source("cosmos", "Bluesoft Cosmos", read_cosmos, "BLUESOFT_COSMOS_TOKEN", metered=True, needs_gtin=True,
           public="collaborative"),
    Source("google_shopping", "Google Shopping", read_google_shopping, "SHOPPING_SEARCH_TOKEN", metered=True, shared=True,
           turn=1, queries=_shopping_queries, requires="SHOPPING_SEARCH_URL"),
    Source("serpapi", "SerpApi", read_serpapi, "SERPAPI_KEY", metered=True, shared=True, turn=1, queries=_shopping_queries),
    Source("brightdata", "Bright Data", read_brightdata, "BRIGHTDATA_API_KEY", metered=True, shared=True, turn=1,
           queries=_shopping_queries, requires="BRIGHTDATA_ZONE"),
)}


PUBLIC = {"manual": "Pesquisa da equipe", "google_shopping": "Google Shopping", "collaborative": "Banco colaborativo"}


def label_of(key):
    return SOURCES[key].label if key in SOURCES else key


def public_key(key):
    """Como a conta vê a fonte. O que não se conhece não passa o nome adiante."""
    return SOURCES[key].public if key in SOURCES else "google_shopping"


def _public_label(label):
    source = next((s for s in SOURCES.values() if s.label == label), None)
    return PUBLIC[source.public if source else "google_shopping"]


def public_sources(text):
    """ "Bright Data, Open Prices, SerpApi" → "Google Shopping, Banco colaborativo"."""
    labels = [_public_label(part.strip()) for part in str(text or "").split(",") if part.strip()]
    return ", ".join(dict.fromkeys(labels))


def public_error(text):
    """A falha da fonte, com o nome que a conta conhece."""
    text = str(text or "")
    for source in SOURCES.values():
        text = text.replace(source.label, PUBLIC[source.public])
    return text


def public_searches(rows):
    return [{**row, "source": public_key(row.get("source"))} for row in rows or []]


def active(account):
    """A pesquisa da equipe, sempre, e as fontes que a plataforma ligou para a conta e têm chave, na ordem dela."""
    keys = ["manual", *(key for key in account.price_sources or [] if key != "manual")]
    return [SOURCES[key] for key in keys if key in SOURCES and SOURCES[key].configured(account)]


def _this_month():
    return timezone.localdate().replace(day=1)


def used_this_month(account):
    rows = PriceUsage.objects.filter(account_id=account.pk, month=_this_month())
    return rows.aggregate(total=Sum("requests"))["total"] or 0


def _take_daily(source):
    """Gasta uma consulta do teto do dia da chave global; `False` = acabou (vale para a plataforma toda)."""
    limit = settings.PRICE_DAILY_LIMITS.get(source.key)
    if not limit:
        return True
    key = f"market:budget:{source.key}:{timezone.localdate()}"
    cache.add(key, 0, 26 * 3600)
    try:
        return cache.incr(key) <= limit
    except ValueError:  # o cache apagou a chave entre as duas chamadas
        return False


def take_budget(source, account):
    """Conta uma consulta da fonte. Devolve o motivo de não poder consultar, ou "" se pode."""
    if not source.metered:
        return ""
    with transaction.atomic():
        limit = Account.objects.select_for_update().values_list("price_monthly_requests", flat=True).get(pk=account.pk)
        if limit and used_this_month(account) >= limit:
            return f"{source.label}: limite mensal de consultas da conta atingido."
        if not _own_token(account, source.key) and not _take_daily(source):
            return f"{source.label}: limite de consultas de hoje atingido."
        row, _ = PriceUsage.objects.get_or_create(account_id=account.pk, month=_this_month(), source=source.key)
        PriceUsage.objects.filter(pk=row.pk).update(requests=F("requests") + 1)
    return ""


def status(account):
    """O que o admin do Django mostra: cada fonte e se já dá para usar (nunca a chave)."""
    return [{"key": s.key, "label": s.label, "ready": s.configured(account)} for s in SOURCES.values()]
