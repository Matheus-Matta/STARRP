"""Analítico de SEO: nota, sugestões, aprovação, dados de busca, limites e isolamento entre contas."""
import pytest
from django.utils import timezone

from starrp.models import Brand, KeywordMetric, Product, SeoCheck, SeoCredential
from starrp.services.seo import analyzer, dictionary, keywords
from starrp.tasks import seo as tasks

CHECKS = "/api/v1/seo-checks/"


@pytest.fixture(autouse=True)
def _module(request):
    if "ctx" in request.fixturenames:
        ctx = request.getfixturevalue("ctx")
        ctx.account.extra_modules = ["seo"]
        ctx.account.save(update_fields=["extra_modules"])


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _google(monkeypatch, settings, volumes, status=200):
    settings.GOOGLE_ADS_CLIENT_ID, settings.GOOGLE_ADS_CLIENT_SECRET = "cid", "segredo-global"
    settings.GOOGLE_ADS_REFRESH_TOKEN, settings.GOOGLE_ADS_CUSTOMER_ID = "refresh-global", "123-456-7890"
    from django.core.cache import cache

    cache.clear()
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if "oauth2" in url:
            return _Response(200, {"access_token": "acesso", "expires_in": 3600})
        return _Response(status, {"results": [
            {"text": term, "keywordIdeaMetrics": {"avgMonthlySearches": str(volume), "competition": "LOW"}}
            for term, volume in volumes.items()]})

    monkeypatch.setattr(keywords.requests, "post", post)
    return calls


def _ads(calls):
    return [call for call in calls if "googleads" in call[0]]


def _product(ctx, name="Guarda-Roupa Casal 5 Portas", **fields):
    variant = ctx.product(name, price="100", sku=fields.pop("sku", "GR1"))
    product = variant.product
    for key, value in fields.items():
        setattr(product, key, value)
    product.save()
    return Product.all_objects.select_related("brand", "account").get(pk=product.pk)


# ── dicionário ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name, wanted", [
    ("Roupeiro 5P 2G", "Roupeiro 5 Portas 2 Gavetas"),
    ("GR Casal 6P", "Guarda-Roupa Casal 6 Portas"),
    ("Armário Coz 6P", "Armário de Cozinha 6 Portas"),
    ("Rack TV 1.8", "Rack para TV 1,80 m"),
    ("Mesa Jantar 6Cad", "Mesa de Jantar com 6 Cadeiras"),
    ("Mesa c/ 4 Cad", "Mesa com 4 Cadeiras"),
    ("Sofá c/ Chaise", "Sofá com Chaise"),
])
def test_dicionario_expande_as_abreviacoes(name, wanted):
    assert dictionary.expand(name)[0] == wanted


@pytest.mark.parametrize("name", ["Chocolate Lacta 90G", "Camiseta 2P", "Whey Protein 900G", "Coca-Cola 2L", "GR Vitaminas"])
def test_abreviacao_fora_do_contexto_nao_muda(name):
    assert dictionary.expand(name) == (name, [])


def test_nunca_inventa_atributo():
    assert "casal" not in dictionary.expand("Roupeiro 5P")[0].lower() and "mdf" not in dictionary.expand("Roupeiro 5P")[0].lower()


def test_sigla_ambigua_pede_confirmacao_e_nao_troca():
    assert dictionary.expand("Cama Box Cj Casal")[0] == "Cama Box Cj Casal"
    assert "confirme" in dictionary.ambiguous("Cama Box Cj Casal")[0]


def test_maiusculas_viram_titulo_mantendo_marca_e_modelo():
    assert dictionary.nice_case("GUARDA ROUPA DE CASAL TUNE 510BT", "", "Tune 510BT") == "Guarda Roupa de Casal Tune 510BT"


# ── nota e sugestões, sem API ──────────────────────────────────────────────
def test_analisa_sem_api_e_a_nota_nao_conta_a_procura(ctx):
    check = analyzer.read_product(_product(ctx, "Roupeiro 5P 2G"))
    assert check.has_search_data is False and "demand" not in {row["key"] for row in check.breakdown}
    assert check.suggested_name == "Roupeiro 5 Portas 2 Gavetas" and check.status == SeoCheck.Status.PENDING
    fields = {issue["field"] for issue in check.issues}
    assert {"name", "seo_title", "seo_description"} <= fields and all(i["origin"] == "regra" for i in check.issues)
    assert check.suggested_seo_title.startswith("Roupeiro 5 Portas") and len(check.suggested_seo_description) <= 160
    assert 0 <= check.score < 100


