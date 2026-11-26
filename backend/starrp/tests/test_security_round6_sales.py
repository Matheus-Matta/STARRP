from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from starrp.models import (
    Commission, Coupon, Customer, CustomerAddress, FreightTable, PaymentMethod, Sale, SaleReturn, StockLot, StockRule,
    Store, StoreRule,
)
from starrp.services import barcodes, returns, stock
from starrp.tests.test_security_round4_money import _boot, _off


def new(ctx, api, *rows, **kw):
    sid = api.post("/api/v1/sales/", kw, format="json").json()["id"]
    for v, q in rows:
        r = api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(v.pk), "quantity": str(q)}, format="json")
        assert r.status_code == 201, r.json()
    return sid


def S(sid):
    return Sale.all_objects.get(pk=sid)


def pay(ctx, api, sid, kind="pix", amount=None, **kw):
    return api.post(f"/api/v1/sales/{sid}/checkout/", {"payments": [
        {"method": str(ctx.methods[kind].pk), "amount": str(amount or S(sid).total), **kw}]}, format="json")


def cust(ctx, **k):
    return Customer.all_objects.create(account=ctx.account, name=k.pop("name", "Ana"), **k)


def ret(api, sid, how):
    r = api.post(f"/api/v1/sales/{sid}/returns/", {"items": [{"sale_item": str(i.pk), "quantity": "1"} for i in S(sid).items.all()],
                 "refund_method": how, "reason": "x"}, format="json")
    assert r.status_code == 201, r.json()
    return SaleReturn.all_objects.get(pk=r.json()["id"])


def drawer(ctx, api, value="500"):
    ctx.link(ctx.admin)
    from starrp.services import cash
    s = cash.open_session(ctx.register, ctx.admin, D(value))
    s.status = "open"
    s.save()
    return s


@pytest.mark.parametrize("disc", ["10.00", "5.00"])
def test_devolucao_total_rateio(ctx, disc):
    api = ctx.client()
    sid = new(ctx, api, *[(ctx.product(name=f"P{i}", sku=f"P{i}", price="10.00", track_stock=False), 1) for i in range(3)])
    api.post(f"/api/v1/sales/{sid}/discount/", {"amount": disc}, format="json")
    assert pay(ctx, api, sid).status_code == 200
    assert ret(api, sid, "original_payment").total == S(sid).total


def test_devolucao_total_dinheiro_rateio(ctx):
    api = ctx.client()
    drawer(ctx, api)
    sid = new(ctx, api, *[(ctx.product(name=f"P{i}", sku=f"P{i}", price="10.00", track_stock=False), 1) for i in range(3)])
    api.post(f"/api/v1/sales/{sid}/discount/", {"amount": "10.00"}, format="json")
    assert pay(ctx, api, sid, "cash").status_code == 200
    returns.complete(ret(api, sid, "cash"), ctx.admin)


def test_cupom_mais_desconto_negativo(ctx):
    api = ctx.client()
    Coupon.all_objects.create(account=ctx.account, code="X60", kind="amount", value=D(60))
    v = ctx.product(price="100.00", track_stock=False, commission_percent=D(10))
    sid = new(ctx, api, (v, 1))
    assert api.post(f"/api/v1/sales/{sid}/discount/", {"amount": "60.00"}, format="json").status_code == 200
    assert api.post(f"/api/v1/sales/{sid}/coupon/", {"code": "X60"}, format="json").status_code == 200
    r = api.post(f"/api/v1/sales/{sid}/complete/", {}, format="json")
    assert r.status_code == 200, r.json()
    assert all(x.amount >= 0 for x in Commission.all_objects.all()), [x.amount for x in Commission.all_objects.all()]


def test_lote_devolvido_vende_de_novo(ctx):
    api = ctx.client()
    v = ctx.product(price="10.00", track_lots=True)
    w = stock.default_warehouse(ctx.store)
    lot = StockLot.all_objects.create(account=ctx.account, variant=v, warehouse=w, code="L1", initial_quantity=1, quantity=0,
                                      received_at=timezone.localdate())
    StockRule.all_objects.update(allow_negative_stock=False)
    stock.move(v, w, D(1), "purchase", lot=lot, unit_cost=D(5), source_key="a")
    cu = cust(ctx)
    sid = new(ctx, api, (v, 1), customer=str(cu.pk))
    assert pay(ctx, api, sid).status_code == 200
    returns.complete(ret(api, sid, "store_credit"), ctx.admin)
    assert stock.available(v) == 1
    r = pay(ctx, api, new(ctx, api, (v, 1)))
    assert r.status_code == 200, r.json()


