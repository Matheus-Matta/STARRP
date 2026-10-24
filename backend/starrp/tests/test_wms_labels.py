"""WMS simples (endereços, guarda, separação, movimentação, inventário) e etiquetas."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.models import (
    BinBalance, DiscountTable, LabelTemplate, ProductBarcode, Promotion, StockDocument, StockMovement, StorageBin,
)
from starrp.services import stock, stock_documents, wms

from .nfe_fixture import UNIT_EAN


@pytest.fixture
def wh(ctx):
    """Depósito da loja com WMS ligado e endereços A-01-1, A-01-2, B-01-1, B-01-2."""
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    warehouse = stock.default_warehouse(ctx.store)
    warehouse.uses_bins = True
    warehouse.save()
    response = ctx.client().post("/api/v1/stock/bins/generate/", {
        "warehouse": str(warehouse.pk), "aisles": ["A", "B"], "racks": 1, "levels": 2}, format="json")
    assert response.json()["created"] == 4
    return warehouse


def _bin(warehouse, code):
    return StorageBin.all_objects.get(warehouse=warehouse, code=code)


def _doc(ctx, warehouse, kind, lines):
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind=kind, number=StockDocument.all_objects.count() + 1,
                                           warehouse=warehouse, effective_date=timezone.localdate())
    for line in lines:
        doc.items.create(account=ctx.account, **line)
    return stock_documents.post(doc, ctx.admin)


def _bins_sum(warehouse, product):
    return wms.bin_total(warehouse, product)


def test_guarda_no_endereco_e_venda_tira_pela_rota(ctx, wh):
    """Entrada em dois endereços; a venda (sem endereço) tira pela ordem do caminho, e a soma bate."""
    product = ctx.product(price="10.00")
    _doc(ctx, wh, "entry", [
        {"variant": product, "quantity": Decimal("3"), "bin": _bin(wh, "B-01-1")},
        {"variant": product, "quantity": Decimal("5"), "bin": _bin(wh, "A-01-1")},
    ])

    stock.move(product, wh, Decimal("-6"), StockMovement.Kind.SALE)

    remaining = {b.bin.code: b.quantity for b in BinBalance.all_objects.filter(variant=product, quantity__gt=0)}
    assert remaining == {"B-01-1": Decimal("2.000")}  # A-01-1 vem primeiro na rota e esvaziou
    assert _bins_sum(wh, product) == stock.available(product, wh) == Decimal("2")


def test_movimentacao_entre_enderecos_nao_muda_o_saldo_do_deposito(ctx, wh):
    product = ctx.product(price="10.00")
    _doc(ctx, wh, "entry", [{"variant": product, "quantity": Decimal("4"), "bin": _bin(wh, "A-01-1")}])

    _doc(ctx, wh, "relocation", [{"variant": product, "quantity": Decimal("4"), "bin": _bin(wh, "A-01-1"),
                                  "destination_bin": _bin(wh, "B-01-2")}])

    assert BinBalance.all_objects.get(variant=product, bin=_bin(wh, "B-01-2")).quantity == Decimal("4")
    assert BinBalance.all_objects.get(variant=product, bin=_bin(wh, "A-01-1")).quantity == Decimal("0")
    assert stock.available(product, wh) == Decimal("4")


def test_lista_de_separacao_segue_validade_e_caminho(ctx, wh):
    """Com lotes, separa primeiro o que vence antes, mesmo estando mais longe no caminho."""
    product = ctx.product(name="Iogurte", price="5.00", track_lots=True)
    today = timezone.localdate()
    _doc(ctx, wh, "entry", [
        {"variant": product, "quantity": Decimal("5"), "bin": _bin(wh, "A-01-1"), "lot_number": "L-LONGE",
         "expires_at": today + timedelta(days=30)},
        {"variant": product, "quantity": Decimal("5"), "bin": _bin(wh, "B-01-2"), "lot_number": "L-PERTO",
         "expires_at": today + timedelta(days=3)},
    ])
    draft = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="exit", number=99,
                                             warehouse=wh, effective_date=today)
    draft.items.create(account=ctx.account, variant=product, quantity=Decimal("7"))

    picking = ctx.client().get(f"/api/v1/stock/documents/{draft.pk}/picking-list/").json()

    assert [(line["bin"], line["lot"], Decimal(line["quantity"])) for line in picking["lines"]] == [
        ("A-01-1", "L-LONGE", Decimal("2.000")), ("B-01-2", "L-PERTO", Decimal("5.000"))]
    # a lista sai na ordem do caminho; quem venceu a disputa foi o lote que vence antes (todo o L-PERTO)
    assert picking["shortages"] == []


def test_inventario_por_endereco_e_estorno_voltam_ao_mesmo_endereco(ctx, wh):
    product = ctx.product(price="10.00")
    entry = _doc(ctx, wh, "entry", [{"variant": product, "quantity": Decimal("10"), "bin": _bin(wh, "A-01-2")}])

    _doc(ctx, wh, "inventory", [{"variant": product, "quantity": Decimal("8"), "bin": _bin(wh, "A-01-2")}])
    assert BinBalance.all_objects.get(variant=product, bin=_bin(wh, "A-01-2")).quantity == Decimal("8")

    stock_documents.cancel(entry, ctx.admin)
    assert BinBalance.all_objects.get(variant=product, bin=_bin(wh, "A-01-2")).quantity == Decimal("-2")
    assert _bins_sum(wh, product) == stock.available(product, wh)


def test_etiqueta_de_gondola_mostra_preco_promocional_e_codigo(ctx):
    product = ctx.product(name="Refrigerante", price="6.00")
    ProductBarcode.all_objects.create(account=ctx.account, variant=product, code=UNIT_EAN, is_primary=True)
    table = DiscountTable.all_objects.create(account=ctx.account, name="Semana")
    Promotion.all_objects.create(account=ctx.account, table=table, name="Tudo", target="all", kind="fixed",
                                 value=Decimal("4.99"))
    template = LabelTemplate.all_objects.create(account=ctx.account, name="Gôndola", subject="product")

    response = ctx.client().post("/api/v1/stock/labels/print/", {
        "template": str(template.pk), "items": [{"id": str(product.pk), "copies": 3}]}, format="json")

    html = response.content.decode()
    assert response.status_code == 200 and response["Content-Type"].startswith("text/html")
    assert html.count('class="label"') == 3
    assert "R$ 4,99" in html and "<s>R$ 6,00</s>" in html
    assert "<svg" in html and "@page" in html


def test_etiqueta_de_endereco(ctx, wh):
    template = LabelTemplate.all_objects.create(account=ctx.account, name="Endereço", subject="bin", code_type="qr")
    bin_ = _bin(wh, "B-01-2")

    html = ctx.client().post("/api/v1/stock/labels/print/", {
        "template": str(template.pk), "items": [{"id": str(bin_.pk)}]}, format="json").content.decode()

    assert ">B-01-2<" in html and "<svg" in html
