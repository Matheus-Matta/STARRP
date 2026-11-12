"""Cosmos no estoque: recomendações de endereço, aceite por rascunho, avisos de entrega e o que cada um pode ver."""
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.utils import timezone

from starrp.models import BinBalance, CosmosFinding, Sale, SaleItem, StockAdvice, StockDocument, StorageBin
from starrp.services import numbering, stock, stock_documents
from starrp.services.cosmos import slotting, supervision

URL = "/api/v1/stock/advices/"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


@pytest.fixture
def wh(ctx):
    """20 endereços de guarda: A-01-1 ... D-05-1, nessa ordem na rota."""
    ctx.account.extra_modules = ["stock", "cosmos"]
    ctx.account.save()
    warehouse = stock.default_warehouse(ctx.store)
    warehouse.uses_bins = True
    warehouse.save()
    created = ctx.client().post("/api/v1/stock/bins/generate/", {"warehouse": str(warehouse.pk), "aisles": ["A", "B", "C", "D"], "racks": 5, "levels": 1},
                                format="json")
    assert created.json()["created"] == 20
    return warehouse


def _bin(warehouse, code):
    return StorageBin.all_objects.get(warehouse=warehouse, code=code)


def _put(ctx, warehouse, variant, code, quantity="10", days=0, **item):
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="entry", number=numbering.next_number(ctx.store, "stock_document"),
                                           warehouse=warehouse, effective_date=timezone.localdate())
    doc.items.create(account=ctx.account, variant=variant, quantity=D(quantity), bin=_bin(warehouse, code), **item)
    stock_documents.post(doc, ctx.admin)
    if days:
        BinBalance.all_objects.filter(variant=variant, bin=_bin(warehouse, code)).update(updated_at=timezone.now() - timedelta(days=days))


def _sell(ctx, *variants, times=1, store=None, days=1):
    store = store or ctx.store
    for _ in range(times):
        sale = Sale.all_objects.create(account=ctx.account, store=store, number=Sale.all_objects.filter(store=store).count() + 1,
                                       status="completed", completed_at=timezone.now() - timedelta(days=days))
        for position, variant in enumerate(variants, start=1):
            SaleItem.all_objects.create(account=ctx.account, sale=sale, position=position, variant=variant, description=variant.display_name)


def _kinds(found):
    return [item.kind for item in found]


def _pair(ctx, wh, first="A-01-1", second="D-05-1"):
    """Caneta e Caderno saem juntos 8 vezes em 30 vendas; Caneta sai mais."""
    pen, book, other = ctx.product("Caneta", sku="CAN"), ctx.product("Caderno", sku="CAD"), ctx.product("Borracha", sku="BOR")
    _put(ctx, wh, pen, first)
    _put(ctx, wh, book, second)
    _sell(ctx, pen, book, times=8)
    _sell(ctx, pen, times=2)
    _sell(ctx, other, times=20)
    return pen, book


# ── juntos ─────────────────────────────────────────────────────────────────
def test_o_que_sai_junto_e_esta_longe_vira_recomendacao(ctx, wh):
    pen, book = _pair(ctx, wh)
    found = [item for item in slotting.recommend(wh) if item.kind == "together"]
    assert len(found) == 1
    item = found[0]
    assert "8 vezes" in item.detail and "19 endereços" in item.detail and "A-01-1" in item.detail and "D-05-1" in item.detail
    move = item.moves[0]
    assert move["variant"] == str(book.pk) and move["from_code"] == "D-05-1"  # mexe em quem sai menos
    assert move["to_code"] == "A-02-1" and D(move["quantity"]) == D("10")  # o vazio mais perto de quem fica


def test_juntos_por_acaso_nao_recomenda(ctx, wh):
    """Os dois saem em quase toda venda: sair junto não diz nada."""
    pen, book = ctx.product("Caneta", sku="CAN"), ctx.product("Caderno", sku="CAD")
    _put(ctx, wh, pen, "A-01-1")
    _put(ctx, wh, book, "D-05-1")
    _sell(ctx, pen, book, times=25)
    assert "together" not in _kinds(slotting.recommend(wh))


def test_ja_perto_nao_recomenda(ctx, wh):
    _pair(ctx, wh, "A-01-1", "A-03-1")
    assert "together" not in _kinds(slotting.recommend(wh))


def test_poucas_vendas_nao_viram_padrao(ctx, wh):
    pen, book = ctx.product("Caneta", sku="CAN"), ctx.product("Caderno", sku="CAD")
    _put(ctx, wh, pen, "A-01-1")
    _put(ctx, wh, book, "D-05-1")
    _sell(ctx, pen, book, times=19)
    assert slotting.recommend(wh) == []