def test_cadastro_completo_tira_nota_maxima_e_sem_sugestao(ctx):
    brand = Brand.all_objects.create(account=ctx.account, name="Marca")
    product = _product(ctx, "Guarda-Roupa Casal 5 Portas Marca", brand=brand, slug="guarda-roupa-casal-5-portas-marca",
                       seo_title="Guarda-Roupa Casal 5 Portas Marca com Espelho",
                       seo_description="Guarda-roupa casal com 5 portas e espelho, ideal para quartos amplos, com ótimo espaço interno.")
    from starrp.models import Category, Tag

    product.category = Category.all_objects.create(account=ctx.account, name="Quarto")
    product.save()
    product.tags.add(Tag.all_objects.create(account=ctx.account, name="quarto", scope="product"))
    check = analyzer.read_product(Product.all_objects.select_related("brand", "account").get(pk=product.pk))
    assert check.score == 100 and check.issues == [] and check.status == SeoCheck.Status.NONE
    assert not check.suggested_name and not check.suggested_seo_title


def test_titulo_ganha_marca_e_modelo_sem_passar_de_70(ctx):
    brand = Brand.all_objects.create(account=ctx.account, name="Caemmun")
    check = analyzer.read_product(_product(ctx, "Guarda-Roupa Sophia", brand=brand, model_name="Lux 5P"))
    assert check.suggested_seo_title == "Guarda-Roupa Sophia Caemmun Lux 5P"
    long = analyzer.read_product(_product(ctx, "Guarda-Roupa " + "Muito Comprido " * 8, sku="GR2", brand=brand))
    assert len(long.suggested_seo_title) <= 70 and not long.suggested_seo_title.endswith(" ")


def test_codigo_interno_no_nome_e_apontado_e_nunca_vira_palavra_chave(ctx):
    check = analyzer.read_product(_product(ctx, "Cadeira ABC123 Escritório", sku="ABC123"))
    assert any("Código interno" in issue["message"] for issue in check.issues)
    assert "abc" not in dictionary.terms_of("Cadeira Escritório")[0]


def test_descricao_usa_o_texto_do_produto_sem_html(ctx):
    long_text = "<p>Cadeira ergonômica com apoio de braço e regulagem de altura, ideal para longas jornadas de trabalho no escritório.</p>"
    check = analyzer.read_product(_product(ctx, "Cadeira Ergonômica", description=long_text))
    assert check.suggested_seo_description.startswith("Cadeira ergonômica com apoio") and "<p>" not in check.suggested_seo_description


# ── dados de busca ─────────────────────────────────────────────────────────
def test_consulta_o_google_com_os_parametros_e_as_credenciais_certas(ctx, monkeypatch, settings):
    calls = _google(monkeypatch, settings, {"guarda roupa casal 5 portas": 500})
    check = analyzer.read_product(_product(ctx))
    url, kwargs = _ads(calls)[0]
    assert url == "https://googleads.googleapis.com/v26/customers/1234567890:generateKeywordIdeas"
    assert kwargs["headers"]["Authorization"] == "Bearer acesso" and "developer-token" not in kwargs["headers"]
    body = kwargs["json"]
    assert body["language"] == "languageConstants/1014" and body["geoTargetConstants"] == ["geoTargetConstants/2076"]
    assert body["keywordPlanNetwork"] == "GOOGLE_SEARCH" and len(body["keywordSeed"]["keywords"]) <= 20
    assert check.has_search_data and {row["key"] for row in check.breakdown} >= {"demand"}
    assert check.keywords[0]["term"] == "guarda roupa casal 5 portas" and check.keywords[0]["avg_monthly_searches"] == 500
    assert keywords.used_this_month(ctx.account) == 1


def test_sinonimo_so_e_trocado_com_dados_a_favor(ctx, monkeypatch, settings):
    _google(monkeypatch, settings, {"roupeiro": 1000, "guarda roupa": 40000})
    check = analyzer.read_product(_product(ctx, "Roupeiro Casal 5 Portas"))
    assert check.suggested_name.startswith("Guarda-Roupa") and any(i["origin"] == "busca" and "40.000" in i["message"] for i in check.issues)

    KeywordMetric.objects.all().delete()
    _google(monkeypatch, settings, {"roupeiro": 30000, "guarda roupa": 40000})
    check = analyzer.read_product(_product(ctx, "Roupeiro Solteiro 2 Portas", sku="GR2"))
    assert not check.suggested_name  # sinônimo correto, sem diferença clara: não perde ponto
    assert not [i for i in check.issues if i["field"] == "demand"]


