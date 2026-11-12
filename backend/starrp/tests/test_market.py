"""Precificação: pareamento, decisão pelo custo, o processo (aprovar/recusar) e a configuração."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from starrp.core.errors import BusinessError
from starrp.models import CompetitorPrice, MarketOffer, PriceCheck, PriceSourceToken, Product, ProductVariant
from starrp.services.market import competitors, matching, pricing, sources, tracker

RULES = pricing.Rules(min_margin=Decimal("20"), band=Decimal("10"), min_competitors=3, match_min=Decimal("85"))
D = Decimal


@pytest.fixture(autouse=True)
def _pricing_module(request):
    if "ctx" in request.fixturenames:
        ctx = request.getfixturevalue("ctx")
        ctx.account.extra_modules = ["pricing", "cosmos"]
        ctx.account.save(update_fields=["extra_modules"])


def _offer(i, price, title="Fone Bluetooth JBL Tune 510BT Preto", gtin="7891234567895", brand="JBL"):
    return {"external_id": f"MLB{i}", "title": title, "url": f"https://ml/{i}", "seller": f"loja{i}",
            "price": price, "free_shipping": True, "brand": brand, "model": "Tune 510BT",
            "gtins": [gtin] if gtin else []}


def _market(*prices, key="fake", metered=False, **kwargs):
    read = lambda variant, ours: [_offer(f"{key}{i}", p, **kwargs) for i, p in enumerate(prices)]  # noqa: E731
    return [sources.Source(key, key.title(), read, metered=metered)]


def _variant(ctx, price="150.00", cost="60.00"):
    variant = ctx.product("Fone Bluetooth JBL Tune 510BT Preto", price=price, barcode="7891234567895", sku="FONE1")
    variant.average_cost = D(cost)
    variant.save()
    return variant


# ── pareamento ─────────────────────────────────────────────────────────────
def test_gtin_igual_e_o_mesmo_produto():
    ours = matching.Ours("Fone JBL Tune 510BT", "JBL", ("07891234567895",))
    assert matching.score(ours, "Headphone qualquer", gtins=["7891234567895"]).score == 100


def test_medida_ou_kit_diferente_nunca_conta_mesmo_com_gtin():
    ours = matching.Ours("Shampoo Seda Ceramidas 325 ml", "Seda", ("7891150000001",))
    assert matching.score(ours, "Shampoo Seda Ceramidas 650 ml", gtins=["7891150000001"]).score == 0
    assert matching.score(ours, "Kit 3 Shampoo Seda Ceramidas 325 ml", gtins=["7891150000001"]).score == 0


def test_titulo_vira_partes_palavra_a_cada_dois_e_tres_espacos_e_inteiro():
    assert matching.title_items("GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUM") == [
        "guarda", "roupa", "sophia", "5", "portas", "caemmum", "guarda roupa sophia", "5 portas caemmum",
        "guarda roupa sophia 5", "portas caemmum", "guarda roupa sophia 5 portas caemmum"]
    assert matching.title_items("Coca-Cola 2L") == ["coca", "cola", "2000ml", "coca cola 2000ml"]  # sem repetir


def test_nota_pesa_as_palavras_e_da_bonus_aos_trechos_em_sequencia():
    ours = matching.Ours("GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUN")
    assert matching.score(ours, "Guarda-Roupa Sophia 5 Portas Caemmun Branco").score == 100
    assert matching.score(ours, "Guarda Roupa Casal Sophia 5 Portas Caemmun").score == 91  # 85 + 2 de 5 trechos
    assert matching.score(ours, "Caemmun Portas 5 Sophia Roupa Guarda").score == 85  # todas as palavras, sem nenhum trecho
    assert matching.score(ours, "Mesa de Jantar 5 Lugares").score < 20


def test_mesmo_produto_com_erro_de_digitacao_na_marca_passa_de_80():
    ours = matching.Ours("GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUM")
    found = matching.score(ours, "Guarda-Roupa Casal Sophia 5 Portas 2 Gavetas com Espelho Freijó/Off White - Caemmun")
    assert found.score >= 80 and "Escrita parecida: caemmum" in found.reason


def test_erro_de_digitacao_nao_vale_para_numero_modelo_nem_outro_produto():
    ours = matching.Ours("GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUM")
    for other in ("Guarda Roupa Sophia 6 Portas Caemmum", "Guarda Roupa Sophia 3 Portas Caemmum", "Guarda Roupa Marta 5 Portas Caemmum"):
        assert matching.score(ours, other).score < 80, other
    phone = matching.Ours("Smartphone Samsung Galaxy A54 128GB")
    assert matching.score(phone, "Smartphone Samsung Galaxy A34 128GB").score < 80
    assert not matching._same_word("sophia", "sofia") and not matching._same_word("bolsa", "bolso")
    assert matching._same_word("portas", "porta") and matching._same_word("caemmum", "caemmun")


def test_trava_de_acessorio_combo_e_retornavel():
    ours = matching.Ours("Coca-Cola 2L")
    for other in ("Coca-Cola 2L Garrafa Vazia", "Refrigerante Coca-Cola + Sprite 2l", "Refrigerante Coca Cola Retornável 2l"):
        assert matching.score(ours, other).score == 0, other
    assert matching.score(matching.Ours("Galaxy A54"), "Capa Para Galaxy A54").score == 0
    assert matching.score(matching.Ours("Capa Galaxy A54"), "Capa Para Galaxy A54").score == 85  # se o nosso é a capa, vale


def test_contem_e_palavra_inteira():
    ours = matching.Ours("Sofa 5 Lugares")
    missing = matching.score(ours, "Sofa 150 Lugares").reason
    assert "Faltou: 5" in missing


def test_marca_e_modelo_entram_no_titulo_so_se_faltarem():
    assert matching.full_title("GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUM", "Caemmum", "") == "GUARDA ROUPA SOPHIA 5 PORTAS CAEMMUM"
    assert matching.full_title("Fone Bluetooth", "JBL", "Tune 510BT") == "Fone Bluetooth JBL Tune 510BT"
    assert matching.full_title("Fone JBL Tune 510BT", "jbl", "TUNE 510BT") == "Fone JBL Tune 510BT"
    assert matching.full_title("Coca-Cola 2L", "Coca Cola", "") == "Coca-Cola 2L"


def test_busca_por_ean_tem_outro_criterio():
    ours = matching.Ours("Smartphone Samsung Galaxy A54 128GB Preto", "Samsung")
    same = matching.score_by_code(ours, "Samsung Galaxy A54 128 GB Preto Novo Lacrado", brand="Samsung")
    other = matching.score_by_code(ours, "Samsung Galaxy A34 128GB Preto", brand="Samsung")
    assert same.score >= 85 > other.score
    assert "Título" in same.reason
    assert matching.score_by_code(ours, "Capa Para Samsung Galaxy A54", brand="Samsung").score < 85  # acessório
    assert matching.score_by_code(ours, "Samsung Galaxy A54 256GB Preto", brand="Samsung").score == 0


def test_busca_por_ean_sem_codigo_de_modelo_o_titulo_decide():
    ours = matching.Ours("Shampoo Seda Ceramidas 325ml", "Seda")
    assert matching.score_by_code(ours, "Seda Shampoo Ceramidas 325 ml Unilever", brand="Seda").score >= 85
    assert matching.score_by_code(ours, "Condicionador Seda Ceramidas 325ml", brand="Seda").score < 85


# ── decisão pelo custo ─────────────────────────────────────────────────────
def test_acima_do_mercado_sugere_a_mediana_quando_a_margem_aguenta():
    out = pricing.decide("150", "60", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["position"] == "above" and out["suggested_price"] == D("121.00")
    assert out["worth_it"] is True and out["suggested_margin"] > 20
    assert "acima da mediana" in out["reason"]


def test_media_maior_preco_e_nosso_lugar_no_mercado():
    out = pricing.decide("1300", "0", [(p, 100) for p in (1000, 1200, 1400, 1800)], RULES)
    assert out["market_min"] == D("1000") and out["market_max"] == D("1800") and out["market_avg"] == D("1350.00")
    assert out["market_rank"] == 3 and out["competitors"] == 4  # dois mais baratos: somos o 3º
    far = pricing.decide("1300", "0", [(p, 100) for p in (1000, 1200, 1400, 3000)], RULES)
    assert far["market_max"] == D("1400") and far["competitors"] == 3  # o preço fora da curva não entra na régua
    assert pricing.decide("900", "0", [(p, 100) for p in (1000, 1200)], RULES)["market_rank"] == 1
    assert pricing.decide("1000", "0", [(p, 100) for p in (1000, 1200)], RULES)["market_rank"] == 1  # empate não nos põe atrás
    assert pricing.decide("5000", "0", [(p, 100) for p in (1000, 1200)], RULES)["market_rank"] == 3
    empty = pricing.decide("100", "0", [], RULES)
    assert empty["market_rank"] is None and empty["market_max"] is None and empty["market_avg"] is None


def test_lugar_no_mercado_chega_na_tela(ctx):
    variant = _variant(ctx, price="115.00")
    tracker.check_variant(variant, RULES, _market(100, 110, 120, 130))
    row = ctx.client().get("/api/v1/price-checks/").json()["results"][0]
    assert row["standing"] == "3º de 5" and row["market_max"] == "130.00" and row["market_avg"] == "115.00"


def test_abaixo_do_mercado_avisa_que_e_otimo_preco():
    out = pricing.decide("100", "20", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["position"] == "below" and out["reason"].startswith("Ótimo preço:")
    cheap = pricing.decide("100", "20", [(p, 100) for p in (90, 118, 120, 122)], RULES)
    assert cheap["position"] == "below" and cheap["reason"].startswith("Ótimo preço:")


def test_acima_do_mercado_mas_o_custo_nao_deixa_baixar():
    out = pricing.decide("150", "125", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["suggested_price"] is None and out["worth_it"] is False
    assert out["floor_price"] == D("156.25") and "não vale a pena" in out["reason"]


def test_custo_alto_baixa_so_ate_o_piso():
    out = pricing.decide("150", "100", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["suggested_price"] == D("125.00") and out["suggested_margin"] == D("20.00")


def test_abaixo_do_mercado_sugere_subir_ate_o_p25():
    out = pricing.decide("90", "50", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["position"] == "below" and out["suggested_price"] == D("119.50") and out["worth_it"] is True


def test_no_mercado_com_margem_baixa_sobe_ate_o_piso():
    out = pricing.decide("120", "100", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["position"] == "inside" and out["suggested_price"] == D("122.75")


def test_poucos_concorrentes_ou_pareamento_fraco_so_informa():
    out = pricing.decide("150", "60", [(120, 100), (121, 100), (119, 70)], RULES)
    assert out["competitors"] == 2 and out["suggested_price"] is None and out["position"] == "unknown"


def test_preco_fora_da_curva_sai_da_referencia():
    kept, stats = pricing.reference([(p, 100) for p in (118, 120, 121, 122, 15)], RULES)
    assert D(15) not in kept and stats["median"] == D("120.50")


def test_sem_custo_sugere_mas_nao_decide_se_vale():
    out = pricing.decide("150", "0", [(p, 100) for p in (118, 120, 122, 125)], RULES)
    assert out["suggested_price"] == D("121.00") and out["worth_it"] is None
    assert "Sem custo" in out["reason"]


# ── o processo ─────────────────────────────────────────────────────────────
def test_leitura_cria_o_processo_aguardando_aprovacao_com_as_ofertas(ctx):
    variant = _variant(ctx)
    check = tracker.check_variant(variant, RULES, _market(118, 120, 122, 125, 15))
    assert check.status == PriceCheck.Status.PENDING and check.suggested_price == D("121.00")
    variant.refresh_from_db()
    assert variant.price == D("150.00")  # nada muda sem aprovação
    offers = MarketOffer.all_objects.filter(price_check=check)
    assert offers.count() == 5 and offers.filter(used=True).count() == 4


def test_aprovar_aplica_o_preco_e_guarda_o_anterior(ctx):
    variant = _variant(ctx)
    check = tracker.check_variant(variant, RULES, _market(118, 120, 122, 125))
    response = ctx.client().post(f"/api/v1/price-checks/{check.pk}/approve/", {}, format="json")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "applied" and body["previous_price"] == "150.00" and body["applied_price"] == "121.00"
    variant.refresh_from_db()
    assert variant.price == D("121.00")
    assert variant.history.first().price == D("121.00")
    again = ctx.client().post(f"/api/v1/price-checks/{check.pk}/approve/", {}, format="json")
    assert again.status_code == 422


def test_aprovar_com_outro_preco(ctx):
    variant = _variant(ctx)
    check = tracker.check_variant(variant, RULES, _market(118, 120, 122, 125))
    ctx.client().post(f"/api/v1/price-checks/{check.pk}/approve/", {"price": "124.90"}, format="json")
    variant.refresh_from_db()
    assert variant.price == D("124.90")


def test_recusada_nao_volta_na_semana_se_o_mercado_nao_mexer(ctx):
    variant = _variant(ctx)
    check = tracker.check_variant(variant, RULES, _market(118, 120, 122, 125))
    assert ctx.client().post(f"/api/v1/price-checks/{check.pk}/reject/").status_code == 200
    check = tracker.check_variant(variant, RULES, _market(118, 120, 122, 126))
    assert check.status == PriceCheck.Status.REJECTED
    check = tracker.check_variant(variant, RULES, _market(98, 100, 101, 103))  # mercado caiu: pede de novo
    assert check.status == PriceCheck.Status.PENDING and check.decided_at is None
    with freeze_time(check.updated_at + timedelta(days=1)):
        ctx.client().post(f"/api/v1/price-checks/{check.pk}/reject/")
    with freeze_time(check.updated_at + timedelta(days=9)):
        assert tracker.check_variant(variant, RULES, _market(98, 100, 101, 103)).status == PriceCheck.Status.PENDING


def test_fonte_fora_do_ar_registra_o_erro_sem_perder_a_sugestao(ctx):
    variant = _variant(ctx)
    tracker.check_variant(variant, RULES, _market(118, 120, 122, 125))

    def down(variant, ours):
        raise sources.SourceError("Fonte fora do ar.")

    check = tracker.check_variant(variant, RULES, [sources.Source("fake", "Fake", down)])
    assert check.error == "Fonte fora do ar." and check.status == PriceCheck.Status.PENDING
    assert check.competitors == 4 and MarketOffer.all_objects.filter(price_check=check).count() == 4  # guardadas


def test_quem_so_ve_o_catalogo_nao_decide(ctx):
    variant = _variant(ctx)
    check = tracker.check_variant(variant, RULES, _market(118, 120, 122, 125))
    seller = ctx.user("vendedor_preco", "seller")
    client = ctx.client(seller)
    assert client.post(f"/api/v1/price-checks/{check.pk}/approve/").status_code == 403


def test_outra_conta_nao_ve_o_processo(ctx, other):
    check = tracker.check_variant(_variant(ctx), RULES, _market(118, 120, 122, 125))
    other.account.extra_modules = ["pricing"]
    other.account.save(update_fields=["extra_modules"])
    assert other.client().get("/api/v1/price-checks/").json()["count"] == 0
    assert other.client().get(f"/api/v1/price-checks/{check.pk}/").status_code == 404
    assert ctx.client().get("/api/v1/price-checks/", {"status": "pending"}).json()["count"] == 1
    offers = ctx.client().get("/api/v1/market-offers/", {"price_check": str(check.pk)}).json()
    assert offers["count"] == 4


def test_varredura_pega_a_vez_e_pula_servico_e_kit(ctx):
    ctx.account.price_tracking_enabled = True
    ctx.account.save()
    first = _variant(ctx)
    ctx.product("Instalação", price="80", sku="SERV1", type=Product.Type.SERVICE)
    assert _read_due(ctx) == 1
    assert _read_due(ctx) == 0  # já lido, ainda não é a vez
    with freeze_time(PriceCheck.all_objects.get(variant=first).checked_at + timedelta(hours=25)):
        assert _read_due(ctx) == 1
    assert not PriceCheck.all_objects.filter(variant__product__type=Product.Type.SERVICE).exists()
    assert ProductVariant.all_objects.filter(product__type=Product.Type.SERVICE).exists()


def _read_due(ctx):
    rows = tracker.due(ctx.account, 200)
    for variant in rows:
        tracker.check_variant(variant, RULES, _market(118, 120, 122, 125))
    return len(rows)


def test_rodada_vai_de_lote_em_lote_e_cria_os_itens_aos_poucos(ctx, monkeypatch, settings):
    from starrp.services import batches
    from starrp.tasks import batches as batch_tasks

    calls, scheduled = [], []
    _google(calls, monkeypatch, settings)
    settings.PRICE_BATCH_SIZE, settings.PRICE_BATCH_PAUSE = 2, 45
    monkeypatch.setattr(batch_tasks.batch_step, "apply_async", lambda args, countdown: scheduled.append((args, countdown)))
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: scheduled.append((args, 0)))
    variants = [ctx.product(f"Produto {i} Teste", price="10", sku=f"LOTE{i}") for i in range(5)]
    ctx.account.price_tracking_enabled, ctx.account.price_sources = True, ["serpapi"]
    ctx.account.save()
    api = ctx.client()
    ids = [v.pk for v in variants]

    body = api.post("/api/v1/price-checks/run/").json()
    assert body["checked"] == 5 and body["running"] is True and not calls  # o clique não lê nada
    assert not PriceCheck.all_objects.filter(variant__in=ids).exists()  # e os itens nascem a cada lote
    assert api.post("/api/v1/price-checks/run/").json()["total"] == 5 and len(scheduled) == 1  # uma rodada por vez

    task_id = scheduled[0][0][0]
    for done, count in ((2, 2), (4, 4)):
        batch_tasks.batch_step(task_id)
        assert PriceCheck.all_objects.filter(variant__in=ids).count() == count
        state = api.get("/api/v1/price-checks/run-status/").json()
        assert (state["running"], state["done"], state["total"], state["task"]) == (True, done, 5, task_id)
        assert scheduled[-1][1] == 45  # a pausa entre os lotes
    batch_tasks.batch_step(task_id)
    assert PriceCheck.all_objects.filter(variant__in=ids, reading_since__isnull=True).count() == 5
    assert api.get("/api/v1/price-checks/run-status/").json()["running"] is False
    assert batches.status("price_round", ctx.account)["running"] is False


def test_rodada_nao_passa_do_limite_mensal(ctx, monkeypatch, settings):
    from starrp.tasks import batches as batch_tasks

    _google([], monkeypatch, settings)
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: None)
    for i in range(5):
        ctx.product(f"Produto {i} Teste", price="10", sku=f"LIM{i}")
    ctx.account.price_tracking_enabled, ctx.account.price_sources, ctx.account.price_monthly_requests = True, ["serpapi"], 3
    ctx.account.save()
    assert ctx.client().post("/api/v1/price-checks/run/").json()["total"] == 3


def test_erro_no_lote_encerra_a_rodada_e_nao_prende_a_conta(ctx, monkeypatch, settings):
    from starrp.services import batches
    from starrp.tasks import batches as batch_tasks

    _google([], monkeypatch, settings)
    sent = []
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: sent.append(args))
    ctx.product("Produto Teste", price="10", sku="ERRO1")
    ctx.account.price_tracking_enabled, ctx.account.price_sources = True, ["serpapi"]
    ctx.account.save()
    ctx.client().post("/api/v1/price-checks/run/")

    def boom(*args):
        raise RuntimeError("falha")

    monkeypatch.setattr(tracker, "batch_process", boom)
    assert batches.step(*sent[0]) is False
    assert batches.status("price_round", ctx.account)["running"] is False


def test_ler_agora_explica_o_que_falta(ctx):
    response = ctx.client().post("/api/v1/price-checks/run/")
    assert response.status_code == 422 and "Configurações da conta" in str(response.json())
    assert tracker.run() == 0


# ── configuração (Configurações da conta → Cosmos) ─────────────────────────
def test_secao_cosmos_nas_configuracoes(ctx, settings):
    settings.SERPAPI_KEY = settings.BLUESOFT_COSMOS_TOKEN = ""
    api = ctx.client()
    body = api.get("/api/v1/account/settings/").json()["cosmos"]
    assert body["price_tracking_enabled"] is False and body["price_min_margin"] == "20.00"
    assert body["price_tracking_hours"] == "24"  # texto, como as opções do campo na tela
    saved = api.patch("/api/v1/account/settings/", {"cosmos": {
        "price_tracking_enabled": True,
        "price_tracking_hours": "12", "price_min_margin": "25",
        "price_min_competitors": 4, "cosmos_daily_digest": False}}, format="json")
    assert saved.status_code == 200, saved.json()
    ctx.account.refresh_from_db()
    assert ctx.account.price_tracking_enabled and ctx.account.price_tracking_hours == 12
    assert ctx.account.price_min_margin == D("25") and not ctx.account.cosmos_daily_digest
    bad = api.patch("/api/v1/account/settings/", {"cosmos": {"price_tracking_hours": 1}}, format="json")
    assert bad.status_code == 400


@pytest.mark.parametrize("hours", [6, 168])
def test_frequencias_aceitas(ctx, hours):
    assert ctx.client().patch("/api/v1/account/settings/", {"cosmos": {"price_tracking_hours": hours}},
                              format="json").status_code == 200


# ── várias fontes juntas ───────────────────────────────────────────────────
def test_ofertas_de_varias_fontes_entram_na_mesma_mediana(ctx):
    variant = _variant(ctx)
    check = tracker.check_variant(variant, RULES, _market(118, 120, key="um") + _market(122, 125, key="dois"))
    assert check.competitors == 4 and check.market_median == D("121.00")
    assert check.source == "dois, um"
    assert set(MarketOffer.all_objects.filter(price_check=check).values_list("source", flat=True)) == {"um", "dois"}


def test_fonte_fora_do_ar_nao_derruba_as_outras(ctx):
    def down(variant, ours):
        raise sources.SourceError("Google Shopping fora do ar.")

    check = tracker.check_variant(_variant(ctx), RULES, [sources.Source("g", "G", down)]
                                  + _market(118, 120, 122, 125))
    assert check.competitors == 4 and "Google Shopping" in check.error


@override_settings(PRICE_DAILY_LIMITS={"limitada": 1})
def test_teto_do_dia_usa_as_ofertas_guardadas_sem_consultar(ctx):
    from django.core.cache import cache

    cache.clear()
    variant = _variant(ctx)
    first = tracker.check_variant(variant, RULES, _market(118, 120, 122, 125, key="limitada", metered=True))
    calls = []

    def read(variant, ours):
        calls.append(1)
        return []

    source = [sources.Source("limitada", "Limitada", read, metered=True)]
    again = tracker.check_variant(variant, RULES, source)
    assert not calls and again.pk == first.pk and again.competitors == 4
    with freeze_time(timezone.now() + timedelta(days=15)):  # guardada há tempo demais não vale mais
        cache.set(f"market:budget:limitada:{timezone.localdate()}", 1)
        assert tracker.check_variant(variant, RULES, source).competitors == 0


# ── pesquisa da equipe ─────────────────────────────────────────────────────
def _on(ctx, min_competitors=2):
    ctx.account.price_tracking_enabled, ctx.account.price_sources = True, ["manual"]
    ctx.account.price_min_competitors = min_competitors
    ctx.account.save()


def test_preco_informado_na_tela_recalcula_na_hora(ctx):
    variant = _variant(ctx)
    _on(ctx)
    api = ctx.client()
    for name, price in (("Loja A", "100.00"), ("Loja B", "110.00")):
        created = api.post("/api/v1/competitor-prices/", {"variant": str(variant.pk), "competitor": name, "price": price},
                           format="json")
        assert created.status_code == 201, created.json()
    check = PriceCheck.all_objects.get(variant=variant)
    assert check.market_median == D("105.00") and check.suggested_price == D("105.00")
    assert MarketOffer.all_objects.get(price_check=check, seller="Loja A").match_score == 100
    api.delete(f"/api/v1/competitor-prices/{created.json()['id']}/")
    check.refresh_from_db()
    assert check.competitors == 1 and check.suggested_price is None


def test_vale_o_preco_mais_novo_de_cada_concorrente_e_o_velho_expira(ctx):
    variant = _variant(ctx)
    _on(ctx, 1)
    today = timezone.localdate()
    for days, price in ((1, "100"), (5, "90"), (61, "50")):
        CompetitorPrice.all_objects.create(account=ctx.account, variant=variant, competitor="Loja A", price=D(price),
                                           observed_on=today - timedelta(days=days))
    CompetitorPrice.all_objects.create(account=ctx.account, variant=variant, competitor="loja a ", price=D("95"),
                                       observed_on=today - timedelta(days=3))
    check = tracker.check_variant(variant)
    assert check.competitors == 1 and check.market_median == D("100.00")


def test_preco_nao_aceita_produto_de_outra_conta_nem_valor_zero(ctx, other):
    theirs = other.product("Outro", sku="OUTRO1")
    api = ctx.client()
    assert api.post("/api/v1/competitor-prices/", {"variant": str(theirs.pk), "competitor": "X", "price": "10"},
                    format="json").status_code == 400
    mine = _variant(ctx)
    assert api.post("/api/v1/competitor-prices/", {"variant": str(mine.pk), "competitor": "X", "price": "0"},
                    format="json").status_code == 400
    assert ctx.client(ctx.user("vend_conc", "seller")).post("/api/v1/competitor-prices/", {"variant": str(mine.pk), "competitor": "X", "price": "10"}, format="json").status_code != 201


def test_planilha_entra_pelo_sku_ou_codigo_e_devolve_as_linhas_com_problema(ctx):
    variant = _variant(ctx)
    _on(ctx)
    text = ("Produto;Concorrente;Preço;Data;Link\n"
            "FONE1;Loja A;R$ 1.100,50;02/11/2026;https://a.com/x\n"
            "7891234567895;Loja B;1200;;\n"
            "NAOEXISTE;Loja C;10;;\n"
            "FONE1;;10;;\n"
            "FONE1;Loja D;caro;;\n"
            "FONE1;Loja E;10;ontem;\n")
    upload = SimpleUploadedFile("precos.csv", text.encode("utf-8"), content_type="text/csv")
    response = ctx.client().post("/api/v1/competitor-prices/import/", {"file": upload}, format="multipart")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["imported"] == 2 and body["products"] == 1 and body["error_count"] == 4
    assert [e["linha"] for e in body["errors"]] == [4, 5, 6, 7]
    first = CompetitorPrice.all_objects.get(competitor="Loja A")
    assert first.price == D("1100.50") and str(first.observed_on) == "2026-11-02" and first.url == "https://a.com/x"
    assert PriceCheck.all_objects.get(variant=variant).competitors == 2


def test_planilha_sem_as_colunas_explica(ctx):
    with pytest.raises(BusinessError, match="colunas"):
        competitors.import_sheet(ctx.account, ctx.admin, "x.csv", b"Nome;Valor\nA;10\n")


# ── fontes externas (HTTP simulado com o formato real de cada uma) ─────────
class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


OURS = matching.Ours("Laranja Legal", "Tudo Legal", ("7898924646076",))


def _http(monkeypatch, status, body):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(status, body)

    monkeypatch.setattr(sources.requests, "get", get)
    return calls


def test_open_prices_um_preco_por_lugar_e_o_mais_novo(monkeypatch):
    calls = _http(monkeypatch, 200, {"items": [
        {"id": 3, "location_id": 1, "product_code": "7898924646076", "price": 15.49, "date": "2026-10-28",
         "location": {"osm_name": "Pão de Açúcar"}, "product": {"product_name": "Laranja Legal", "brands": "Tudo Legal"}},
        {"id": 2, "location_id": 1, "product_code": "7898924646076", "price": 12.00, "date": "2026-09-01"},
        {"id": 1, "location_id": 2, "product_code": "7898924646076", "price": 14.00, "duplicate_of": 9},
    ]})
    offers = sources.read_open_prices(None, OURS)
    assert [(o["price"], o["seller"]) for o in offers] == [(15.49, "Pão de Açúcar")]
    assert calls[0][1]["params"]["product_code"] == "7898924646076" and calls[0][1]["params"]["currency"] == "BRL"
    assert matching.score(OURS, offers[0]["title"], gtins=offers[0]["gtins"]).score == 100
    assert sources.read_open_prices(None, matching.Ours("Sem código")) == []


@override_settings(BLUESOFT_COSMOS_TOKEN="tok")
def test_bluesoft_usa_o_preco_medio_e_404_nao_e_erro(monkeypatch):
    calls = _http(monkeypatch, 200, {"gtin": 7898924646076, "description": "LARANJA LEGAL", "avg_price": 2.99,
                                     "brand": {"name": "TUDO LEGAL"}})
    offer = sources.read_cosmos(None, OURS, "tok")[0]
    assert offer["price"] == 2.99 and offer["gtins"] == ["7898924646076"]
    assert calls[0][1]["headers"]["X-Cosmos-Token"] == "tok"
    _http(monkeypatch, 404, {})
    assert sources.read_cosmos(None, OURS, "tok") == []
    _http(monkeypatch, 401, {"message": "Token Inválido"})
    with pytest.raises(sources.SourceError, match="recusou"):
        sources.read_cosmos(None, OURS, "tok")


def test_anuncio_real_de_coca_cola_2l():
    """Títulos que vieram de uma consulta real ao Google Shopping (03/11/2026)."""
    ours = matching.Ours("Coca-Cola 2L", "Coca-Cola", ("7894900011517",))
    for same in ("Refrigerante Coca Cola 2L", "Coca-Cola 2lt", "Refri Coca Cola 2,00 L"):
        assert matching.score(ours, same).score == 100, same
    assert matching.score(ours, "Coca-Cola Original Pet 2 Litros").score == 85  # as palavras estão, o título inteiro não
    for other in ("Refrigerante Coca Cola 2l Zero", "Coca-Cola sem Açúcar 2l", "Del Valle 100% Laranja 1L", "O Pequeno Príncipe - Edição Luxo",
                  "Pack Refrigerante Coca Cola 2 Unidades 2l", "Coca-Cola Original 2l Com 6un", "Refrigerante Coca-cola 6x2lts"):
        assert matching.score(ours, other).score < 85, other


def _shopping_by_query(monkeypatch, answers):
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"]["q"])
        return _Response(200, answers.get(kwargs["params"]["q"], {"error": "Google hasn't returned any results."}))

    monkeypatch.setattr(sources.requests, "get", get)
    return calls


def _found(title):
    return {"shopping_results": [{"position": 1, "title": title, "price": "R$ 10,00", "extracted_price": 10.0, "source": "Loja"}]}


def _many(title, *prices):
    return {"shopping_results": [{"position": i, "product_id": str(i), "title": title, "price": f"R$ {p},00",
                                  "extracted_price": p, "source": f"Loja {i}", "product_link": f"https://g/{i}"}
                                 for i, p in enumerate(prices)]}


def _cola(ctx, settings, *keys, barcode="7894900011517"):
    from starrp.models import Brand

    settings.SERPAPI_KEY, settings.BLUESOFT_COSMOS_TOKEN, settings.PRICE_DAILY_LIMITS = "k", "k", {}
    variant = ctx.product("Refrigerante 2L", price="10", sku="COCA", barcode=barcode)
    variant.product.brand = Brand.all_objects.create(account=ctx.account, name="Coca-Cola")
    variant.product.save()
    ctx.account.price_sources = list(keys)
    ctx.account.save()
    return variant


TITLED = "Refrigerante 2L Coca-Cola"


def test_busca_por_titulo_e_marca_e_para_no_minimo(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    calls = _shopping_by_query(monkeypatch, {TITLED: _many(TITLED, 10, 11, 12)})
    check = tracker.check_variant(variant)
    assert calls == [TITLED] and sources.used_this_month(ctx.account) == 1  # chegou ao mínimo: não gasta o EAN
    assert check.searches == [{"source": "serpapi", "query": TITLED, "offers": 3, "matched": 3}]
    assert {o.query for o in check.offers.all()} == {TITLED}


def test_oferta_no_limite_da_faixa_fica_marcada_como_usada(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    answer = {"shopping_results": [{"position": i, "title": TITLED, "price": f"R$ {p}", "extracted_price": p, "source": f"Loja {i}"}
                                   for i, p in enumerate((10.39, 11.29, 12.59))]}
    _shopping_by_query(monkeypatch, {TITLED: answer})
    check = tracker.check_variant(variant)
    assert check.competitors == 3 and check.offers.filter(used=True).count() == 3


def test_marca_que_ja_esta_no_titulo_nao_repete():
    assert sources._shopping_queries(matching.Ours("Coca-Cola 2L", "Coca-Cola")) == ["Coca-Cola 2L"]


def test_titulo_com_oferta_aceita_nao_gasta_a_busca_por_ean(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    calls = _shopping_by_query(monkeypatch, {TITLED: _many(TITLED, 10), "7894900011517": _many(TITLED, 10, 11, 12)})
    check = tracker.check_variant(variant)
    assert calls == [TITLED] and check.competitors == 1  # abaixo do mínimo, mas o título achou: só informa


def test_titulo_sem_oferta_aceita_busca_pelo_ean_sem_repetir_a_mesma_oferta(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    junk = "Del Valle Laranja"
    answer = {"shopping_results": [*_many(junk, 9)["shopping_results"], *_many("Refrigerante Coca-Cola 2L Pet", 10, 11, 12)["shopping_results"]]}
    calls = _shopping_by_query(monkeypatch, {TITLED: _many(junk, 9), "7894900011517": answer})
    check = tracker.check_variant(variant)
    assert calls == [TITLED, "7894900011517"] and sources.used_this_month(ctx.account) == 2
    assert check.offers.count() == 4 and check.searches[0]["matched"] == 0 and check.searches[1]["offers"] == 4
    from_code = [o for o in check.offers.all() if o.query == "7894900011517"]
    assert from_code and all("Título" in o.match_reason for o in from_code)  # o critério da busca por código
    assert all("palavras do título" in o.match_reason for o in check.offers.all() if o.query == TITLED)


def test_titulo_sem_resultado_busca_pelo_ean(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    calls = _shopping_by_query(monkeypatch, {"7894900011517": _many(TITLED, 10, 11, 12)})
    assert tracker.check_variant(variant).competitors == 3 and calls == [TITLED, "7894900011517"]


def test_oferta_da_busca_por_ean_passa_pelo_pareamento(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    _shopping_by_query(monkeypatch, {"7894900011517": _many("O Pequeno Príncipe - Edição Luxo", 10, 11, 12)})
    check = tracker.check_variant(variant)
    assert check.competitors == 0 and check.searches[1]["offers"] == 3 and check.searches[1]["matched"] == 0


def _second_code(variant, code):
    from starrp.models import ProductBarcode

    ProductBarcode.all_objects.create(account_id=variant.account_id, variant=variant, code=code)


GTIN14 = "17894900011514"


def test_busca_usa_o_ean_e_o_gtin_ate_achar(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    _second_code(variant, GTIN14)
    calls = _shopping_by_query(monkeypatch, {GTIN14: _many(TITLED, 10, 11, 12)})
    check = tracker.check_variant(variant)
    assert calls == [TITLED, "7894900011517", GTIN14] and check.competitors == 3
    assert [s["query"] for s in check.searches] == calls
    assert {o.query for o in check.offers.all()} == {GTIN14}

    calls = _shopping_by_query(monkeypatch, {"7894900011517": _many(TITLED, 10, 11, 12)})
    tracker.check_variant(variant)
    assert calls == [TITLED, "7894900011517"]  # o primeiro código resolveu: não gasta o segundo


def test_mesmo_codigo_com_zero_a_esquerda_e_uma_busca_so(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    _second_code(variant, "07894900011517")
    calls = _shopping_by_query(monkeypatch, {})
    tracker.check_variant(variant)
    assert calls == [TITLED, "7894900011517"]


def test_fontes_de_codigo_leem_o_ean_e_o_gtin_e_nunca_o_interno(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "cosmos", "open_prices")
    _second_code(variant, GTIN14)
    _second_code(variant, "2000000000015")
    read = []

    def get(url, **kwargs):
        read.append(url.rsplit("/", 1)[-1].replace(".json", "") if "bluesoft" in url else kwargs["params"]["product_code"])
        return _Response(404, {}) if "bluesoft" in url else _Response(200, {"items": []})

    monkeypatch.setattr(sources.requests, "get", get)
    check = tracker.check_variant(variant)
    assert read == ["7894900011517", GTIN14, "7894900011517", GTIN14] and sources.used_this_month(ctx.account) == 2
    assert [s["query"] for s in check.searches] == read


def test_codigo_interno_da_loja_nao_busca_pelo_ean(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi", barcode="2000000000015")
    calls = _shopping_by_query(monkeypatch, {})
    assert not tracker.check_variant(variant).error and calls == [TITLED]


def test_sem_saldo_para_o_ean_guarda_o_que_achou_e_avisa(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi")
    ctx.account.price_monthly_requests = 1
    ctx.account.save()
    calls = _shopping_by_query(monkeypatch, {TITLED: _many("Del Valle Laranja", 10)})
    check = tracker.check_variant(variant)
    assert calls == [TITLED] and check.offers.count() == 1 and "limite mensal" in check.error


def _reads(monkeypatch):
    """Quem foi consultado, em ordem. As fontes de código não acham nada."""
    read, answers = [], {"google": True}

    def get(url, **kwargs):
        if "serpapi" in url:
            read.append(kwargs["params"]["q"])
            return _Response(200, _many(TITLED, 10, 11, 12) if answers["google"] else {"error": "any results"})
        read.append("open_prices" if "openfoodfacts" in url else "cosmos")
        return _Response(200, {"items": []}) if "openfoodfacts" in url else _Response(404, {})

    monkeypatch.setattr(sources.requests, "get", get)
    return read, answers


def test_outras_fontes_so_entram_abaixo_do_minimo(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "cosmos", "open_prices", "serpapi")  # a ordem na conta não muda a da leitura
    read, answers = _reads(monkeypatch)
    tracker.check_variant(variant)
    assert read == [TITLED]
    read.clear()
    answers["google"] = False
    check = tracker.check_variant(variant)
    assert read == [TITLED, "7894900011517", "cosmos", "open_prices"]
    assert [s["source"] for s in check.searches] == ["serpapi", "serpapi", "cosmos", "open_prices"]


def test_pesquisa_da_equipe_sempre_entra_e_conta_para_o_minimo(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi", "manual")
    for shop, price in (("A", "10"), ("B", "11")):
        CompetitorPrice.all_objects.create(account=ctx.account, variant=variant, competitor=shop, price=D(price))
    calls = _shopping_by_query(monkeypatch, {TITLED: _many(TITLED, 12)})
    check = tracker.check_variant(variant)
    assert calls == [TITLED] and check.competitors == 3  # 2 da equipe + 1 do Google: não precisou do EAN
    assert [s["source"] for s in check.searches] == ["serpapi"]  # informar preço não é uma busca


def test_recalcular_com_preco_da_equipe_nao_apaga_o_que_foi_pesquisado(ctx, monkeypatch, settings):
    variant = _cola(ctx, settings, "serpapi", "manual")
    calls = _shopping_by_query(monkeypatch, {TITLED: _many(TITLED, 10, 11, 12)})
    first = tracker.check_variant(variant)
    CompetitorPrice.all_objects.create(account=ctx.account, variant=variant, competitor="A", price=D("10"))
    again = tracker.check_variant(variant, fresh={"manual"})
    assert len(calls) == 1 and again.searches == first.searches and again.competitors == 4
    assert TITLED in {o.query for o in again.offers.all()}


def test_da_grade_so_a_medida_fica_no_titulo(ctx):
    variant = _variant(ctx)
    for name, title in (("Branca / P", ""), ("42", ""), ("128GB / Preto", "128GB"), ("", "")):
        variant.name = name
        assert tracker._ours(variant).title == f"{variant.product.name} {title}".strip()


# ── botão do produto, regras e achados ─────────────────────────────────────
def _google(calls, monkeypatch, settings, title="Fone Bluetooth JBL Tune 510BT Preto"):
    """A fonte de verdade, com a resposta da SerpApi trocada."""
    settings.SERPAPI_KEY, settings.PRICE_DAILY_LIMITS = "k", {}

    def get(url, **kwargs):
        calls.append(kwargs["params"]["q"])
        return _Response(200, {"shopping_results": [
            {"position": i, "product_id": str(i), "title": title, "price": f"R$ {p},00", "extracted_price": p,
             "source": f"Loja {i}", "product_link": f"https://google/{i}"} for i, p in enumerate((100, 110, 120))]})

    monkeypatch.setattr(sources.requests, "get", get)


def test_botao_do_produto_le_todas_as_variacoes_com_uma_consulta(ctx, monkeypatch, settings):
    calls = []
    _google(calls, monkeypatch, settings)
    first = _variant(ctx)
    second = ProductVariant.all_objects.create(account=ctx.account, product=first.product, sku="FONE2", name="Azul", price=D("150"))
    ProductVariant.all_objects.filter(pk=first.pk).update(name="Preto")
    ctx.account.price_sources = ["serpapi"]
    ctx.account.save()
    response = ctx.client().post("/api/v1/price-checks/product/", {"product": str(first.product_id)}, format="json")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["checked"] == 2 and len(calls) == 1 and sources.used_this_month(ctx.account) == 1
    assert PriceCheck.all_objects.filter(variant__in=[first, second]).count() == 2  # sem o rastreamento automático ligado
    detail = ctx.client().get(f"/api/v1/price-checks/{body['ids'][0]}/").json()
    assert [o["url"] for o in detail["offers"] if o["used"]] and all(o["url"].startswith("https://google/") for o in detail["offers"])
    assert {"title", "price", "seller", "match_score", "match_reason", "used", "query"} <= set(detail["offers"][0])
    assert detail["searches"][0]["query"] == calls[0]
    assert "offers" not in ctx.client().get("/api/v1/price-checks/").json()["results"][0]  # a lista não carrega as ofertas


def test_clique_cria_o_item_na_hora_e_a_leitura_vai_para_o_worker(ctx, monkeypatch, settings):
    from starrp.tasks import market as tasks

    calls = []
    _google(calls, monkeypatch, settings)
    sent = []
    monkeypatch.setattr(tasks.price_read, "delay", lambda *args: sent.append(args))
    variant = _variant(ctx)
    ctx.account.price_sources = ["serpapi"]
    ctx.account.save()
    api = ctx.client()

    body = api.post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json").json()
    assert not calls and [args[:2] for args in sent] == [(str(ctx.account.pk), [str(variant.pk)])]  # nada foi consultado dentro do clique
    item = api.get(f"/api/v1/price-checks/{body['ids'][0]}/").json()
    assert item["reading"] is True and item["reading_stalled"] is False and item["checked_at"] is None
    assert item["product_name"] and item["current_price"] == "150.00" and item["cost"] and item["offers"] == []
    assert item["position"] == "unknown" and item["status"] == "none"

    api.post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json")
    assert len(sent) == 1  # segundo clique com a leitura na fila: não manda de novo

    tasks.price_read(*sent[0])  # o worker roda
    done = api.get(f"/api/v1/price-checks/{body['ids'][0]}/").json()
    assert done["reading"] is False and done["checked_at"] and done["competitors"] == 3 and len(calls) == 1
    assert PriceCheck.all_objects.filter(variant=variant).count() == 1  # o mesmo item, não outro


def test_ler_agora_no_item_e_na_lista_tambem_vao_para_o_worker(ctx, monkeypatch, settings):
    from starrp.tasks import market as tasks

    calls, sent = [], []
    _google(calls, monkeypatch, settings)
    monkeypatch.setattr(tasks.price_read, "delay", lambda *args: sent.append(args))
    variant = _variant(ctx)
    ctx.account.price_tracking_enabled, ctx.account.price_sources = True, ["serpapi"]
    ctx.account.save()
    api = ctx.client()
    assert api.post("/api/v1/price-checks/run/").json()["checked"] >= 1
    check = PriceCheck.all_objects.get(variant=variant)
    PriceCheck.all_objects.filter(pk=check.pk).update(reading_since=None)
    sent.clear()
    calls.clear()
    assert api.post(f"/api/v1/price-checks/{check.pk}/refresh/").json()["reading"] is True
    assert len(sent) == 1 and not calls


def test_leitura_presa_avisa_e_deixa_tentar_de_novo(ctx, monkeypatch, settings):
    from starrp.tasks import market as tasks

    calls, sent = [], []
    _google(calls, monkeypatch, settings)
    monkeypatch.setattr(tasks.price_read, "delay", lambda *args: sent.append(args))
    variant = _variant(ctx)
    ctx.account.price_sources = ["serpapi"]
    ctx.account.save()
    api = ctx.client()
    body = api.post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json").json()
    with freeze_time(timezone.now() + timedelta(minutes=11)):
        item = api.get(f"/api/v1/price-checks/{body['ids'][0]}/").json()
        assert item["reading"] is False and item["reading_stalled"] is True
        api.post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json")
        assert len(sent) == 2


def test_falha_no_worker_nao_deixa_o_item_lendo_para_sempre(ctx, monkeypatch, settings):
    from starrp.tasks import market as tasks

    calls, sent = [], []
    _google(calls, monkeypatch, settings)
    monkeypatch.setattr(tasks.price_read, "delay", lambda *args: sent.append(args))
    variant = _variant(ctx)
    ctx.account.price_sources = ["serpapi"]
    ctx.account.save()
    ctx.client().post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json")

    def boom(*args, **kwargs):
        raise RuntimeError("erro inesperado com segredo")

    monkeypatch.setattr(tracker, "check_variant", boom)
    tasks.price_read(*sent[0])
    check = PriceCheck.all_objects.get(variant=variant)
    assert check.reading_since is None and "falhou" in check.error and "segredo" not in check.error


def test_fila_fora_do_ar_avisa_e_nao_deixa_o_item_preso(ctx, monkeypatch, settings):
    from kombu.exceptions import OperationalError

    from starrp.tasks import market as tasks

    _google([], monkeypatch, settings)

    def down(*args):
        raise OperationalError("sem redis")

    monkeypatch.setattr(tasks.price_read, "delay", down)
    variant = _variant(ctx)
    ctx.account.price_sources = ["serpapi"]
    ctx.account.save()
    response = ctx.client().post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json")
    assert response.status_code == 422 and "fila" in str(response.json())
    assert PriceCheck.all_objects.get(variant=variant).reading_since is None


def test_worker_so_le_a_conta_do_pedido(ctx, other, monkeypatch, settings):
    from starrp.tasks import market as tasks

    calls = []
    _google(calls, monkeypatch, settings)
    alheio = other.product("Fone Bluetooth JBL Tune 510BT Preto", price="10", sku="OUTRO")
    tasks.price_read(str(ctx.account.pk), [str(alheio.pk)])
    assert not calls and not PriceCheck.all_objects.filter(variant=alheio).exists()


def test_botao_do_produto_recusa_o_que_nao_cabe(ctx, other):
    api = ctx.client()
    service = ctx.product("Instalação", price="80", sku="SERV1", type=Product.Type.SERVICE)
    assert api.post("/api/v1/price-checks/product/", {"product": str(service.product_id)}, format="json").status_code == 422
    assert api.post("/api/v1/price-checks/product/", {"product": "nao-e-uuid"}, format="json").status_code == 400
    alheio = other.product("De outra conta", price="10", sku="OUTRO")
    assert api.post("/api/v1/price-checks/product/", {"product": str(alheio.product_id)}, format="json").status_code == 422
    assert not PriceCheck.all_objects.filter(variant=alheio).exists()


def _catalog(ctx):
    from starrp.models import Brand, Category

    drinks = Category.all_objects.create(account=ctx.account, name="Bebidas")
    soda = Category.all_objects.create(account=ctx.account, name="Refrigerantes", parent=drinks)
    a, b = (Brand.all_objects.create(account=ctx.account, name=n) for n in ("Marca A", "Marca B"))
    rows = {}
    for sku, category, brand, price in (("COLA", soda, a, "10"), ("GUAR", drinks, b, "20"), ("MESA", None, None, "500")):
        rows[sku] = ctx.product(sku, price=price, sku=sku)
        rows[sku].product.category, rows[sku].product.brand = category, brand
        rows[sku].product.save()
    return drinks, a, rows


def _rules(ctx, **body):
    response = ctx.client().post("/api/v1/price-checks/rules/", body, format="json")
    assert response.status_code == 200, response.json()
    ctx.account.refresh_from_db()
    return {v.sku for v in tracker.trackable(ctx.account)}


def test_regras_escolhem_o_que_a_leitura_pega(ctx):
    drinks, brand, rows = _catalog(ctx)
    everything = {"COLA", "GUAR", "MESA"}
    assert everything <= {v.sku for v in tracker.trackable(ctx.account)}  # sem regra: tudo
    assert _rules(ctx, categories=[str(drinks.pk)]) == {"COLA", "GUAR"}  # leva a subcategoria
    assert _rules(ctx, categories=[str(drinks.pk)], brands=[str(brand.pk)]) == {"COLA"}  # as duas juntas
    assert _rules(ctx, brands=[str(brand.pk)], products=[str(rows["MESA"].product_id)]) == {"COLA", "MESA"}  # o escolhido entra
    assert _rules(ctx, categories=[str(drinks.pk)], exclude_products=[str(rows["COLA"].product_id)]) == {"GUAR"}
    assert _rules(ctx, categories=[str(drinks.pk)], min_price="15") == {"GUAR"}
    assert _rules(ctx, categories=[str(drinks.pk)], max_price="15.50") == {"COLA"}
    assert _rules(ctx, products=[str(rows["MESA"].product_id)], only_with_barcode=True) == set()
    assert _rules(ctx) >= everything  # limpou: volta a ser tudo
    assert tracker.due(ctx.account, 50)


def test_varredura_e_ler_agora_respeitam_as_regras_mas_o_botao_do_produto_nao(ctx, monkeypatch, settings):
    calls = []
    _google(calls, monkeypatch, settings)
    _, _, rows = _catalog(ctx)
    _rules(ctx, products=[str(rows["COLA"].product_id)])
    ctx.account.price_tracking_enabled, ctx.account.price_sources = True, ["serpapi"]
    ctx.account.save()
    assert ctx.client().post("/api/v1/price-checks/run/").json()["checked"] == 1
    assert PriceCheck.all_objects.filter(variant=rows["COLA"]).exists() and not PriceCheck.all_objects.filter(variant=rows["MESA"]).exists()
    assert ctx.client().post("/api/v1/price-checks/product/", {"product": str(rows["MESA"].product_id)}, format="json").status_code == 200
    assert PriceCheck.all_objects.filter(variant=rows["MESA"]).exists()


def test_regras_nao_aceitam_item_de_outra_conta_nem_faixa_invertida(ctx, other):
    from starrp.models import Brand

    api = ctx.client()
    alheia = Brand.all_objects.create(account=other.account, name="Alheia")
    assert api.post("/api/v1/price-checks/rules/", {"brands": [str(alheia.pk)]}, format="json").status_code == 400
    assert api.post("/api/v1/price-checks/rules/", {"min_price": "20", "max_price": "10"}, format="json").status_code == 400
    ctx.account.refresh_from_db()
    assert not ctx.account.price_scope


def test_sem_permissao_nao_mexe_nas_regras_nem_precifica(ctx):
    variant = ctx.product("Produto", price="10", sku="P1")
    api = ctx.client(ctx.user("auditor-precos", "auditor"))  # vê o catálogo, mas não gerencia
    assert api.get("/api/v1/price-checks/").status_code == 200
    assert api.get("/api/v1/price-checks/rules/").status_code == 403
    assert api.post("/api/v1/price-checks/product/", {"product": str(variant.product_id)}, format="json").status_code == 403


def test_produtos_reais_na_demo(ctx):
    from django.core.management import call_command

    from starrp.management.commands.seed_real_products import REAL_PRODUCTS
    from starrp.services.barcodes import ean_check_digit_ok

    assert all(ean_check_digit_ok(ean) for *_, ean in REAL_PRODUCTS if ean)
    cola = ctx.product("Refrigerante Cola 2L", price="10.00", barcode="7891000000017", sku="COLA")
    cola.average_cost = D("4.00")
    cola.save()
    queijo = ctx.product("Queijo Mussarela (kg)", price="54.90", barcode="7891000000024", sku="QUEIJO")
    ctx.account.extra_modules, ctx.account.price_sources = [], ["manual"]
    ctx.account.save()
    call_command("seed_real_products", account=ctx.account.slug)
    call_command("seed_real_products", account=ctx.account.slug)  # de novo: não muda nada

    cola.refresh_from_db()
    assert cola.product.name == "Coca-Cola 2L" and cola.product.brand.name == "Coca-Cola" and cola.price == D("11.49")
    assert cola.average_cost == D("4.596")  # margem igual
    assert [b.code for b in cola.barcodes.all()] == ["7894900011517"]
    queijo.refresh_from_db()
    code = queijo.barcodes.get().code
    assert queijo.product.name == "Queijo Mussarela Tirolez" and code.startswith("2") and ean_check_digit_ok(code)
    ctx.account.refresh_from_db()
    assert ctx.account.has_module("pricing") and ctx.account.price_tracking_enabled
    assert ctx.account.price_sources == ["manual", "brightdata", "serpapi"]


@override_settings(SERPAPI_KEY="k")
def test_serpapi_so_em_reais(monkeypatch):
    calls = _http(monkeypatch, 200, {"shopping_results": [
        {"position": 1, "title": "Laranja Legal", "price": "R$ 15,90", "extracted_price": 15.9, "source": "Loja X",
         "product_link": "https://g/1"},
        {"position": 2, "title": "Laranja Legal", "price": "$3.00", "extracted_price": 3.0, "source": "Fora"},
    ]})
    offers = sources.read_serpapi("Laranja Legal", "k")
    assert [(o["price"], o["seller"]) for o in offers] == [(15.9, "Loja X")]
    assert calls[0][1]["params"]["gl"] == "br" and calls[0][1]["params"]["engine"] == "google_shopping"
    _http(monkeypatch, 200, {"error": "Google hasn't returned any results for this query."})
    assert sources.read_serpapi("Laranja Legal", "k") == []
    _http(monkeypatch, 200, {"error": "Your account has run out of searches."})
    with pytest.raises(sources.SourceError):
        sources.read_serpapi("Laranja Legal", "k")


def test_fonte_sem_chave_nao_fica_ativa(ctx, settings):
    settings.SERPAPI_KEY = ""
    ctx.account.price_sources = ["serpapi", "manual"]
    assert [s.key for s in sources.active(ctx.account)] == ["manual"]
    settings.SERPAPI_KEY = "k"
    assert [s.key for s in sources.active(ctx.account)] == ["manual", "serpapi"]  # a equipe sempre primeiro


# ── controle da plataforma: módulo, limite mensal e chaves da conta ────────
def _tool(monkeypatch, settings, status=200, body=None):
    settings.SHOPPING_SEARCH_URL, settings.SHOPPING_SEARCH_TOKEN = "http://busca.local:8010/", "token-da-ferramenta"
    settings.SERPAPI_KEY, settings.PRICE_DAILY_LIMITS = "chave-serpapi", {}
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(status, body if body is not None else {"query": "q", "count": 0, "elapsed_ms": 1, "products": []})

    monkeypatch.setattr(sources.requests, "get", get)
    return calls


def _card(title, price, merchant="Loja X", **extra):
    return {"source": "google_shopping", "offer_id": f"o{price}", "product_id": "p", "title": title, "price": price,
            "price_text": f"R$ {price}", "currency": "BRL", "merchant": merchant, "url": "https://loja.exemplo/produto",
            "shipping": "Frete grátis", "sponsored": False, **extra}


FONE = "Fone Bluetooth JBL Tune 510BT Preto"


def test_google_shopping_e_a_ferramenta_propria(ctx, monkeypatch, settings):
    calls = _tool(monkeypatch, settings, body={"products": [
        _card(FONE, 100, "Loja A"), _card(FONE, 110, "Loja B"), _card(FONE, 120, "Loja C", shipping="R$ 15,00")]})
    variant = _variant(ctx)
    ctx.account.price_sources = ["google_shopping"]
    ctx.account.save()
    check = tracker.check_variant(variant)
    url, kwargs = calls[0]
    assert url == "http://busca.local:8010/v1/search" and kwargs["headers"]["X-API-Token"] == "token-da-ferramenta"
    assert "api_key" not in kwargs["params"] and kwargs["timeout"] == sources.SEARCH_TIMEOUT
    assert len(calls) == 1 and check.competitors == 3 and check.searches[0]["source"] == "google_shopping"
    assert check.source == "Google Shopping" and sources.used_this_month(ctx.account) == 1  # conta no limite mensal
    offers = {o.seller: o for o in check.offers.all()}
    assert offers["Loja A"].url == "https://loja.exemplo/produto" and offers["Loja A"].free_shipping
    assert not offers["Loja C"].free_shipping


def test_serpapi_e_outra_fonte_e_nao_chama_a_ferramenta(ctx, monkeypatch, settings):
    calls = _tool(monkeypatch, settings, body={"shopping_results": []})
    ctx.account.price_sources = ["serpapi"]
    ctx.account.save()
    tracker.check_variant(_variant(ctx))
    assert calls and all("serpapi.com" in url for url, _ in calls)


def test_ferramenta_vem_antes_e_a_serpapi_so_completa_o_minimo(ctx, monkeypatch, settings):
    _tool(monkeypatch, settings)
    read = []

    def get(url, **kwargs):
        read.append("serpapi" if "serpapi.com" in url else "ferramenta")
        if "serpapi.com" in url:
            return _Response(200, {"shopping_results": [
                {"position": i, "title": FONE, "price": f"R$ {p},00", "extracted_price": p, "source": f"Loja {p}"}
                for i, p in enumerate(answers["serpapi"])]})
        return _Response(200, {"products": [_card(FONE, p, f"Loja {p}") for p in answers["tool"]]})

    monkeypatch.setattr(sources.requests, "get", get)
    variant = _variant(ctx)
    variant.barcodes.update(code="2000000000015")  # uma busca por fonte, pelo título
    ctx.account.price_sources = ["google_shopping", "serpapi"]
    ctx.account.save()

    answers = {"tool": [100], "serpapi": [110, 120]}  # a primeira achou, mesmo abaixo do mínimo: não gasta a segunda
    check = tracker.check_variant(variant)
    assert read == ["ferramenta"] and check.competitors == 1

    read.clear()
    answers = {"tool": [], "serpapi": [100, 110, 120]}  # não trouxe nenhuma aceita: é falha, passa a vez
    check = tracker.check_variant(variant)
    assert read == ["ferramenta", "serpapi"] and check.competitors == 3
    assert [s["source"] for s in check.searches] == ["google_shopping", "serpapi"]

    read.clear()
    ctx.account.price_sources = ["serpapi", "google_shopping"]  # a ordem da conta é a da fila
    ctx.account.save()
    variant = ProductVariant.all_objects.select_related("product", "account").get(pk=variant.pk)
    check = tracker.check_variant(variant)
    assert read == ["serpapi"] and check.source == "SerpApi"

    read.clear()
    ctx.account.price_search_mode = "all"  # todas sempre, e a mesma loja nas duas conta uma vez
    ctx.account.price_sources = ["google_shopping", "serpapi"]
    ctx.account.save()
    answers = {"tool": [100, 110, 120], "serpapi": [100, 130]}
    variant = ProductVariant.all_objects.select_related("product", "account").get(pk=variant.pk)
    check = tracker.check_variant(variant)
    assert read == ["ferramenta", "serpapi"] and check.offers.count() == 4 and check.competitors == 4
    assert check.source == "Google Shopping, SerpApi"


def test_fontes_e_modo_nao_aparecem_nem_mudam_pela_conta(ctx):
    ctx.account.price_sources = ["manual", "serpapi"]
    ctx.account.save()
    api = ctx.client()
    body = api.get("/api/v1/account/settings/").json()["cosmos"]
    assert not {"price_sources", "price_search_mode", "price_sources_status"} & set(body)
    saved = api.patch("/api/v1/account/settings/", {"cosmos": {"price_search_mode": "all", "price_sources": ["brightdata"]}}, format="json")
    assert saved.status_code == 200
    ctx.account.refresh_from_db()
    assert ctx.account.price_sources == ["manual", "serpapi"] and ctx.account.price_search_mode == "fallback"


def test_conta_nova_vem_com_todas_as_fontes_na_ordem(ctx):
    from starrp.models import Account

    assert Account(name="Nova").price_sources == ["manual", "brightdata", "serpapi"]


REAL_NAMES = ("bright", "serpapi", "serp", "bluesoft", "open prices", "open_prices", "search-shop", "brd")


def _assert_no_provider(text):
    low = text.lower()
    assert not [name for name in REAL_NAMES if name in low], text[:400]


def test_conta_nunca_ve_qual_api_foi_usada(ctx, monkeypatch, settings):
    calls = _brightdata(monkeypatch, settings, body={"shopping": [_shop(FONE, f"R$ {p}", f"Loja {p}", p) for p in (100, 110, 120)]})
    settings.BLUESOFT_COSMOS_TOKEN = "tok"
    variant = _variant(ctx)
    ctx.account.price_sources = ["brightdata"]
    ctx.account.save()
    api = ctx.client()
    check = tracker.check_variant(variant)
    assert check.source == "Bright Data" and calls  # gravado com o nome real, para a plataforma
    PriceCheck.all_objects.filter(pk=check.pk).update(error="Bright Data: o Google recusou. Bluesoft Cosmos fora do ar. SerpApi: limite.")
    tracker.check_variant(variant, RULES, [sources.SOURCES["brightdata"]])  # gera histórico com a fonte mudando
    PriceCheck.all_objects.filter(pk=check.pk).update(error="Bright Data: o Google recusou. Bluesoft Cosmos fora do ar. SerpApi: limite.")

    detail = api.get(f"/api/v1/price-checks/{check.pk}/")
    assert detail.json()["source"] == "Google Shopping"
    assert detail.json()["error"] == "Google Shopping: o Google recusou. Banco colaborativo fora do ar. Google Shopping: limite."
    assert {o["source"] for o in detail.json()["offers"]} == {"google_shopping"}
    assert detail.json()["searches"][0]["source"] == "google_shopping"
    for url in (f"/api/v1/price-checks/{check.pk}/", "/api/v1/price-checks/", f"/api/v1/market-offers/?price_check={check.pk}",
                f"/api/v1/price-checks/{check.pk}/history/", "/api/v1/account/settings/"):
        response = api.get(url)
        assert response.status_code == 200, url
        _assert_no_provider(response.content.decode().replace("api/v1", ""))


def test_banco_colaborativo_e_equipe_aparecem_com_o_nome_certo(ctx, monkeypatch, settings):
    settings.BLUESOFT_COSMOS_TOKEN, settings.PRICE_DAILY_LIMITS = "tok", {}
    variant = _variant(ctx)
    ctx.account.price_sources = ["cosmos"]
    ctx.account.save()
    CompetitorPrice.all_objects.create(account=ctx.account, variant=variant, competitor="Vizinho", price=D("100"))
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: _Response(200, {
        "gtin": 7891234567895, "description": "Fone", "avg_price": 120.0, "brand": {"name": "JBL"}}))
    check = tracker.check_variant(variant)
    body = ctx.client().get(f"/api/v1/price-checks/{check.pk}/").json()
    assert body["source"] == "Banco colaborativo, Pesquisa da equipe" or body["source"] == "Pesquisa da equipe, Banco colaborativo"
    assert {o["source"] for o in body["offers"]} == {"manual", "collaborative"}
    _assert_no_provider(str(body).replace("api/v1", ""))


def test_admin_define_as_fontes_na_ordem_e_a_equipe_nao_sai(ctx, client, django_user_model):
    root = django_user_model.objects.create_superuser("root-fontes", "root-fontes@x.com", "x")
    client.force_login(root)
    url = f"/admin/starrp/account/{ctx.account.pk}/change/"
    page = client.get(url)
    assert "Fontes prontas para usar" in page.content.decode()
    data = _admin_post_data(page)
    data.update(price_sources="serpapi\nbrightdata\nserpapi", price_search_mode="all")
    assert client.post(url, data).status_code == 302
    ctx.account.refresh_from_db()
    assert ctx.account.price_sources == ["manual", "serpapi", "brightdata"] and ctx.account.price_search_mode == "all"
    data["price_sources"] = "inventada"
    assert client.post(url, data).status_code == 200  # volta com o erro
    ctx.account.refresh_from_db()
    assert ctx.account.price_sources == ["manual", "serpapi", "brightdata"]


def test_bloqueio_guardadas_nao_impedem_a_proxima_fonte(ctx, monkeypatch, settings):
    _tool(monkeypatch, settings)
    variant = _variant(ctx)
    ctx.account.price_sources = ["google_shopping", "serpapi"]
    ctx.account.save()
    variant = ProductVariant.all_objects.select_related("product__brand", "account").get(pk=variant.pk)
    cards = {"products": [_card(FONE, p, f"Loja {p}") for p in (100, 110, 120)]}
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: _Response(200, cards))
    assert tracker.check_variant(variant).competitors == 3

    read = []

    def get(url, **kwargs):
        read.append("serpapi" if "serpapi.com" in url else "ferramenta")
        if "serpapi.com" in url:
            return _Response(200, {"shopping_results": [
                {"position": 1, "title": FONE, "price": "R$ 130,00", "extracted_price": 130, "source": "Loja 130"}]})
        return _Response(429, {"detail": "many queries"})

    monkeypatch.setattr(sources.requests, "get", get)
    check = tracker.check_variant(variant)
    assert read == ["ferramenta", "serpapi"]  # as 3 guardadas davam o mínimo, mas quem falhou passa a vez
    assert check.competitors == 4 and "bloqueou" in check.error


def test_bloqueio_na_ferramenta_cai_para_a_serpapi_quando_marcada(ctx, monkeypatch, settings):
    _tool(monkeypatch, settings)

    def get(url, **kwargs):
        if "serpapi.com" in url:
            return _Response(200, {"shopping_results": [
                {"position": i, "title": FONE, "price": f"R$ {p},00", "extracted_price": p, "source": f"Loja {p}"}
                for i, p in enumerate((100, 110, 120))]})
        return _Response(429, {"detail": "many queries"})

    monkeypatch.setattr(sources.requests, "get", get)
    ctx.account.price_sources = ["google_shopping", "serpapi"]
    ctx.account.save()
    check = tracker.check_variant(_variant(ctx))
    assert "bloqueou" in check.error and check.competitors == 3 and check.source == "SerpApi"


def test_ferramenta_so_em_reais_e_com_preco(monkeypatch, settings):
    _tool(monkeypatch, settings, body={"products": [
        _card("A", 10.5), _card("B", 3.0, currency="USD", price_text="$3.00"), _card("C", None),
        _card("D", 7.0, currency=None, price_text="R$ 7,00"), _card("E", 8.0, currency=None, price_text=None),
    ]})
    assert [o["title"] for o in sources.read_google_shopping("algo", "t", "http://busca.local")] == ["A", "D"]


def test_ferramenta_corta_a_busca_no_tamanho_que_aceita(monkeypatch, settings):
    calls = _tool(monkeypatch, settings)
    sources.read_google_shopping("x" * 300, "t", "http://busca.local")
    assert len(calls[0][1]["params"]["q"]) == 200


@pytest.mark.parametrize("status, message", [(429, "bloqueou"), (401, "recusou"), (503, "503")])
def test_falha_da_ferramenta_nao_gasta_a_outra_busca_nem_mostra_o_token(ctx, monkeypatch, settings, status, message):
    calls = _tool(monkeypatch, settings, status=status, body={"detail": "x"})
    check = tracker.check_variant(_variant(ctx), RULES, [sources.SOURCES["google_shopping"]])
    assert message in check.error and len(calls) == 1
    assert "token-da-ferramenta" not in check.error


def test_ferramenta_exige_endereco_e_token(ctx, settings):
    source = sources.SOURCES["google_shopping"]
    settings.SHOPPING_SEARCH_URL, settings.SHOPPING_SEARCH_TOKEN = "http://busca.local", ""
    assert not source.configured(ctx.account)
    settings.SHOPPING_SEARCH_URL, settings.SHOPPING_SEARCH_TOKEN = "", "t"
    assert not source.configured(ctx.account)
    settings.SHOPPING_SEARCH_URL = "http://busca.local"
    assert source.configured(ctx.account)
    body = ctx.client().get("/api/v1/account/settings/").content.decode()
    assert "http://busca.local" not in body and '"t"' not in body


def test_cada_fonte_do_google_tem_o_seu_teto_do_dia(ctx, monkeypatch, settings):
    from django.core.cache import cache

    cache.clear()
    _tool(monkeypatch, settings)
    settings.PRICE_DAILY_LIMITS = {"serpapi": 1, "google_shopping": 2}
    tool, serp = sources.SOURCES["google_shopping"], sources.SOURCES["serpapi"]
    assert [bool(sources.take_budget(tool, ctx.account)) for _ in range(3)] == [False, False, True]
    assert [bool(sources.take_budget(serp, ctx.account)) for _ in range(2)] == [False, True]


def test_ferramenta_aceita_token_e_endereco_da_conta(ctx, monkeypatch, settings):
    calls = _tool(monkeypatch, settings)
    PriceSourceToken.objects.create(account=ctx.account, source="google_shopping", token="token-da-conta", option="http://da-conta:9000")
    tracker.check_variant(_variant(ctx), RULES, [sources.SOURCES["google_shopping"]])
    assert calls[0][0] == "http://da-conta:9000/v1/search" and calls[0][1]["headers"]["X-API-Token"] == "token-da-conta"


def test_ferramenta_com_token_da_conta_usa_o_endereco_global(ctx, monkeypatch, settings):
    calls = _tool(monkeypatch, settings)
    PriceSourceToken.objects.create(account=ctx.account, source="google_shopping", token="token-da-conta")
    tracker.check_variant(_variant(ctx), RULES, [sources.SOURCES["google_shopping"]])
    assert calls[0][0].startswith("http://busca.local:8010/") and calls[0][1]["headers"]["X-API-Token"] == "token-da-conta"


# ── Bright Data ────────────────────────────────────────────────────────────
def _brightdata(monkeypatch, settings, status=200, body=None):
    settings.BRIGHTDATA_API_KEY, settings.BRIGHTDATA_ZONE, settings.PRICE_DAILY_LIMITS = "chave-global", "zona_global", {}
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(status, body if body is not None else {"general": {}, "shopping": []})

    monkeypatch.setattr(sources.requests, "post", post)
    return calls


def _shop(title, price, shop="Loja X", rank=1, **extra):
    return {"title": title, "price": price, "shop": shop, "rank": rank, "global_rank": rank, **extra}


def test_bright_data_le_o_google_shopping_pela_zona(ctx, monkeypatch, settings):
    calls = _brightdata(monkeypatch, settings, body={"shopping": [
        _shop(FONE, "R$ 100,00", "Loja A", 1, link="https://loja.a/fone", shipping="Frete grátis"),
        _shop(FONE, "R$ 1.110,50", "Loja B", 2), _shop(FONE, "R$ 120", "Loja C", 3)]})
    ctx.account.price_sources = ["brightdata"]
    ctx.account.save()
    check = tracker.check_variant(_variant(ctx))
    url, kwargs = calls[0]
    assert url == "https://api.brightdata.com/request" and kwargs["headers"]["Authorization"] == "Bearer chave-global"
    assert kwargs["json"]["zone"] == "zona_global" and kwargs["json"]["format"] == "raw"
    assert "tbm=shop" in kwargs["json"]["url"] and "gl=br" in kwargs["json"]["url"] and "brd_json=1" in kwargs["json"]["url"]
    assert kwargs["json"]["url"].startswith("https://www.google.com/search?q=Fone+Bluetooth")
    assert check.source == "Bright Data" and check.searches[0]["source"] == "brightdata"
    assert sources.used_this_month(ctx.account) == 1
    offers = {o.seller: o for o in check.offers.all()}
    assert offers["Loja A"].price == D("100.00") and offers["Loja A"].url == "https://loja.a/fone" and offers["Loja A"].free_shipping
    assert offers["Loja B"].price == D("1110.50") and offers["Loja C"].price == D("120.00") and offers["Loja C"].url == ""


@pytest.mark.parametrize("text, value", [
    ("R$ 6,99", D("6.99")), ("R$\xa01.299,90", D("1299.90")), ("R$ 1.299", D("1299")), ("R$ 12", D("12")), ("R$ 6.99", D("6.99")),
    ("$6.99", None), ("€ 10,00", None), ("", None), (None, None), ("R$ 0,00", None),
])
def test_bright_data_entende_o_preco_em_texto(text, value):
    assert sources._reais(text) == value


def test_bright_data_usa_o_preco_de_agora_e_nao_o_campo_price_nem_a_parcela(monkeypatch, settings):
    """Ofertas de uma resposta real (04/11/2026): a Magalu estava a R$ 1.264,79 e o `price` dizia R$ 2.624,79."""
    _brightdata(monkeypatch, settings, body={"shopping": [
        _shop("Promoção Magalu", "R$2624.79", "Magalu", 1, price_details=[
            {"type": "Item price", "price": "R$ 1.264,79 agora"}, {"type": "Item price", "price": "R$ 136/mês x 10"}]),
        _shop("Sem promoção", "R$ 1.899,00", "Salvador Moveis", 2),
        _shop("Só a parcela", "R$ 500,00", "Loja P", 3, price_details=[{"type": "Item price", "price": "R$ 50/mês x 10"}]),
        _shop("A partir de", "R$ 1.300+", None, 4),
        _shop("Promoção de fora", "$99.00", "Fora", 5, price_details=[{"type": "Item price", "price": "$ 50 agora"}]),
    ]})
    offers = {o["title"]: o["price"] for o in sources.read_brightdata("x", "k", "z")}
    assert offers == {"Promoção Magalu": D("1264.79"), "Sem promoção": D("1899.00"), "Só a parcela": D("500.00")}


def test_bright_data_aceita_chave_e_zona_da_conta(ctx, monkeypatch, settings):
    calls = _brightdata(monkeypatch, settings)
    PriceSourceToken.objects.create(account=ctx.account, source="brightdata", token="chave-da-conta", option="zona_da_conta")
    tracker.check_variant(_variant(ctx), RULES, [sources.SOURCES["brightdata"]])
    assert calls[0][1]["headers"]["Authorization"] == "Bearer chave-da-conta" and calls[0][1]["json"]["zone"] == "zona_da_conta"


def test_bright_data_exige_chave_e_zona(ctx, settings):
    source = sources.SOURCES["brightdata"]
    settings.BRIGHTDATA_API_KEY, settings.BRIGHTDATA_ZONE = "k", ""
    assert not source.configured(ctx.account)
    settings.BRIGHTDATA_API_KEY, settings.BRIGHTDATA_ZONE = "", "z"
    assert not source.configured(ctx.account)
    PriceSourceToken.objects.create(account=ctx.account, source="brightdata", token="da-conta")
    assert source.configured(ctx.account)


@pytest.mark.parametrize("status, message", [(401, "recusou"), (429, "limite"), (502, "502")])
def test_falha_da_bright_data_nao_gasta_a_outra_busca_nem_mostra_a_chave(ctx, monkeypatch, settings, status, message):
    calls = _brightdata(monkeypatch, settings, status=status, body={})
    check = tracker.check_variant(_variant(ctx), RULES, [sources.SOURCES["brightdata"]])
    assert message in check.error and len(calls) == 1 and "chave-global" not in check.error


def test_a_conta_nunca_ve_a_chave_nem_a_zona_propria(ctx):
    PriceSourceToken.objects.create(account=ctx.account, source="brightdata", token="segredo", option="zona_secreta")
    body = ctx.client().get("/api/v1/account/settings/").content.decode()
    assert "segredo" not in body and "zona_secreta" not in body


def test_contas_antigas_passam_para_a_serpapi_na_migracao(ctx):
    from importlib import import_module

    from django.apps import apps

    from starrp.models import MarketOffer as Offer, PriceUsage

    migration = import_module("starrp.migrations.0043_split_serpapi_source")
    check = PriceCheck.all_objects.create(account=ctx.account, variant=_variant(ctx), source="Google Shopping, Open Prices",
                                          searches=[{"source": "google_shopping", "query": "q", "offers": 1, "matched": 1}])
    offer = Offer.all_objects.create(account=ctx.account, price_check=check, source="google_shopping", external_id="1", title="t",
                                     price=D("1"), match_score=D("90"))
    token = PriceSourceToken.objects.create(account=ctx.account, source="google_shopping", token="k")
    usage = PriceUsage.objects.create(account=ctx.account, month=timezone.localdate().replace(day=1), source="google_shopping", requests=3)
    ctx.account.price_sources = ["manual", "google_shopping"]
    ctx.account.save()

    migration.to_serpapi(apps, None)

    for row in (offer, token, usage, check, ctx.account):
        row.refresh_from_db()
    assert ctx.account.price_sources == ["manual", "serpapi"] and token.source == usage.source == offer.source == "serpapi"
    assert check.source == "SerpApi, Open Prices" and check.searches[0]["source"] == "serpapi"


def _metered(calls, key="serpapi"):
    def read(variant, ours, token):
        calls.append(token)
        return []

    return [sources.Source(key, "SerpApi", read, "SERPAPI_KEY", metered=True)]


def test_sem_o_modulo_a_precificacao_some_para_a_conta(ctx):
    ctx.account.extra_modules = []
    ctx.account.price_tracking_enabled = True
    ctx.account.save()
    api = ctx.client()
    assert api.get("/api/v1/price-checks/").status_code == 403
    assert api.get("/api/v1/market-offers/").status_code == 403
    assert api.get("/api/v1/competitor-prices/").status_code == 403
    assert tracker.run() == 0
    assert api.get("/api/v1/account/settings/").json()["cosmos"] == {}
    saved = api.patch("/api/v1/account/settings/", {"cosmos": {"cosmos_daily_digest": False, "price_min_margin": "50"}},
                      format="json")
    assert saved.status_code == 200
    ctx.account.refresh_from_db()
    assert ctx.account.cosmos_daily_digest and ctx.account.price_min_margin == D("20")  # só o que a conta tem


def test_limite_mensal_para_de_consultar_e_avisa(ctx, settings):
    settings.PRICE_DAILY_LIMITS = {}
    settings.SERPAPI_KEY = "global"
    ctx.account.price_monthly_requests = 2
    ctx.account.save()
    variant, calls = _variant(ctx), []
    for _ in range(2):
        assert not tracker.check_variant(variant, RULES, _metered(calls)).error
    blocked = tracker.check_variant(variant, RULES, _metered(calls))
    assert len(calls) == 2 and "limite mensal" in blocked.error
    assert sources.used_this_month(ctx.account) == 2
    with freeze_time(timezone.now() + timedelta(days=32)):  # mês novo, conta nova
        assert not tracker.check_variant(variant, RULES, _metered(calls)).error
    assert len(calls) == 3


def test_limite_zero_nao_limita(ctx, settings):
    settings.PRICE_DAILY_LIMITS = {}
    settings.SERPAPI_KEY = "global"
    ctx.account.price_monthly_requests = 0
    ctx.account.save()
    variant, calls = _variant(ctx), []
    for _ in range(3):
        tracker.check_variant(variant, RULES, _metered(calls))
    assert len(calls) == 3


def test_limite_mensal_e_de_cada_conta(ctx, settings):
    from starrp.models import Account

    settings.PRICE_DAILY_LIMITS = {}
    source = _metered([])[0]
    other = Account.objects.create(name="Outra", slug="outra-precos", price_monthly_requests=1)
    ctx.account.price_monthly_requests = 1
    ctx.account.save()
    assert sources.take_budget(source, ctx.account) == ""
    assert sources.take_budget(source, ctx.account)
    assert sources.take_budget(source, other) == ""


def test_chave_da_conta_ignora_a_global_e_o_teto_do_dia(ctx, settings):
    from django.core.cache import cache

    cache.clear()
    settings.SERPAPI_KEY = "global"
    settings.PRICE_DAILY_LIMITS = {"serpapi": 1}
    variant, calls = _variant(ctx), []
    tracker.check_variant(variant, RULES, _metered(calls))
    assert calls == ["global"]
    assert "de hoje" in tracker.check_variant(variant, RULES, _metered(calls)).error  # o teto da chave global acabou
    PriceSourceToken.objects.create(account=ctx.account, source="serpapi", token="da-conta")
    assert not tracker.check_variant(variant, RULES, _metered(calls)).error
    assert calls == ["global", "da-conta"]
    assert cache.get(f"market:budget:serpapi:{timezone.localdate()}") == 2  # não gastou o teto global


def test_chave_da_conta_liga_a_fonte_so_para_ela(ctx, settings):
    from starrp.models import Account

    settings.SERPAPI_KEY = ""
    other = Account(name="Outra", price_sources=["serpapi"])
    other.save()
    PriceSourceToken.objects.create(account=ctx.account, source="serpapi", token="da-conta")
    ctx.account.price_sources = ["serpapi"]
    assert [s.key for s in sources.active(ctx.account)] == ["manual", "serpapi"]
    assert [s.key for s in sources.active(other)] == ["manual"]  # a pesquisa da equipe é sempre ativa


def test_produto_sem_codigo_nao_gasta_consulta_do_bluesoft(ctx, settings):
    settings.BLUESOFT_COSMOS_TOKEN = "tok"
    settings.PRICE_DAILY_LIMITS = {}
    variant = ctx.product("Produto sem código", price="10", sku="SEM1")
    tracker.check_variant(variant, RULES, [sources.SOURCES["cosmos"]])
    assert sources.used_this_month(ctx.account) == 0


def test_a_conta_nunca_ve_a_chave_nem_o_limite(ctx):
    PriceSourceToken.objects.create(account=ctx.account, source="serpapi", token="segredo-da-conta")
    api = ctx.client()
    body = api.get("/api/v1/account/settings/")
    assert "segredo-da-conta" not in body.content.decode() and "price_monthly_requests" not in body.content.decode()
    saved = api.patch("/api/v1/account/settings/", {"cosmos": {"price_monthly_requests": 0, "cosmos_daily_digest": False}},
                      format="json")
    assert saved.status_code == 200
    ctx.account.refresh_from_db()
    assert ctx.account.price_monthly_requests == 500


def _admin_post_data(page):
    """O que o navegador enviaria: os valores atuais do formulário da conta e de cada inline."""
    data = {}
    form = page.context["adminform"].form
    for field in form:
        value = field.value()
        if value is not None and value is not False:
            data[field.html_name] = value
    for formset in page.context["inline_admin_formsets"]:
        data.update({f.html_name: f.value() for f in formset.formset.management_form})
        for row in formset.formset.forms:
            data.update({f.html_name: f.value() for f in row if f.value() is not None})
    return data


def test_admin_libera_o_modulo_limita_e_guarda_a_chave_mascarada(ctx, client, django_user_model):
    root = django_user_model.objects.create_superuser("root-precos", "root-precos@x.com", "x")
    client.force_login(root)
    url = f"/admin/starrp/account/{ctx.account.pk}/change/"
    ctx.account.extra_modules = []
    ctx.account.save()
    PriceSourceToken.objects.create(account=ctx.account, source="cosmos", token="segredo-1234")

    page = client.get(url)
    html = page.content.decode()
    assert "segredo-1234" not in html and "••••1234" in html
    assert 'value="pricing"' in html and "0 de 500 (0%)" in html

    data = _admin_post_data(page)
    data.update({"extra_modules": ["pricing"], "price_monthly_requests": "9"})
    saved = client.post(url, data)  # chave em branco: continua a mesma
    assert saved.status_code == 302, saved.context["adminform"].form.errors
    ctx.account.refresh_from_db()
    assert ctx.account.has_module("pricing") and ctx.account.price_monthly_requests == 9
    assert PriceSourceToken.objects.get(account=ctx.account).token == "segredo-1234"
    assert ctx.account.history.exists() and not hasattr(PriceSourceToken, "history")
    assert client.get("/admin/starrp/pricesourcetoken/").status_code == 404
