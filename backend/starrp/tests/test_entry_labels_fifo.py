"""Entrada de estoque: data de entrada no lote, saída do mais antigo (FIFO) para quem não tem
validade, validação das datas e etiquetas com o modelo padrão do sistema."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.models import LabelTemplate, LogisticsRule, StockDocument, StockLot, StockMovement, StockRule
from starrp.services import rules, stock, stock_documents
from starrp.services.barcodes import resolve_code

TODAY = timezone.localdate()


@pytest.fixture
def wh(ctx):
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    return stock.default_warehouse(ctx.store)


def _entry(ctx, warehouse, lines, days_ago=0, post=True):
    doc = StockDocument.all_objects.create(
        account=ctx.account, store=ctx.store, kind="entry", number=StockDocument.all_objects.count() + 1,
        warehouse=warehouse, effective_date=TODAY - timedelta(days=days_ago))
    for line in lines:
        doc.items.create(account=ctx.account, **line)
    return stock_documents.post(doc, ctx.admin) if post else doc


def test_sem_validade_sai_o_que_entrou_primeiro(ctx, wh):
    """Três entradas em dias diferentes; a venda leva a mais antiga inteira e só então a seguinte."""
    rice = ctx.product(name="Arroz", price="10.00")
    _entry(ctx, wh, [{"variant": rice, "quantity": Decimal("4")}], days_ago=2)
    _entry(ctx, wh, [{"variant": rice, "quantity": Decimal("5")}], days_ago=10)  # a mais velha
    _entry(ctx, wh, [{"variant": rice, "quantity": Decimal("3")}], days_ago=0)

    stock.move(rice, wh, Decimal("-7"), StockMovement.Kind.SALE, source_key="sale:1")

    left = {lot.received_at: lot.quantity for lot in StockLot.all_objects.filter(variant=rice)}
    assert left == {TODAY - timedelta(days=10): Decimal("0"), TODAY - timedelta(days=2): Decimal("2"),
                    TODAY: Decimal("3")}
    assert stock.available(rice, wh) == Decimal("5")


def test_saldo_de_antes_da_regra_sai_antes_dos_lotes_novos(ctx, wh):
    """Estoque que entrou SEM lote (antes de ligar a regra) é o mais velho: sai primeiro."""
    beans = ctx.product(name="Feijão", price="8.00")
    StockRule.all_objects.filter(pk=ctx.store.stock_rule_id).update(fifo_by_entry=False)
    _entry(ctx, wh, [{"variant": beans, "quantity": Decimal("3")}], days_ago=30)
    StockRule.all_objects.filter(pk=ctx.store.stock_rule_id).update(fifo_by_entry=True)
    _entry(ctx, wh, [{"variant": beans, "quantity": Decimal("5")}])

    movements = stock.move(beans, wh, Decimal("-4"), StockMovement.Kind.SALE, source_key="sale:2")

    assert [(m.lot_id is None, -m.quantity) for m in movements] == [(True, Decimal("3")), (False, Decimal("1"))]
    assert StockLot.all_objects.get(variant=beans).quantity == Decimal("4")


def test_reenvio_da_mesma_baixa_nao_baixa_de_novo(ctx, wh):
    oil = ctx.product(name="Óleo", price="9.00")
    _entry(ctx, wh, [{"variant": oil, "quantity": Decimal("2")}], days_ago=3)
    _entry(ctx, wh, [{"variant": oil, "quantity": Decimal("2")}])

    first = stock.move(oil, wh, Decimal("-3"), StockMovement.Kind.SALE, source_key="sale:3")
    again = stock.move(oil, wh, Decimal("-3"), StockMovement.Kind.SALE, source_key="sale:3")

    assert len(first) == 2 and [m.pk for m in again] == [m.pk for m in first]
    assert stock.available(oil, wh) == Decimal("1")


def test_regra_desligada_nao_cria_lote_para_quem_nao_tem_validade(ctx, wh):
    StockRule.all_objects.filter(pk=ctx.store.stock_rule_id).update(fifo_by_entry=False)
    salt = ctx.product(name="Sal", price="3.00")
    _entry(ctx, wh, [{"variant": salt, "quantity": Decimal("6")}])

    assert not StockLot.all_objects.filter(variant=salt).exists() and stock.available(salt, wh) == Decimal("6")


def test_transferencia_leva_a_data_de_entrada(ctx, wh):
    from starrp.models import Warehouse

    other = Warehouse.all_objects.create(account=ctx.account, store=ctx.store, name="Depósito 2")
    soap = ctx.product(name="Sabão", price="5.00")
    _entry(ctx, wh, [{"variant": soap, "quantity": Decimal("4")}], days_ago=20)
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="transfer", number=99,
                                           warehouse=wh, destination=other, effective_date=TODAY)
    doc.items.create(account=ctx.account, variant=soap, quantity=Decimal("4"))
    stock_documents.post(doc, ctx.admin)

    moved = StockLot.all_objects.get(variant=soap, warehouse=other)
    assert moved.received_at == TODAY - timedelta(days=20) and moved.quantity == Decimal("4")


@pytest.mark.parametrize("dates, code", [
    ({"expires_at": TODAY - timedelta(days=1)}, "lot_expired"),
    ({"manufactured_at": TODAY + timedelta(days=1), "expires_at": TODAY + timedelta(days=90)}, "lot_manufactured_future"),
    ({"manufactured_at": TODAY - timedelta(days=1), "expires_at": TODAY - timedelta(days=5)}, "lot_expired"),
])
def test_datas_erradas_do_lote_nao_entram(ctx, wh, dates, code):
    milk = ctx.product(name="Leite", price="6.00", track_lots=True)
    doc = _entry(ctx, wh, [{"variant": milk, "quantity": Decimal("2"), "lot_number": "A1", **dates}], post=False)

    with pytest.raises(BusinessError) as error:
        stock_documents.post(doc, ctx.admin)
    assert error.value.detail.code == code and stock.available(milk, wh) == 0


def test_rascunho_com_validade_vencida_e_recusado_na_api(ctx, wh):
    milk = ctx.product(name="Leite", price="6.00", track_lots=True)
    response = ctx.client().post("/api/v1/stock/documents/", {
        "kind": "entry", "warehouse": str(wh.pk), "effective_date": str(TODAY),
        "items": [{"variant": str(milk.pk), "quantity": "2", "lot_number": "A1",
                   "expires_at": str(TODAY - timedelta(days=3))}]}, format="json")

    assert response.status_code == 400 and "validade" in str(response.json())


def test_etiqueta_da_entrada_usa_o_modelo_padrao_e_mostra_a_data_de_entrada(ctx, wh):
    coffee = ctx.product(name="Café", price="20.00")
    doc = _entry(ctx, wh, [{"variant": coffee, "quantity": Decimal("2")}], days_ago=1)
    api = ctx.client()

    options = api.get(f"/api/v1/stock/documents/{doc.pk}/label-options/").json()
    html = api.get(f"/api/v1/stock/documents/{doc.pk}/labels/").content.decode()
    lot = StockLot.all_objects.get(variant=coffee)

    assert options["lots"] == 1 and options["suggested"]
    assert "<span>Entrada</span><b>" + (TODAY - timedelta(days=1)).strftime("%d/%m/%Y") in html and lot.code in html


def test_etiqueta_de_lote_so_depois_de_confirmar_e_cancelado_nao_imprime(ctx, wh):
    coffee = ctx.product(name="Café", price="20.00")
    draft = _entry(ctx, wh, [{"variant": coffee, "quantity": Decimal("2")}], post=False)
    api = ctx.client()
    lot_template = api.get("/api/v1/stock/label-templates/", {"subject": "lot", "is_default": "true"}).json()["results"][0]

    product_ok = api.get(f"/api/v1/stock/documents/{draft.pk}/labels/")  # rascunho: o padrão é o de produto
    lot_draft = api.get(f"/api/v1/stock/documents/{draft.pk}/labels/", {"template": lot_template["id"]})
    posted = stock_documents.post(draft, ctx.admin)
    stock_documents.cancel(posted, ctx.admin)
    cancelled = api.get(f"/api/v1/stock/documents/{draft.pk}/labels/")

    assert product_ok.status_code == 200 and "Entrada " in product_ok.content.decode()
    assert lot_draft.status_code == 422 and "no_lots" in str(lot_draft.json())
    assert cancelled.status_code == 422 and "labels_not_available" in str(cancelled.json())


def test_impressao_avulsa_sem_modelo_usa_o_padrao_do_tipo(ctx, wh):
    coffee = ctx.product(name="Café", price="20.00")
    _entry(ctx, wh, [{"variant": coffee, "quantity": Decimal("1")}])
    lot = StockLot.all_objects.get(variant=coffee)

    response = ctx.client().post("/api/v1/stock/labels/print/", {"subject": "lot", "items": [{"id": str(lot.pk)}]},
                                 format="json")
    assert response.status_code == 200 and lot.code in response.content.decode()


def test_leitor_acha_o_produto_pela_etiqueta_do_lote(ctx, wh):
    tea = ctx.product(name="Chá", price="7.00")
    _entry(ctx, wh, [{"variant": tea, "quantity": Decimal("1")}])
    lot = StockLot.all_objects.get(variant=tea)

    found = resolve_code(ctx.account.pk, lot.code.lower())
    assert found.variant == tea and found.lot == lot


def test_regra_de_logistica_ja_nasce_com_os_modelos_padrao_de_cada_etapa(ctx):
    rule = rules.default(LogisticsRule, ctx.account.pk)
    new = LogisticsRule.all_objects.create(account=ctx.account, name="Outra")

    for r in (rule, new):
        r.refresh_from_db()
        assert r.entry_labels == r.conference_labels == "auto"
        assert (r.entry_lot_label.subject, r.entry_product_label.subject, r.conference_label.subject) == (
            "lot", "product", "volume")
        assert r.entry_lot_label.is_default and r.entry_product_label.is_default


def test_etapa_usa_o_modelo_da_regra_e_conferencia_sem_caixas_nao_imprime(ctx, wh):
    coffee = ctx.product(name="Café", price="20.00")
    doc = _entry(ctx, wh, [{"variant": coffee, "quantity": Decimal("2")}])
    rule = rules.of_store("logistics_rule", doc.store_id, ctx.account.pk)
    chosen = LabelTemplate.all_objects.get(account=ctx.account, name="Entrada de estoque 50×30 mm")
    LogisticsRule.all_objects.filter(pk=rule.pk).update(entry_lot_label=chosen, conference_labels="ask")
    api = ctx.client()

    options = api.get(f"/api/v1/stock/documents/{doc.pk}/label-options/").json()
    entry = api.get(f"/api/v1/stock/documents/{doc.pk}/labels/", {"stage": "entry"})
    conference = api.get(f"/api/v1/stock/documents/{doc.pk}/labels/", {"stage": "conference"})

    assert options["entry"] == {"mode": "auto", "template": str(chosen.pk), "template_name": chosen.name}
    assert options["suggested"] == str(chosen.pk) and options["conference"]["mode"] == "ask"
    assert entry.status_code == 200 and "<span>Quantidade</span>" in entry.content.decode()
    assert conference.status_code == 204  # nenhum produto da entrada tem caixas (volumes)


def test_regra_recusa_modelo_de_outro_tipo(ctx):
    rule = rules.default(LogisticsRule, ctx.account.pk)
    bin_template = LabelTemplate.all_objects.filter(account=ctx.account, subject="bin").first()

    response = ctx.client().patch(f"/api/v1/logistics/rules/{rule.pk}/", {"entry_lot_label": str(bin_template.pk)},
                                  format="json")
    assert response.status_code == 400 and "entry_lot_label" in response.json()["error"]["message"]