def test_boleto_devolve_dinheiro(ctx):
    api = ctx.client()
    s = drawer(ctx, api)
    ctx.methods["bank_slip"] = ctx.methods.get("bank_slip") or PaymentMethod.all_objects.create(
        account=ctx.account, name="Boleto", kind="bank_slip")
    v = ctx.product(price="100.00", track_stock=False)
    sid = new(ctx, api, (v, 1), customer=str(cust(ctx).pk))
    r = pay(ctx, api, sid, "bank_slip")
    assert r.status_code == 200, r.json()
    x = ret(api, sid, "cash")
    from starrp.services import cash
    try:
        returns.complete(x, ctx.admin)
    except Exception as e:
        assert getattr(e, "code", None) == "cash_refund_limit" or "passa do que" in str(e), e
    s.refresh_from_db()
    assert cash.expected_cash(s) == 500


def _scale(ctx, mode):
    StoreRule.all_objects.filter(pk=ctx.store.rule_id).update(scale_barcode_mode=mode)


def _label(plu, val, pre="2", size=6):
    b = f"{pre}{plu:0{size}d}{val:05d}"
    return next(b + d for d in "0123456789" if barcodes.ean_check_digit_ok(b + d))


def test_balanca_preco_promocional(ctx):
    _scale(ctx, "price")
    api = ctx.client()
    ctx.product(price="40.00", scale_code="123", promotional_price=D("30.00"), track_stock=False)
    sid = new(ctx, api)
    r = api.post(f"/api/v1/sales/{sid}/items/", {"code": _label(123, 3000)}, format="json")
    assert r.status_code == 201, r.json()
    assert S(sid).total == D("30.00"), S(sid).items.first().quantity


def test_balanca_preco_centavo(ctx):
    _scale(ctx, "price")
    api = ctx.client()
    ctx.product(price="199.90", scale_code="123", track_stock=False)
    sid = new(ctx, api)
    api.post(f"/api/v1/sales/{sid}/items/", {"code": _label(123, 1234)}, format="json")
    assert S(sid).total == D("12.34")


def test_balanca_regra_da_filial(ctx):
    _scale(ctx, "price")
    rb = StoreRule.all_objects.create(account=ctx.account, name="B", scale_barcode_mode="weight")
    b = Store.all_objects.create(account=ctx.account, name="B", rule=rb, logistics_rule=ctx.store.logistics_rule,
                                 stock_rule=ctx.store.stock_rule)
    api = ctx.client(store=b)
    ctx.product(price="40.00", scale_code="123", track_stock=False)
    sid = new(ctx, api)
    api.post(f"/api/v1/sales/{sid}/items/", {"code": _label(123, 500)}, format="json")
    assert S(sid).items.first().quantity == D("0.5"), S(sid).total


def test_prefixo_2_digitos(ctx):
    _scale(ctx, "weight")
    StoreRule.all_objects.update(scale_barcode_prefix="20")
    ctx.product(price="40.00", scale_code="123", track_stock=False)
    r = barcodes.resolve_code(ctx.account.pk, _label(123, 500, "20", 5))
    assert r and r.quantity == D("0.5")


def test_troca_cliente_endereco(ctx):
    api = ctx.client()
    a, b = cust(ctx), cust(ctx, name="Bia")
    ad = CustomerAddress.all_objects.create(account=ctx.account, customer=a, label="casa", zip_code="20000000", street="r",
                                            number="1", city="Rio", state="RJ")
    t = FreightTable.all_objects.create(account=ctx.account, name="t", kind="zip_range")
    t.ranges.model.all_objects.create(account=ctx.account, table=t, zip_start="00000000", zip_end="99999999", value=D(15))
    v = ctx.product(price="100.00", track_stock=False)
    sid = new(ctx, api, (v, 1), customer=str(a.pk))
    r = api.post(f"/api/v1/sales/{sid}/delivery/", {"address": str(ad.pk), "table": str(t.pk)}, format="json")
    assert r.status_code == 200, r.json()
    r = api.post(f"/api/v1/sales/{sid}/customer/", {"customer": str(b.pk)}, format="json")
    assert r.status_code == 200
    r = pay(ctx, api, sid)
    s = S(sid)
    assert r.status_code >= 400 or s.shipping_address is None or s.shipping_address.customer_id == b.pk, (s.freight, s.shipping_address.customer.name)