def test_termos_vao_como_o_google_guarda_sem_hifen_nem_pedaco_cortado():
    """Resposta real (04/11/2026): "guarda roupa" tem 550 mil buscas, e "guarda-roupa" volta vazio."""
    assert dictionary.terms_of("Guarda-Roupa Casal 5 Portas") == ["guarda roupa casal 5 portas", "guarda roupa", "guarda roupa casal"]
    terms = dictionary.terms_of("Roupeiro Casal 5 Portas")
    assert "guarda roupa" in terms and "roupeiro" in terms and "roupeiro casal 5" not in terms
    assert not [term for term in terms if "-" in term]

def test_termo_guardado_nao_gasta_outra_consulta(ctx, monkeypatch, settings):
    calls = _google(monkeypatch, settings, {"guarda roupa casal 5 portas": 500})
    product = _product(ctx)
    analyzer.read_product(product)
    first = len(_ads(calls))
    analyzer.read_product(product)
    assert len(_ads(calls)) == first == 1 and keywords.used_this_month(ctx.account) == 1


def test_termo_antigo_consulta_de_novo(ctx, monkeypatch, settings):
    calls = _google(monkeypatch, settings, {"guarda roupa casal 5 portas": 500})
    product = _product(ctx)
    analyzer.read_product(product)
    KeywordMetric.objects.update(fetched_at=timezone.now() - keywords.FRESH * 2)
    analyzer.read_product(product)
    assert len(_ads(calls)) == 2


@pytest.mark.parametrize("status, message", [(401, "recusou"), (403, "recusou"), (429, "Muitas"), (500, "500")])
def test_falha_do_google_nao_impede_a_analise_nem_mostra_segredo(ctx, monkeypatch, settings, status, message):
    _google(monkeypatch, settings, {}, status=status)
    check = analyzer.read_product(_product(ctx, "Roupeiro 5P"))
    assert message in check.error and check.score is not None and check.has_search_data is False
    assert check.suggested_name and "segredo" not in check.error and "refresh" not in check.error


def test_limite_mensal_para_de_consultar_e_avisa(ctx, monkeypatch, settings):
    calls = _google(monkeypatch, settings, {"termo": 10})
    ctx.account.seo_monthly_requests = 1
    ctx.account.save()
    analyzer.read_product(_product(ctx, "Primeiro Produto Aqui", sku="A1"))
    check = analyzer.read_product(_product(ctx, "Outro Produto Diferente", sku="A2"))
    assert len(_ads(calls)) == 1 and "Limite mensal" in check.error and check.score is not None


def test_credencial_da_conta_ignora_a_global(ctx, monkeypatch, settings):
    calls = _google(monkeypatch, settings, {"termo": 10})
    SeoCredential.objects.create(account=ctx.account, client_id="da-conta", client_secret="s", refresh_token="r-conta",
                                 customer_id="999-999-9999", login_customer_id="111-111-1111", developer_token="dev-antigo")
    analyzer.read_product(_product(ctx))
    token = next(call for call in calls if "oauth2" in call[0])
    assert token[1]["data"]["client_id"] == "da-conta" and token[1]["data"]["refresh_token"] == "r-conta"
    url, kwargs = _ads(calls)[0]
    assert "/customers/9999999999:" in url and kwargs["headers"]["login-customer-id"] == "1111111111"
    assert kwargs["headers"]["developer-token"] == "dev-antigo"


def test_credencial_de_uma_conta_nao_vale_para_outra(ctx, other, settings):
    settings.GOOGLE_ADS_CLIENT_ID = settings.GOOGLE_ADS_CLIENT_SECRET = settings.GOOGLE_ADS_REFRESH_TOKEN = settings.GOOGLE_ADS_CUSTOMER_ID = ""
    SeoCredential.objects.create(account=ctx.account, client_id="c", client_secret="s", refresh_token="r", customer_id="1")
    assert keywords.configured(ctx.account) and not keywords.configured(other.account)


# ── API, worker e aprovação ────────────────────────────────────────────────
def _detail(api, pk):
    return api.get(f"{CHECKS}{pk}/").json()