def test_venda_antiga_ou_de_outra_filial_nao_conta(ctx, wh):
    from starrp.models import Store

    pen, book = ctx.product("Caneta", sku="CAN"), ctx.product("Caderno", sku="CAD")
    _put(ctx, wh, pen, "A-01-1")
    _put(ctx, wh, book, "D-05-1")
    second = Store.all_objects.create(account=ctx.account, name="Filial 2")
    _sell(ctx, pen, book, times=30, days=120)
    _sell(ctx, pen, book, times=30, store=second)
    assert slotting.recommend(wh) == []


def test_sem_endereco_livre_orienta_mas_nao_oferece_movimentacao(ctx, wh):
    pen, book = _pair(ctx, wh)
    for index, item in enumerate(StorageBin.all_objects.filter(warehouse=wh).exclude(code__in=["A-01-1", "D-05-1"])):
        _put(ctx, wh, ctx.product(f"Enche {index}", sku=f"E{index}"), item.code)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    assert advice.moves == [] and "libere" in advice.detail
    response = ctx.client().post(f"{URL}{advice.pk}/apply/")
    assert response.status_code == 422


# ── os outros tipos ────────────────────────────────────────────────────────
def test_o_que_mais_sai_no_fim_da_rota_vem_para_a_frente(ctx, wh):
    fast = ctx.product("Campeão", sku="CMP")
    _put(ctx, wh, fast, "D-05-1")
    _sell(ctx, fast, times=25)
    item = next(item for item in slotting.recommend(wh) if item.kind == "fast")
    assert "25 vendas" in item.detail and item.moves[0]["to_code"] == "A-01-1"


def test_doca_parada_vai_para_um_endereco(ctx, wh):
    dock = StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="DOCA", kind="receiving", sequence=0)
    variant = ctx.product("Chegou", sku="CHE")
    _put(ctx, wh, variant, "DOCA", days=4)
    item = slotting.recommend(wh)[0]
    assert item.kind == "dock" and "4 dias" in item.title and item.moves[0]["from_code"] == dock.code and item.moves[0]["to_code"] == "A-01-1"


def test_doca_recente_nao_avisa(ctx, wh):
    StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="DOCA", kind="receiving", sequence=0)
    _put(ctx, wh, ctx.product("Chegou", sku="CHE"), "DOCA")
    assert slotting.recommend(wh) == []


def test_espalhado_junta_no_endereco_maior(ctx, wh):
    variant = ctx.product("Espalhado", sku="ESP")
    _put(ctx, wh, variant, "A-01-1", "2")
    _put(ctx, wh, variant, "B-01-1", "9")
    _put(ctx, wh, variant, "C-01-1", "3")
    item = next(item for item in slotting.recommend(wh) if item.kind == "scattered")
    assert {move["from_code"] for move in item.moves} == {"A-01-1", "C-01-1"} and {move["to_code"] for move in item.moves} == {"B-01-1"}


def test_espalhado_nao_mistura_validades(ctx, wh):
    variant = ctx.product("Iogurte", sku="IOG")
    variant.product.track_lots = True
    variant.product.save()
    expires = timezone.localdate() + timedelta(days=30)
    for index, code in enumerate(("A-01-1", "B-01-1", "C-01-1")):
        _put(ctx, wh, variant, code, lot_number=f"L{index}", expires_at=expires)
    assert "scattered" not in _kinds(slotting.recommend(wh))


def test_o_que_nao_sai_libera_a_frente(ctx, wh):
    idle, seller = ctx.product("Encalhe", sku="ENC"), ctx.product("Vende", sku="VEN")
    _put(ctx, wh, idle, "A-01-1", days=40)
    _put(ctx, wh, seller, "A-05-1")
    _sell(ctx, seller, times=25)
    item = next(item for item in slotting.recommend(wh) if item.kind == "idle")
    assert item.moves[0]["variant"] == str(idle.pk) and _bin(wh, item.moves[0]["to_code"]).sequence > _bin(wh, "B-05-1").sequence


def test_o_mesmo_endereco_livre_nao_e_oferecido_duas_vezes(ctx, wh):
    StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="DOCA", kind="receiving", sequence=0)
    _put(ctx, wh, ctx.product("Um", sku="UM"), "DOCA", days=4)
    _put(ctx, wh, ctx.product("Dois", sku="DOIS"), "DOCA", days=4)
    targets = [item.moves[0]["to_code"] for item in slotting.recommend(wh) if item.kind == "dock"]
    assert len(targets) == 2 and len(set(targets)) == 2


