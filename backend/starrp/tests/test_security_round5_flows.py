"""Rodada 5b: confirmacoes de ponta a ponta."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from starrp.models import (
    Commission, FinancialTitle, LogisticsRule, ProductBarcode, Sale, StockDocument, StockMovement, Store,
    StorageBin, Supplier, Warehouse,
)
from starrp.services import finance, stock

from .nfe_fixture import UNIT_EAN, nfe_xml
from .test_security_round5_finance import A, D, _mods, bank, sale, stocked  # noqa: F401


def _nfe(ctx):
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj="11222333000181")
    LogisticsRule.all_objects.filter(pk=ctx.store.logistics_rule_id).update(allow_manual_conference=True)
    soda = ctx.product(name="Refrigerante Lata", sku="REFRI", price="5.00")
    ProductBarcode.all_objects.create(account=ctx.account, variant=soda, code=UNIT_EAN)
    ctx.product(name="Iogurte Natural", sku="IOG", price="6.00", track_lots=True)
    api = ctx.client()
    r = api.post(f"{A}/inbound-nfe/import/", {"file": SimpleUploadedFile("n.xml", nfe_xml(), content_type="text/xml")},
                 format="multipart")
    assert r.status_code == 201, r.json()
    nfe = r.json()
    for it in api.get(f"{A}/inbound-nfe/items/?nfe={nfe['id']}").json()["results"]:
        if not it["variant"]:
            api.post(f"{A}/inbound-nfe/items/{it['id']}/ignore/", {"reason": "nao vai"}, format="json")
    r = api.post(f"{A}/inbound-nfe/{nfe['id']}/receive/", {"post": True}, format="json")
    assert r.status_code == 201, r.json()
    return api, soda


def test_m01_nfe_real_conta_duas_vezes_na_dre(ctx):
    """Compra 24 un. por NF-e (titulo 82,80), nada vendido: o resultado do mes nao pode cair pelo estoque comprado."""
    api, soda = _nfe(ctx)
    d = api.get(f"{A}/reports/dre/?date_from=2026-10-01&date_to=2026-12-31").json()
    sup = [e for e in d["expenses"] if "fornec" in e["category"].lower()]
    assert not sup, (d["expenses"], d["operating_result"])


def test_m01b_nfe_e_venda(ctx):
    api, soda = _nfe(ctx)
    sale(ctx, api, [(soda, "24")])
    d = api.get(f"{A}/reports/dre/?date_from=2026-10-01&date_to=2026-12-31").json()
    assert D(d["operating_result"]) == D(d["gross_profit"]), (d["gross_profit"], d["expenses"], d["operating_result"])


def test_m02_custo_no_documento_da_nfe(ctx):
    _nfe(ctx)
    doc = StockDocument.all_objects.get()
    r = ctx.client(ctx.user("log", "logistics_lead")).get(f"{A}/stock/documents/{doc.pk}/")
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert not D(it.get("total_cost") or 0), it


def test_m03_liga_wms_e_vende(ctx):
    wh = stock.default_warehouse(ctx.store)
    v = stocked(ctx, "X", "10.00", "5.00")
    StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="A")
    ctx.client(ctx.user("est", "stockist")).patch(f"{A}/stock/warehouses/{wh.pk}/", {"uses_bins": True}, format="json")
    sale(ctx, ctx.client(), [(v, "1")])


@pytest.mark.parametrize("how", ["patch", "off"])
def test_m04_endereco_mexido_trava_venda(ctx, how):
    wh = stock.default_warehouse(ctx.store)
    Warehouse.all_objects.filter(pk=wh.pk).update(uses_bins=True)
    wh.refresh_from_db()
    b = StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="A")
    wh2 = Warehouse.all_objects.create(account=ctx.account, store=ctx.store, name="D2", uses_bins=True)
    v = ctx.product(name="X", price="10")
    stock.move(v, wh, D(10), StockMovement.Kind.PURCHASE, unit_cost=D(1), bin=b)
    body = {"warehouse": str(wh2.pk)} if how == "patch" else {"is_active": False}
    ctx.client(ctx.user("est", "stockist")).patch(f"{A}/stock/bins/{b.pk}/", body, format="json")
    sale(ctx, ctx.client(), [(v, "1")])


def test_m05_auditoria_real_do_ti(ctx):
    """O TI (sem finance.view) le pela auditoria o que o financeiro gravou."""
    api = ctx.client()
    b = bank(ctx)
    r = api.patch(f"{A}/finance/accounts/{b.pk}/", {"opening_balance": "987654.32"}, format="json")
    assert r.status_code == 200, r.json()
    ti = ctx.client(ctx.user("ti", "it"), store=None)
    assert ti.get(f"{A}/finance/accounts/").status_code == 403
    seen = "".join(ti.get(f"{A}/audit-logs/").content.decode() for _ in range(1))
    assert "987654.32" not in seen


def test_m05b_auditoria_do_ti_custo_real(ctx):
    v = stocked(ctx)
    s = Supplier.all_objects.create(account=ctx.account, name="F")
    api = ctx.client()
    r = api.post(f"{A}/catalog/supplier-products/", {"supplier": str(s.pk), "variant": str(v.pk), "supplier_code": "1"}, format="json")
    assert r.status_code in (201, 404), r.json()


def test_m06_json_profundo_no_link_publico(ctx):
    v = ctx.product(name="X", price="10", track_stock=False)
    s = sale(ctx, ctx.client(), [(v, "1")])
    from starrp.services import reviews
    link = reviews.generate_link(s, "order", ctx.admin)
    from rest_framework.test import APIClient
    r = APIClient().post(f"{A}/public/reviews/{link.token}/", {"data": "[" * 100000}, format="multipart")
    assert r.status_code < 500


def test_m07_comissao_devolucao_fecha(ctx):
    v = stocked(ctx)
    u = ctx.user("vend", "seller", is_seller=True, commission_percent=D("3.33"))
    api = ctx.client()
    sid = api.post(f"{A}/sales/", {"seller": u.pk}, format="json").json()["id"]
    api.post(f"{A}/sales/{sid}/items/", {"variant": str(v.pk), "quantity": "7"}, format="json")
    r = api.post(f"{A}/sales/{sid}/checkout/", {"payments": [
        {"nsu": "1", "method": str(ctx.methods["pix"].pk), "amount": "700.00"}]}, format="json")
    assert r.status_code == 200, r.json()
    it = Sale.all_objects.get(pk=sid).items.first()
    for _ in range(7):
        r = api.post(f"{A}/sales/{sid}/returns/", {"items": [{"sale_item": str(it.pk), "quantity": "1"}],
                     "refund_method": "original_payment", "reason": "x"}, format="json")
        assert api.post(f"{A}/returns/{r.json()['id']}/complete/", {}, format="json").status_code == 200
    total = sum(c.amount for c in Commission.all_objects.filter(sale_id=sid))
    assert total == 0, total


def test_m08_painel_credito_vencido(ctx):
    """Cliente excluido com vale: o vale nao some da contabilidade nem a divida."""
    from starrp.models import Customer, CustomerCredit
    c = Customer.all_objects.create(account=ctx.account, name="Ze", document="11144477735")
    CustomerCredit.all_objects.create(account=ctx.account, customer=c, kind="return", amount=D("50"))
    r = ctx.client(ctx.user("cx", "cashier")).delete(f"{A}/customers/{c.pk}/")
    assert r.status_code not in (204, 404), r.status_code


def test_m09_baixa_com_data_futura(ctx):
    c_title = finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"))
    r = ctx.client().post(f"{A}/finance/installments/{c_title.installments.first().pk}/settle/",
                          {"financial_account": str(bank(ctx).pk), "amount": "100", "date": "2099-01-01"}, format="json")
    assert r.status_code >= 400, r.status_code


def test_m10_titulo_sem_valor(ctx):
    r = ctx.client().post(f"{A}/finance/titles/", {"kind": "payable", "description": "x", "total": "0"}, format="json")
    assert r.status_code == 400, (r.status_code, FinancialTitle.all_objects.count())


def test_p01_motivo_da_precificacao_entrega_o_custo(ctx):
    """O texto sai de services/market/pricing.suggest; aqui so gravado para ver se a API o esconde do caixa."""
    from starrp.models import PriceCheck
    v = stocked(ctx, price="100.00", cost="61.37")
    c = PriceCheck.all_objects.create(account=ctx.account, variant=v, current_price=D("100"), cost=D("61.37"),
                                      reason="acima da mediana (custo R$ 61,37, margem mínima 20%): baixar não vale a pena.")
    r = ctx.client(ctx.user("cx", "cashier")).get(f"{A}/price-checks/{c.pk}/")
    assert r.status_code == 200, r.json()
    assert "cost" not in r.json()
    assert "61,37" not in r.content.decode(), r.json()["reason"]


def test_c01_cliente_nao_vira_fornecedor_no_fechamento(ctx):
    from starrp.models import Customer
    c = Customer.all_objects.create(account=ctx.account, name="Ze Cliente")
    finance.create_title(store=ctx.store, kind="receivable", description="x", total=D("100"), customer=c)
    r = ctx.client().get(f"{A}/reports/book/fechamento/").json()
    t = next(b for b in r["blocks"] if b["title"] == "Clientes e fornecedores")
    assert t["rows"][0]["type"] == "Cliente", t["rows"]