def test_clique_cria_o_item_na_hora_e_o_trabalho_vai_para_o_worker(ctx, monkeypatch):
    sent = []
    monkeypatch.setattr(tasks.seo_read, "delay", lambda *args: sent.append(args))
    product, api = _product(ctx, "Roupeiro 5P"), ctx.client()
    pk = api.post(f"{CHECKS}product/", {"product": str(product.pk)}, format="json").json()["id"]
    item = _detail(api, pk)
    assert [args[:2] for args in sent] == [(str(ctx.account.pk), [str(product.pk)])] and item["reading"] is True and item["score"] is None
    api.post(f"{CHECKS}product/", {"product": str(product.pk)}, format="json")
    assert len(sent) == 1  # segundo clique com a análise na fila
    tasks.seo_read(*sent[0])
    done = _detail(api, pk)
    assert done["reading"] is False and done["score"] is not None and done["product_name"] == "Roupeiro 5P"
    assert SeoCheck.all_objects.filter(product=product).count() == 1


def test_aplica_so_o_que_foi_aprovado_e_registra_quem(ctx):
    product, api = _product(ctx, "Roupeiro 5P 2G"), ctx.client()
    check = analyzer.read_product(product)
    body = _detail(api, check.pk)
    fields = {row["field"] for row in body["suggestions"]}
    assert {"name", "seo_title", "seo_description"} <= fields
    row = next(row for row in body["suggestions"] if row["field"] == "name")
    assert row["current"] == "Roupeiro 5P 2G" and row["suggested"] == "Roupeiro 5 Portas 2 Gavetas"

    assert not Product.all_objects.get(pk=product.pk).seo_title  # analisar não muda o cadastro
    response = api.post(f"{CHECKS}{check.pk}/apply/", {"fields": ["name"]}, format="json")
    assert response.status_code == 200, response.json()
    product.refresh_from_db()
    assert product.name == "Roupeiro 5 Portas 2 Gavetas" and not product.seo_title and product.updated_by == ctx.admin
    after = response.json()
    assert after["status"] == "pending" and after["decided_by_name"] and {r["field"] for r in after["suggestions"]} >= {"seo_title"}


def test_apply_recusa_o_que_nao_existe(ctx):
    check, api = analyzer.read_product(_product(ctx, "Roupeiro 5P")), ctx.client()
    assert api.post(f"{CHECKS}{check.pk}/apply/", {"fields": ["price"]}, format="json").status_code == 422
    assert api.post(f"{CHECKS}{check.pk}/apply/", {"fields": []}, format="json").status_code == 422
    assert api.post(f"{CHECKS}{check.pk}/apply/", {"fields": "name"}, format="json").status_code == 400


def test_recusar_nao_muda_o_cadastro(ctx):
    product, api = _product(ctx, "Roupeiro 5P"), ctx.client()
    check = analyzer.read_product(product)
    assert api.post(f"{CHECKS}{check.pk}/reject/").json()["status"] == "rejected"
    product.refresh_from_db()
    assert product.name == "Roupeiro 5P"
    assert api.post(f"{CHECKS}{check.pk}/reject/").status_code == 409


def test_sem_o_modulo_some_e_sem_permissao_nao_altera(ctx):
    check = analyzer.read_product(_product(ctx, "Roupeiro 5P"))
    auditor = ctx.client(ctx.user("auditor-seo", "auditor"))
    assert auditor.get(CHECKS).status_code == 200
    assert auditor.post(f"{CHECKS}{check.pk}/apply/", {"fields": ["name"]}, format="json").status_code == 403
    assert auditor.post(f"{CHECKS}run/").status_code == 403
    ctx.account.extra_modules = []
    ctx.account.save()
    assert ctx.client().get(CHECKS).status_code == 403


def test_uma_conta_nao_alcanca_a_outra(ctx, other):
    other.account.extra_modules = ["seo"]
    other.account.save()
    alheio = other.product("Roupeiro 5P", price="10", sku="OUTRO").product
    check = analyzer.read_product(Product.all_objects.select_related("brand", "account").get(pk=alheio.pk))
    api = ctx.client()
    assert api.post(f"{CHECKS}product/", {"product": str(alheio.pk)}, format="json").status_code == 422
    assert api.get(f"{CHECKS}{check.pk}/").status_code == 404
    assert api.post(f"{CHECKS}{check.pk}/apply/", {"fields": ["name"]}, format="json").status_code == 404
    assert tasks.seo_read(str(ctx.account.pk), [str(alheio.pk)]) == {"checked": 0}
    assert api.get(CHECKS).json()["results"] == []