# ── aceitar e recusar ──────────────────────────────────────────────────────
def test_aceitar_cria_rascunho_e_o_estoque_so_muda_ao_confirmar(ctx, wh):
    _, book = _pair(ctx, wh)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    body = ctx.client().post(f"{URL}{advice.pk}/apply/").json()
    assert body["status"] == "applied" and body["document"]
    document = StockDocument.all_objects.get(pk=body["document"])
    assert document.kind == "relocation" and document.status == "draft" and document.created_by == ctx.admin
    assert BinBalance.all_objects.get(variant=book, bin=_bin(wh, "D-05-1")).quantity == D("10")  # nada mudou ainda

    before = stock.available(book, wh)
    stock_documents.post(document, ctx.admin)
    assert BinBalance.all_objects.get(variant=book, bin=_bin(wh, "A-02-1")).quantity == D("10")
    assert stock.available(book, wh) == before
    assert ctx.client().post(f"{URL}{advice.pk}/apply/").status_code == 409


def test_aceitar_usa_o_saldo_de_agora_e_barra_endereco_ocupado(ctx, wh):
    _, book = _pair(ctx, wh)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    _put(ctx, wh, ctx.product("Intruso", sku="INT"), "A-02-1")
    assert ctx.client().post(f"{URL}{advice.pk}/apply/").status_code == 409

    BinBalance.all_objects.filter(bin=_bin(wh, "A-02-1")).update(quantity=0)
    BinBalance.all_objects.filter(variant=book).update(quantity=D("4"))
    body = ctx.client().post(f"{URL}{advice.pk}/apply/").json()
    assert StockDocument.all_objects.get(pk=body["document"]).items.get().quantity == D("4")


def test_movimentacao_aberta_nao_recomenda_de_novo(ctx, wh):
    _pair(ctx, wh)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    slotting.apply(advice, ctx.admin)
    assert "together" not in _kinds(slotting.recommend(wh))


def test_recusada_nao_volta_ate_passar_o_prazo(ctx, wh):
    _pair(ctx, wh)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    assert ctx.client().post(f"{URL}{advice.pk}/dismiss/").json()["status"] == "dismissed"
    slotting.analyze(ctx.account)
    advice.refresh_from_db()
    assert advice.status == "dismissed"

    StockAdvice.all_objects.filter(pk=advice.pk).update(decided_at=timezone.now() - timedelta(days=61))
    slotting.analyze(ctx.account)
    advice.refresh_from_db()
    assert advice.status == "open"


def test_o_que_deixou_de_valer_sai_da_lista(ctx, wh):
    _, book = _pair(ctx, wh)
    slotting.analyze(ctx.account)
    BinBalance.all_objects.filter(variant=book).update(bin=_bin(wh, "A-02-1"))
    slotting.analyze(ctx.account)
    assert StockAdvice.all_objects.get(kind="together").status == "expired"


# ── quem vê ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("setup", ["sem_cosmos", "sem_estoque", "interruptor", "desligada_no_admin"])
def test_sem_acesso_quando_falta_modulo_ou_esta_desligado(ctx, wh, setup):
    if setup == "sem_cosmos":
        ctx.account.extra_modules = ["stock"]
    elif setup == "sem_estoque":
        ctx.account.extra_modules = ["cosmos"]
    elif setup == "interruptor":
        ctx.account.cosmos_stock_advice = False
    else:
        ctx.account.cosmos_enabled = False
    ctx.account.save()
    _pair(ctx, wh)
    assert slotting.analyze(ctx.account) == 0 and not StockAdvice.all_objects.exists()
    assert ctx.client().get(URL).status_code == 403
    assert ctx.client().post(f"{URL}run/").status_code == 403
    assert "cosmos_stock" not in ctx.account.session_modules()


def test_a_tela_aparece_com_os_dois_modulos(ctx, wh):
    assert "cosmos_stock" in ctx.account.session_modules()
    assert "cosmos_stock" in ctx.client().get("/api/v1/me/").json()["account"]["modules"]


def test_quem_so_ve_o_estoque_nao_decide(ctx, wh):
    _pair(ctx, wh)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    viewer = ctx.user("olha", "comprador")
    api = ctx.client(viewer)
    assert api.get(URL).status_code == 200
    for path in (f"{URL}{advice.pk}/apply/", f"{URL}{advice.pk}/dismiss/", f"{URL}run/"):
        assert api.post(path).status_code == 403


def test_uma_conta_nao_ve_nem_mistura_a_outra(ctx, other, wh):
    other.account.extra_modules = ["stock", "cosmos"]
    other.account.save()
    _pair(ctx, wh)
    slotting.analyze(ctx.account)
    advice = StockAdvice.all_objects.get(kind="together")
    api = other.client()
    assert api.get(URL).json()["results"] == []
    assert api.get(f"{URL}{advice.pk}/").status_code == 404
    assert api.post(f"{URL}{advice.pk}/apply/").status_code == 404


def test_a_cosmos_le_as_recomendacoes_pela_api_com_o_acesso_do_usuario(ctx, wh):
    from starrp.services.cosmos import bridge

    _pair(ctx, wh)
    slotting.analyze(ctx.account)
    found = bridge.actor_for(ctx.admin, str(ctx.store.pk))
    reply = bridge.call(found, "GET", "stock/advices/", {"status": "open"})
    assert reply.status == 200 and "saem juntos" in str(reply.data)
    from starrp.services.cosmos import prompts

    assert "stock/advices" in prompts.system_prompt(found)