def test_tira_cliente_com_entrega_conclui(ctx):
    test_troca_cliente_endereco(ctx)


def test_cupom_vencido_pedido_guardado(ctx):
    api = ctx.client()
    Coupon.all_objects.create(account=ctx.account, code="C10", kind="amount", value=D(10))
    sid = new(ctx, api, (ctx.product(price="100.00", track_stock=False), 1))
    api.post(f"/api/v1/sales/{sid}/coupon/", {"code": "C10"}, format="json")
    api.post(f"/api/v1/sales/{sid}/park/", {}, format="json")
    Coupon.all_objects.update(ends_at=timezone.now() - timedelta(days=3))
    api.post(f"/api/v1/sales/{sid}/resume/", {}, format="json")
    r = pay(ctx, api, sid)
    assert r.status_code >= 400 or S(sid).coupon_discount == 0


def test_primeira_compra_duas_abertas(ctx):
    api = ctx.client()
    Coupon.all_objects.create(account=ctx.account, code="PRI", kind="amount", value=D(10), first_purchase_only=True)
    cu = cust(ctx, document="52998224725")
    v = ctx.product(price="100.00", track_stock=False)
    ids = []
    for _ in range(2):
        sid = new(ctx, api, (v, 1), customer=str(cu.pk))
        r = api.post(f"/api/v1/sales/{sid}/coupon/", {"code": "PRI"}, format="json")
        assert r.status_code == 200, r.json()
        ids.append(sid)
    assert pay(ctx, api, ids[0]).status_code == 200
    assert pay(ctx, api, ids[1]).status_code >= 400


def test_offline_fato_sem_estoque(ctx):
    StockRule.all_objects.update(allow_negative_stock=False)
    api = ctx.client()
    _boot(api)
    r = api.post("/api/v1/pdv/offline-sales/", _off(ctx, ctx.product(price="10.00"), "10.00", was_offline=True), format="json")
    assert r.status_code == 201, r.json()


def test_offline_fato_exige_vendedor(ctx):
    StoreRule.all_objects.update(require_seller=True)
    api = ctx.client()
    _boot(api)
    r = api.post("/api/v1/pdv/offline-sales/", _off(ctx, ctx.product(price="10.00", track_stock=False), "10.00", was_offline=True), format="json")
    assert r.status_code == 201, r.json()


def test_offline_fato_cupom_venceu_no_envio(ctx):
    api = ctx.client()
    _boot(api)
    Coupon.all_objects.create(account=ctx.account, code="C1", kind="amount", value=D(1), ends_at=timezone.now() - timedelta(minutes=1))
    b = _off(ctx, ctx.product(price="11.00", track_stock=False), "11.00", coupon_code="C1", total="10.00")
    b["payments"][0].update(amount="10.00", tendered="10.00")
    r = api.post("/api/v1/pdv/offline-sales/", b, format="json")
    assert r.status_code == 201, r.json()


def test_offline_peso_meio_centavo(ctx):
    api = ctx.client()
    _boot(api)
    b = _off(ctx, ctx.product(price="53.00", track_stock=False), "53.00", total="2.38")
    b["items"][0]["quantity"] = "0.045"
    b["payments"][0].update(amount="2.38", tendered="2.38")
    r = api.post("/api/v1/pdv/offline-sales/", b, format="json")
    assert r.status_code == 201, r.json()