def _catalog(ctx):
    from starrp.models import Category

    moveis = Category.all_objects.create(account=ctx.account, name="Móveis")
    outra = Category.all_objects.create(account=ctx.account, name="Outra")
    a = _product(ctx, "Roupeiro 5P", sku="R1", category=moveis)
    b = _product(ctx, "Mesa Jantar 6Cad", sku="R2", category=moveis)
    c = _product(ctx, "Cadeira Simples", sku="R3", category=outra)
    return moveis, a, b, c


def test_regras_escolhem_o_que_a_analise_pega_e_sao_separadas_da_precificacao(ctx):
    moveis, a, b, c = _catalog(ctx)
    api = ctx.client()
    assert api.get(f"{CHECKS}rules/").json()["in_scope"] == 3
    saved = api.post(f"{CHECKS}rules/", {"categories": [str(moveis.pk)], "exclude_products": [str(b.pk)]}, format="json")
    assert saved.status_code == 200 and saved.json()["in_scope"] == 1
    ctx.account.refresh_from_db()
    assert ctx.account.seo_scope["categories"] == [str(moveis.pk)] and not ctx.account.price_scope
    assert [p.pk for p in analyzer.batch_next(ctx.account, timezone.now(), 10)] == [a.pk]


def test_regras_nao_aceitam_item_de_outra_conta_nem_quem_nao_gerencia(ctx, other):
    alheio = other.product("Alheio", price="10", sku="X").product
    api = ctx.client()
    assert api.post(f"{CHECKS}rules/", {"products": [str(alheio.pk)]}, format="json").status_code == 400
    assert ctx.client(ctx.user("auditor-seo2", "auditor")).get(f"{CHECKS}rules/").status_code == 403


def test_rodada_analisa_tudo_nas_regras_de_lote_em_lote_com_pausa(ctx, monkeypatch, settings):
    from starrp.tasks import batches as batch_tasks

    scheduled = []
    settings.PRICE_BATCH_SIZE, settings.PRICE_BATCH_PAUSE = 2, 45
    monkeypatch.setattr(batch_tasks.batch_step, "apply_async", lambda args, countdown: scheduled.append((args, countdown)))
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: scheduled.append((args, 0)))
    _catalog(ctx)
    api = ctx.client()
    body = api.post(f"{CHECKS}run/").json()
    assert body["checked"] == 3 and body["running"] is True and not SeoCheck.all_objects.exists()
    task_id = scheduled[0][0][0]
    batch_tasks.batch_step(task_id)
    assert SeoCheck.all_objects.count() == 2 and scheduled[-1][1] == 45
    state = api.get(f"{CHECKS}run-status/").json()
    assert (state["running"], state["done"], state["total"]) == (True, 2, 3)
    batch_tasks.batch_step(task_id)
    assert SeoCheck.all_objects.filter(reading_since__isnull=True, score__isnull=False).count() == 3
    assert api.get(f"{CHECKS}run-status/").json()["running"] is False
    assert len(scheduled) == 2  # terminou: não agenda outro lote


def test_rodada_sem_nada_nas_regras_avisa(ctx):
    moveis = _catalog(ctx)[0]
    moveis_vazia = {"min_price": "99999"}
    api = ctx.client()
    api.post(f"{CHECKS}rules/", moveis_vazia, format="json")
    response = api.post(f"{CHECKS}run/")
    assert moveis and response.status_code == 422 and "regras" in str(response.json())


def test_rodada_de_uma_conta_nao_toca_na_outra(ctx, other, monkeypatch):
    from starrp.tasks import batches as batch_tasks

    sent = []
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: sent.append(args))
    other.account.extra_modules = ["seo"]
    other.account.save()
    alheio = other.product("Produto de Outra Conta", price="10", sku="OUTRA").product
    _product(ctx, "Produto Desta Conta", sku="DESTA")
    ctx.client().post(f"{CHECKS}run/")
    assert batch_tasks.batches.step(*sent[0]) is False and not SeoCheck.all_objects.filter(product=alheio).exists()
    assert SeoCheck.all_objects.filter(account=ctx.account).count() == 1