# ── alertas ────────────────────────────────────────────────────────────────
def test_alerta_unico_por_filial_e_fecha_sem_pendencia(ctx, wh):
    _pair(ctx, wh)
    slotting.analyze(ctx.account)
    rows = CosmosFinding.all_objects.filter(account=ctx.account, rule="organizacao_estoque")
    assert rows.count() == 1 and "recomenda" in rows.get().title and rows.get().endpoint == "stock/advices"
    for advice in StockAdvice.all_objects.filter(status="open"):
        slotting.dismiss(advice, ctx.admin)
    assert not rows.filter(status="open").exists()


def _delivery(ctx, stage, moment, days, number=None):
    from starrp.models import Customer, CustomerAddress

    customer = Customer.all_objects.create(account=ctx.account, name=f"Cliente {stage}")
    address = CustomerAddress.all_objects.create(account=ctx.account, customer=customer, zip_code="01001000", street="Rua", number="1",
                                                 district="Centro", city="São Paulo", state="SP")
    return Sale.all_objects.create(account=ctx.account, store=ctx.store, number=number or Sale.all_objects.count() + 1, status="completed",
                                   shipping_address=address, fulfillment_status=stage,
                                   **{"completed_at": timezone.now() - timedelta(days=days), moment: timezone.now() - timedelta(days=days)})


def test_avisa_de_entrega_parada_e_fecha_quando_anda(ctx, wh):
    sale = _delivery(ctx, "pending", "completed_at", 3)
    _delivery(ctx, "ready", "ready_at", 2)
    _delivery(ctx, "shipped", "shipped_at", 1)  # em rota há pouco: tudo certo
    supervision.sweep(ctx.account)
    rows = CosmosFinding.all_objects.filter(account=ctx.account, rule="entrega_parada", status="open")
    titles = sorted(row.title for row in rows)
    assert len(titles) == 2 and "aguardando separação" in titles[0] and "separadas" in titles[1]
    assert str(sale.number) in rows.get(title=titles[0]).detail

    supervision.sweep(ctx.account)
    assert rows.all().count() == 2  # não repete
    Sale.all_objects.filter(fulfillment_status__in=["pending", "ready"]).update(fulfillment_status="delivered")
    supervision.sweep(ctx.account)
    assert rows.all().count() == 0


def test_avisa_de_recebimento_sem_confirmar(ctx, wh):
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="entry", number=99, warehouse=wh, effective_date=timezone.localdate())
    StockDocument.all_objects.filter(pk=doc.pk).update(created_at=timezone.now() - timedelta(days=4))
    supervision.sweep(ctx.account)
    assert "99" in CosmosFinding.all_objects.get(rule="recebimento_parado").detail


def test_varredura_analisa_uma_vez_por_dia(ctx, wh, monkeypatch):
    calls = []
    monkeypatch.setattr(slotting, "analyze", lambda account: calls.append(account) or 0)
    supervision.sweep(ctx.account)
    supervision.sweep(ctx.account)
    assert len(calls) == 1


@pytest.mark.parametrize("setup", ["sem_cosmos", "interruptor"])
def test_sem_a_funcao_nao_avisa_de_entrega(ctx, wh, setup):
    if setup == "sem_cosmos":
        ctx.account.extra_modules = ["stock"]
    else:
        ctx.account.cosmos_stock_advice = False
    ctx.account.save()
    _delivery(ctx, "pending", "completed_at", 3)
    supervision.sweep(ctx.account)
    assert not CosmosFinding.all_objects.filter(rule="entrega_parada").exists()


# ── sem o módulo a Cosmos não trabalha ─────────────────────────────────────
def test_varredura_agendada_pula_conta_sem_a_cosmos(ctx, other, monkeypatch):
    """A tarefa agendada passa por todas as contas: só quem tem o módulo pode receber alerta."""
    ctx.account.extra_modules, other.account.extra_modules = ["cosmos"], []
    ctx.account.save()
    other.account.save()
    seen = []
    monkeypatch.setattr(supervision, "_negative_stock", lambda account: seen.append(account.pk) or 0)
    supervision.sweep()
    assert ctx.account.pk in seen and other.account.pk not in seen


def test_conferencia_ao_gravar_nao_abre_alerta_sem_a_cosmos(ctx):
    from starrp.models import Customer

    ctx.account.extra_modules = []
    ctx.account.save()
    customer = Customer.all_objects.create(account=ctx.account, name="Sem documento", document="11111111111")
    assert supervision.check_instance(customer) == []
    assert not CosmosFinding.all_objects.filter(account=ctx.account).exists()
