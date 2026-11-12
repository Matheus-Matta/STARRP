"""Volume de busca pelo KeywordPlanIdeaService do Google Ads (REST). A API não exige URL: basta enviar palavras.

- Uma análise avulsa usa `fetch` (GenerateKeywordIdeas): até 20 termos, e traz ideias novas.
- A rodada usa `fetch_many` (GenerateKeywordHistoricalMetrics): junta os termos de todos os produtos, sem repetir, e pede de uma
  vez, até 10 mil por pedido. Uma operação serve o catálogo inteiro. O Google junta termos parecidos e devolve um deles, com os
  outros em `closeVariants`: o número vale para todos.

As credenciais vêm da conta (`SeoCredential`, só no admin do Django) e, sem ela, das globais do `.env`. Os números
ficam em `KeywordMetric` por 30 dias, porque o Google atualiza uma vez por mês: termo já guardado não gasta consulta.
O limite mensal da conta é `Account.seo_monthly_requests`. Para a conta, a origem é só "dados de busca do Google".
"""
import hashlib
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from starrp.models import Account, KeywordMetric, SeoCredential, SeoUsage

TIMEOUT = 30
BULK_TIMEOUT = 120
FRESH = timedelta(days=30)
GEO_BRAZIL = "2076"
LANGUAGE_PT = "1014"
MAX_SEEDS = 20  # o limite do Google por pedido
MAX_IDEAS = 200
MAX_BULK = 10_000  # o limite do Google por pedido em GenerateKeywordHistoricalMetrics
RATE_PAUSE = 1.1  # o Google aceita 1 pedido por segundo por conta nestes métodos
CACHE_CHUNK = 500  # o banco não aceita um IN com dezenas de milhares de termos
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105


class KeywordError(Exception):
    """A consulta não deu certo. A mensagem pode ir para a tela: não traz chave nem o corpo da resposta."""


def _credentials(account):
    own = SeoCredential.objects.filter(account_id=account.pk).first()
    if own:
        return {"client_id": own.client_id, "client_secret": own.client_secret, "refresh_token": own.refresh_token,
                "customer_id": own.customer_id, "login_customer_id": own.login_customer_id,
                "developer_token": own.developer_token, "own": True}
    return {"client_id": settings.GOOGLE_ADS_CLIENT_ID, "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
            "refresh_token": settings.GOOGLE_ADS_REFRESH_TOKEN, "customer_id": settings.GOOGLE_ADS_CUSTOMER_ID,
            "login_customer_id": settings.GOOGLE_ADS_LOGIN_CUSTOMER_ID, "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            "own": False}


def configured(account):
    creds = _credentials(account)
    return all(creds[key] for key in ("client_id", "client_secret", "refresh_token", "customer_id"))


def _digits(value):
    return "".join(char for char in str(value or "") if char.isdigit())


def _access_token(creds):
    key = "seo:token:" + hashlib.sha256(creds["refresh_token"].encode()).hexdigest()
    token = cache.get(key)
    if token:
        return token
    try:
        response = requests.post(TOKEN_URL, timeout=TIMEOUT, data={
            "grant_type": "refresh_token", "client_id": creds["client_id"], "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"]})
    except requests.RequestException as error:
        raise KeywordError("Dados de busca do Google fora do ar.") from error
    if response.status_code != 200:
        raise KeywordError("O Google recusou o acesso aos dados de busca. Fale com o suporte.")
    body = response.json()
    cache.set(key, body["access_token"], max(int(body.get("expires_in", 3600)) - 120, 60))
    return body["access_token"]


def _this_month():
    return timezone.localdate().replace(day=1)


def used_this_month(account):
    return SeoUsage.objects.filter(account_id=account.pk, month=_this_month()).values_list("requests", flat=True).first() or 0


def _take_budget(account):
    with transaction.atomic():
        limit = Account.objects.select_for_update().values_list("seo_monthly_requests", flat=True).get(pk=account.pk)
        if limit and used_this_month(account) >= limit:
            raise KeywordError("Limite mensal de consultas de busca da conta atingido.")
        row, _ = SeoUsage.objects.get_or_create(account_id=account.pk, month=_this_month())
        SeoUsage.objects.filter(pk=row.pk).update(requests=F("requests") + 1)