def _bulk_google(monkeypatch, settings, volumes, status=200, variants=None):
    settings.GOOGLE_ADS_CLIENT_ID, settings.GOOGLE_ADS_CLIENT_SECRET = "cid", "s"
    settings.GOOGLE_ADS_REFRESH_TOKEN, settings.GOOGLE_ADS_CUSTOMER_ID = "r", "1234567890"
    from django.core.cache import cache

    cache.clear()
    calls = []

    def post(url, **kwargs):
        if "oauth2" in url:
            return _Response(200, {"access_token": "a", "expires_in": 3600})
        calls.append((url, kwargs["json"]))
        results = [{"text": term, "keywordMetrics": {"avgMonthlySearches": str(volume), "competition": "HIGH"},
                    "closeVariants": (variants or {}).get(term, [])} for term, volume in volumes.items()]
        return _Response(status, {"results": results})

    monkeypatch.setattr(keywords.requests, "post", post)
    return calls


def _round(ctx, monkeypatch, settings):
    """Roda a rodada inteira do Analítico, lote a lote, e devolve a tarefa."""
    from starrp.models import BackgroundTask
    from starrp.tasks import batches as batch_tasks

    settings.PRICE_BATCH_SIZE = 2
    sent = []
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: sent.append(args))
    monkeypatch.setattr(batch_tasks.batch_step, "apply_async", lambda args, countdown: sent.append(args))
    response = ctx.client().post(f"{CHECKS}run/")
    assert response.status_code == 200, response.json()
    task_id = response.json()["task"]
    for _ in range(10):
        batch_tasks.batch_step(task_id)
    return BackgroundTask.all_objects.get(pk=task_id)


def test_rodada_pede_os_termos_de_todos_os_produtos_em_uma_operacao(ctx, monkeypatch, settings):
    calls = _bulk_google(monkeypatch, settings, {"guarda roupa": 550000, "guarda roupa casal": 450000})
    for index, name in enumerate(("Guarda-Roupa Casal 5 Portas", "Guarda-Roupa Casal 6 Portas", "Guarda-Roupa Solteiro 2 Portas",
                                  "Guarda-Roupa Casal 3 Portas", "Guarda-Roupa Infantil")):
        _product(ctx, name, sku=f"B{index}")
    task = _round(ctx, monkeypatch, settings)
    assert task.status == "completed" and task.done == 5 and not task.error
    assert len(calls) == 1 and keywords.used_this_month(ctx.account) == 1  # 5 produtos, uma operação
    url, body = calls[0]
    assert url.endswith("/customers/1234567890:generateKeywordHistoricalMetrics")
    assert body["language"] == "languageConstants/1014" and body["geoTargetConstants"] == ["geoTargetConstants/2076"]
    sent = body["keywords"]
    assert len(sent) == len(set(sent)) and sent.count("guarda roupa") == 1  # o termo de vários produtos vai uma vez
    checks = SeoCheck.all_objects.filter(account=ctx.account)
    assert checks.count() == 5 and all(check.has_search_data for check in checks)
    assert any(row["term"] == "guarda roupa" and row["avg_monthly_searches"] == 550000 for row in checks.first().keywords)


def test_segunda_rodada_usa_o_que_esta_guardado_e_nao_gasta_nada(ctx, monkeypatch, settings):
    calls = _bulk_google(monkeypatch, settings, {"guarda roupa": 550000})
    _product(ctx, "Guarda-Roupa Casal 5 Portas", sku="B1")
    _round(ctx, monkeypatch, settings)
    _round(ctx, monkeypatch, settings)
    assert len(calls) == 1 and keywords.used_this_month(ctx.account) == 1


def test_variante_que_o_google_juntou_tambem_recebe_o_numero(ctx, monkeypatch, settings):
    _bulk_google(monkeypatch, settings, {"guarda roupas": 550000}, variants={"guarda roupas": ["guarda roupa"]})
    keywords.fetch_many(ctx.account, ["guarda roupa", "guarda roupas", "termo sem resultado"])
    saved = keywords.cached(["guarda roupa", "guarda roupas", "termo sem resultado"])
    assert saved["guarda roupa"].avg_monthly_searches == 550000 and saved["guarda roupas"].avg_monthly_searches == 550000
    assert saved["termo sem resultado"].avg_monthly_searches is None