def test_retomado_desktop_perde_autorizacao(ctx):
    admin = ctx.client()
    api = ctx.client(ctx.user("cx", "cashier"))
    _boot(api)
    v = ctx.product(price="100.00", track_stock=False)
    sid = new(ctx, api, (v, 1))
    assert admin.post(f"/api/v1/sales/{sid}/discount/", {"amount": "40.00"}, format="json").status_code == 200
    api.post(f"/api/v1/sales/{sid}/park/", {}, format="json")
    api.post(f"/api/v1/sales/{sid}/resume/", {}, format="json")
    b = _off(ctx, v, "100.00", replaces=sid, discount="40.00", total="60.00")
    b["payments"][0].update(amount="60.00", tendered="60.00")
    r = api.post("/api/v1/pdv/offline-sales/", b, format="json")
    assert r.status_code == 201, r.json()
    assert "_approval_unverified" not in S(r.json()["id"]).metafields, S(r.json()["id"]).metafields


def test_promo_maior_que_preco_snapshot(ctx):
    api = ctx.client()
    _boot(api)
    v = ctx.product(price="10.00", track_stock=False, promotional_price=D("12.00"))
    snap = api.get("/api/v1/pdv/catalog-snapshot/").json()
    cp = [x for p in snap["products"] for x in p["variants"] if x["id"] == str(v.pk)][0]["current_price"]
    assert S(new(ctx, api, (v, 1))).total == D(cp)


def test_promo_maior_que_preco_recusado(ctx):
    v = ctx.product(price="10.00", track_stock=False)
    r = ctx.client().patch(f"/api/v1/catalog/variants/{v.pk}/", {"promotional_price": "12.00"}, format="json")
    assert r.status_code >= 400, r.json()


def test_troca_crediario_para_crediario(ctx):
    api = ctx.client()
    cu = cust(ctx, credit_limit=D(100))
    sid = new(ctx, api, (ctx.product(price="100.00", track_stock=False), 1), customer=str(cu.pk))
    m = ctx.methods.get("installment_plan") or PaymentMethod.all_objects.create(account=ctx.account, name="Cred", kind="installment_plan", max_installments=12)
    ctx.methods["installment_plan"] = m
    PaymentMethod.all_objects.filter(pk=m.pk).update(max_installments=12)
    r = pay(ctx, api, sid, "installment_plan")
    assert r.status_code == 200, r.json()
    p = S(sid).payments.first()
    r = api.post(f"/api/v1/sales/{sid}/payments/{p.pk}/change/", {"method": str(m.pk), "reason": "era 3x", "installments": 3}, format="json")
    assert r.status_code == 200, r.json()


def test_parcelas_texto_na_troca_500(ctx):
    api = ctx.client()
    sid = new(ctx, api, (ctx.product(price="100.00", track_stock=False), 1))
    pay(ctx, api, sid)
    p = S(sid).payments.first()
    r = api.post(f"/api/v1/sales/{sid}/payments/{p.pk}/change/", {"method": str(p.method_id), "reason": "x", "installments": "abc"}, format="json")
    assert r.status_code < 500


def test_troca_exige_nsu(ctx):
    StoreRule.all_objects.update(require_payment_reference=True)
    PaymentMethod.all_objects.filter(kind="credit_card").update(requires_reference=True)
    api = ctx.client()
    drawer(ctx, api)
    sid = new(ctx, api, (ctx.product(price="100.00", track_stock=False), 1))
    assert pay(ctx, api, sid, "cash").status_code == 200
    p = S(sid).payments.first()
    r = api.post(f"/api/v1/sales/{sid}/payments/{p.pk}/change/", {"method": str(ctx.methods["credit_card"].pk), "reason": "x"}, format="json")
    assert r.status_code >= 400


def test_cancelar_venda_com_pagamento_gaveta_vazia(ctx):
    api = ctx.client()
    s = drawer(ctx, api, "0")
    sid = new(ctx, api, (ctx.product(price="100.00", track_stock=False), 1))
    assert pay(ctx, api, sid, "cash").status_code == 200
    from starrp.services import cash
    from starrp.models import CashMovement
    CashMovement.all_objects.create(account=ctx.account, store=ctx.store, session=s, kind="withdrawal", amount=D(100), status="approved", operator=ctx.admin, reason="s")
    r = api.post(f"/api/v1/sales/{sid}/cancel/", {"reason": "erro"}, format="json")
    assert cash.expected_cash(s) >= 0, r.status_code