def _call(account, method, body):
    creds = _credentials(account)
    customer = _digits(creds["customer_id"])
    headers = {"Authorization": f"Bearer {_access_token(creds)}"}
    if creds["developer_token"]:
        headers["developer-token"] = creds["developer_token"]
    if creds["login_customer_id"]:
        headers["login-customer-id"] = _digits(creds["login_customer_id"])
    url = f"https://googleads.googleapis.com/{settings.GOOGLE_ADS_API_VERSION}/customers/{customer}:{method}"
    place = {"language": f"languageConstants/{LANGUAGE_PT}", "geoTargetConstants": [f"geoTargetConstants/{GEO_BRAZIL}"],
             "keywordPlanNetwork": "GOOGLE_SEARCH"}
    try:
        response = requests.post(url, timeout=BULK_TIMEOUT, headers=headers, json={**place, **body})
    except requests.RequestException as error:
        raise KeywordError("Dados de busca do Google fora do ar.") from error
    if response.status_code == 429:
        raise KeywordError("Muitas consultas de busca ao Google agora. Tente mais tarde.")
    if response.status_code in (401, 403):
        raise KeywordError("O Google recusou o acesso aos dados de busca. Fale com o suporte.")
    if response.status_code != 200:
        raise KeywordError(f"Dados de busca do Google responderam {response.status_code}.")
    try:
        return response.json().get("results") or []
    except ValueError as error:
        raise KeywordError("Dados de busca do Google responderam algo inesperado.") from error


def _ask_google(account, seeds):
    return _call(account, "generateKeywordIdeas", {"keywordSeed": {"keywords": seeds[:MAX_SEEDS]}, "includeAdultKeywords": False,
                                                   "pageSize": MAX_IDEAS})


def _save(term, volume, competition, now):
    KeywordMetric.objects.update_or_create(term=term[:200], geo=GEO_BRAZIL, language=LANGUAGE_PT, defaults={
        "avg_monthly_searches": volume, "competition": competition, "fetched_at": now})


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def cached(terms):
    since, found, terms = timezone.now() - FRESH, {}, list(terms)
    for start in range(0, len(terms), CACHE_CHUNK):
        rows = KeywordMetric.objects.filter(term__in=terms[start:start + CACHE_CHUNK], geo=GEO_BRAZIL, language=LANGUAGE_PT,
                                            fetched_at__gte=since)
        found.update({row.term: row for row in rows})
    return found


def fetch_many(account, terms):
    """Guarda o volume de todos os termos com o mínimo de operações. Devolve quantos pedidos fez."""
    wanted = list(dict.fromkeys(terms))
    known = cached(wanted)
    missing = [term for term in wanted if term not in known]
    calls = 0
    for start in range(0, len(missing), MAX_BULK):
        if calls:
            time.sleep(RATE_PAUSE)
        chunk = missing[start:start + MAX_BULK]
        _take_budget(account)
        calls += 1
        _save_bulk(chunk, _call(account, "generateKeywordHistoricalMetrics", {"keywords": chunk}))
    return calls


def _save_bulk(asked, results):
    now, values = timezone.now(), {}
    for item in results:
        metrics = item.get("keywordMetrics") or {}
        number = (_int(metrics.get("avgMonthlySearches")), str(metrics.get("competition") or "")[:12])
        for text in (item.get("text"), *(item.get("closeVariants") or [])):
            term = str(text or "").strip().lower()
            if term:
                values[term] = number
    for term in asked:  # o que o Google não devolveu também fica guardado: não pergunta de novo no mês
        values.setdefault(term, (None, ""))
    KeywordMetric.objects.bulk_create(
        [KeywordMetric(term=term[:200], geo=GEO_BRAZIL, language=LANGUAGE_PT, avg_monthly_searches=volume, competition=competition,
                       fetched_at=now, updated_at=now) for term, (volume, competition) in values.items()],
        update_conflicts=True, unique_fields=["term", "geo", "language"],
        update_fields=["avg_monthly_searches", "competition", "fetched_at", "updated_at"], batch_size=500)


def fetch(account, terms):
    """Os números de cada termo, do que está guardado ou de uma consulta. Devolve (métricas, ideias do Google)."""
    known = cached(terms)
    missing = [term for term in terms if term not in known]
    ideas = []
    if missing:
        _take_budget(account)
        now = timezone.now()
        for item in _ask_google(account, missing):
            text = str(item.get("text") or "").strip().lower()
            if not text:
                continue
            metrics = item.get("keywordIdeaMetrics") or {}
            volume, competition = _int(metrics.get("avgMonthlySearches")), str(metrics.get("competition") or "")[:12]
            _save(text, volume, competition, now)
            ideas.append(text)
        returned = set(ideas)
        for term in missing:  # o que o Google não devolveu também fica guardado: não pergunta de novo no mês
            if term not in returned:
                _save(term, None, "", now)
        known = cached(list(dict.fromkeys([*terms, *ideas])))
    return known, ideas