def test_acima_de_10_mil_termos_divide_e_respeita_o_limite_de_velocidade(ctx, monkeypatch, settings):
    calls = _bulk_google(monkeypatch, settings, {})
    naps = []
    monkeypatch.setattr(keywords, "MAX_BULK", 2)
    monkeypatch.setattr(keywords.time, "sleep", naps.append)
    assert keywords.fetch_many(ctx.account, ["um termo", "dois termos", "tres termos", "um termo"]) == 2
    assert [len(body["keywords"]) for _, body in calls] == [2, 1] and naps == [keywords.RATE_PAUSE]
    assert keywords.used_this_month(ctx.account) == 2


def test_falha_na_consulta_em_lote_avisa_na_tarefa_e_analisa_com_as_regras(ctx, monkeypatch, settings):
    _bulk_google(monkeypatch, settings, {}, status=403)
    _product(ctx, "Roupeiro 5P", sku="B1")
    task = _round(ctx, monkeypatch, settings)
    assert task.status == "completed" and "recusou" in task.error and task.done == 1
    check = SeoCheck.all_objects.get(account=ctx.account)
    assert check.has_search_data is False and check.score is not None and check.suggested_name


def test_limite_mensal_zerado_nao_consulta_e_a_rodada_segue(ctx, monkeypatch, settings):
    calls = _bulk_google(monkeypatch, settings, {"termo": 1})
    ctx.account.seo_monthly_requests = 1
    ctx.account.save()
    keywords.SeoUsage.objects.create(account=ctx.account, month=timezone.localdate().replace(day=1), requests=1)
    _product(ctx, "Roupeiro 5P", sku="B1")
    task = _round(ctx, monkeypatch, settings)
    assert not calls and "Limite mensal" in task.error and task.status == "completed"


def test_nome_longo_demais_nao_derruba_o_pedido_inteiro():
    long = "Guarda Roupa Casal Com Espelho Seis Portas Duas Gavetas Madeira Maciça Cor Branca Muito Bonito"
    terms = dictionary.terms_of(long)
    assert terms and all(len(term) <= 80 and len(term.split()) <= 10 for term in terms) and "guarda roupa" in terms


def test_falha_no_worker_nao_deixa_o_item_analisando(ctx, monkeypatch):
    sent = []
    monkeypatch.setattr(tasks.seo_read, "delay", lambda *args: sent.append(args))
    product = _product(ctx)
    ctx.client().post(f"{CHECKS}product/", {"product": str(product.pk)}, format="json")

    def boom(_):
        raise RuntimeError("segredo")

    monkeypatch.setattr(analyzer, "read_product", boom)
    tasks.seo_read(*sent[0])
    check = SeoCheck.all_objects.get(product=product)
    assert check.reading_since is None and "falhou" in check.error and "segredo" not in check.error


def test_a_conta_nunca_ve_a_credencial_nem_o_nome_da_api(ctx, monkeypatch, settings):
    _google(monkeypatch, settings, {"termo": 10})
    SeoCredential.objects.create(account=ctx.account, client_id="id-secreto", client_secret="s-secreto", refresh_token="r-secreto",
                                 customer_id="5550001111")
    check = analyzer.read_product(_product(ctx))
    api = ctx.client()
    for url in (f"{CHECKS}{check.pk}/", CHECKS, f"{CHECKS}{check.pk}/history/", "/api/v1/account/settings/"):
        text = api.get(url).content.decode()
        assert "secreto" not in text and "5550001111" not in text and "seo_monthly_requests" not in text, url


def test_admin_guarda_a_credencial_mascarada_e_em_branco_mantem(ctx, client, django_user_model):
    from starrp.tests.test_market import _admin_post_data

    root = django_user_model.objects.create_superuser("root-seo", "root-seo@x.com", "x")
    client.force_login(root)
    SeoCredential.objects.create(account=ctx.account, client_id="id", client_secret="segredo-atual", refresh_token="refresh-atual",
                                 customer_id="1234567890")
    url = f"/admin/starrp/account/{ctx.account.pk}/change/"
    page = client.get(url)
    html = page.content.decode()
    assert "segredo-atual" not in html and "refresh-atual" not in html and "Consultas de busca neste mês" in html
    data = _admin_post_data(page)
    assert client.post(url, data).status_code == 302
    saved = SeoCredential.objects.get(account=ctx.account)
    assert saved.client_secret == "segredo-atual" and saved.refresh_token == "refresh-atual"
