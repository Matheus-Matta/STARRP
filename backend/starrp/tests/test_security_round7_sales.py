from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from starrp.models import Coupon, PaymentMethod, StoreRule, FreightTable, CustomerAddress
from starrp.services import returns, stock
from starrp.tests.test_security_round4_money import _boot, _off
from starrp.tests.test_security_round6_sales import S, cust, new, pay


def send(api, b, dry=False):
    return api.post("/api/v1/pdv/offline-sales/" + ("?dry_run=1" if dry else ""), b, format="json")


def flagged(r):
    assert r.status_code == 201, r.json()
    return "_approval_unverified" in S(r.json()["id"]).metafields


def body(ctx, v, price, total, qty="1", discount="0", **kw):
    b = _off(ctx, v, price, total=total, **kw)
    b["items"][0].update(quantity=qty, discount=discount)
    b["payments"][0].update(amount=total, tendered=total)
    return b


def test_tolerancia_peso(ctx):
    api = ctx.client(ctx.user("cx", "cashier")); _boot(api)
    v = ctx.product(price="1000.00", track_stock=False)
    r = send(api, body(ctx, v, "2000000.00", "1.00", qty="1.001", discount="2001999.00"))
    assert flagged(r), S(r.json()["id"]).total


def test_tolerancia_peso_park(ctx):
    api = ctx.client(ctx.user("cx", "cashier")); _boot(api)
    v = ctx.product(price="1000.00", track_stock=False)
    b = body(ctx, v, "2000000.00", "1.00", qty="1.001", discount="2001999.00", park=True); b.pop("payments")
    r = send(api, b)
    assert r.status_code == 201, r.json()
    sid = r.json()["id"]
    api.post(f"/api/v1/sales/{sid}/resume/", {}, format="json")
    r = pay(ctx, api, sid)
    s = S(sid)
    assert not (s.status == "completed" and s.total < 500 and "_approval_unverified" not in s.metafields), s.total


def test_grant_promo(ctx):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    v = ctx.product(price="100.00", track_stock=False, promotional_price=D("50.00"))
    sid = new(ctx, api, (v, 1))
    assert S(sid).total == 50
    r = send(api, body(ctx, v, "25.00", "25.00", replaces=sid))
    assert flagged(r)


def test_control_grant(ctx):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    v = ctx.product(price="100.00", track_stock=False, promotional_price=D("50.00"))
    assert flagged(send(api, body(ctx, v, "25.00", "25.00")))


def test_grant_qtd(ctx):
    """desconto autorizado em 0,1 kg vale para 1000 un"""
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx)
    _boot(api)
    adm = ctx.client()
    v = ctx.product(price="100.00", track_stock=False)
    sid = new(ctx, api, (v, 1))
    it = S(sid).items.first()
    assert adm.patch(f"/api/v1/sales/{sid}/items/{it.pk}/", {"discount": "50.00"}, format="json").status_code == 200
    r = send(api, body(ctx, v, "100.00", "5000.00", qty="100", discount="5000.00", replaces=sid))
    assert flagged(r)


def test_header_grant_combina(ctx):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx)
    _boot(api)
    adm = ctx.client()
    cx.profile.role.max_discount_percent = D(10); cx.profile.role.save()
    v = ctx.product(price="100.00", track_stock=False)
    sid = new(ctx, api, (v, 1))
    assert adm.post(f"/api/v1/sales/{sid}/discount/", {"amount": "40.00"}, format="json").status_code == 200
    b = body(ctx, v, "100.00", "54.00", discount="10.00", replaces=sid)
    b["discount"] = "36.00"
    assert flagged(send(api, b))


@pytest.mark.parametrize("kind", ["ref", "parc", "maior", "frete", "endereco"])
def test_fato_recusado(ctx, kind):
    api = ctx.client(); _boot(api)
    v = ctx.product(price="100.00", track_stock=False)
    b = body(ctx, v, "100.00", "100.00")
    if kind == "ref":
        m = ctx.methods["credit_card"]
        PaymentMethod.all_objects.filter(pk=m.pk).update(requires_reference=True)
        StoreRule.all_objects.update(require_payment_reference=True)
        b["payments"][0] = {"method": str(m.pk), "amount": "100.00"}
    if kind == "parc":
        m = ctx.methods["credit_card"]
        PaymentMethod.all_objects.filter(pk=m.pk).update(max_installments=3)
        b["payments"][0] = {"method": str(m.pk), "amount": "100.00", "installments": 6}
    if kind == "maior":
        Coupon.all_objects.create(account=ctx.account, code="C1", kind="amount", value=D(10))
        b = body(ctx, v, "100.00", "95.00", coupon_code="C1")
    if kind in ("frete", "endereco"):
        c = cust(ctx)
        a = CustomerAddress.all_objects.create(account=ctx.account, customer=c, street="R", zip_code="01001000", city="SP", state="SP")
        t = FreightTable.all_objects.create(account=ctx.account, name="T", is_active=False)
        b = body(ctx, v, "100.00", "110.00", customer=str(c.pk), delivery={"address": str(a.pk), "table": str(t.pk)})
    r = send(api, b)
    assert r.status_code == 201, r.json()


def test_cupom_vencido_mais_gap(ctx):
    api = ctx.client(); _boot(api)
    Coupon.all_objects.create(account=ctx.account, code="C1", kind="amount", value=D(1), ends_at=timezone.now() - timedelta(minutes=1))
    v = ctx.product(price="11.00", track_stock=False)
    r = send(api, body(ctx, v, "11.00", "9.99", coupon_code="C1"))
    assert r.status_code == 201, r.json()


def test_kit_negativo_avisa(ctx):
    from starrp.models import StockRule
    StockRule.all_objects.update(allow_negative_stock=False)
    api = ctx.client(); _boot(api)
    v = ctx.product(price="10.00")
    assert flagged(send(api, body(ctx, v, "10.00", "10.00")))


def test_autorizador_falso(ctx):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    cx.profile.role.max_discount_percent = D(10); cx.profile.role.save()
    v = ctx.product(price="100.00", track_stock=False)
    b = body(ctx, v, "100.00", "90.00", discount_approved_by=ctx.admin.pk); b["discount"] = "10.00"
    r = send(api, b)
    assert r.status_code == 201, r.json()
    s = S(r.json()["id"])
    assert s.discount_approved_by_id != ctx.admin.pk or "_approval_unverified" in s.metafields


def test_devolucao_parcial_formula_velha(ctx):
    api = ctx.client()
    sid = new(ctx, api, *[(ctx.product(name=f"P{i}", sku=f"P{i}", price="10.00", track_stock=False), 1) for i in range(3)])
    api.post(f"/api/v1/sales/{sid}/discount/", {"amount": "10.00"}, format="json")
    pay(ctx, api, sid)
    for i in S(sid).items.all()[:2]:
        r = returns.create(S(sid), ctx.admin, [{"sale_item": i, "quantity": D(1)}], refund_method="original_payment", reason="x")
        r.items.update(total=D("6.67")); r.total = D("6.67"); r.save()
        returns.complete(r, ctx.admin)
    i = list(S(sid).items.all())[2]
    r = returns.create(S(sid), ctx.admin, [{"sale_item": i, "quantity": D(1)}], refund_method="original_payment", reason="x")
    returns.complete(r, ctx.admin)
    assert S(sid).refunded_amount <= S(sid).total, S(sid).refunded_amount


def test_grant_promo_park(ctx):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    v = ctx.product(price="100.00", track_stock=False, promotional_price=D("50.00"))
    sid = new(ctx, api, (v, 1))
    b = body(ctx, v, "50.00", "25.00", discount="25.00", replaces=sid, park=True); b.pop("payments")
    r = send(api, b)
    sid = r.json()["id"]
    api.post(f"/api/v1/sales/{sid}/resume/", {}, format="json")
    r = pay(ctx, api, sid)
    s = S(sid)
    assert not (s.status == "completed" and s.total < 50), s.total


@pytest.mark.parametrize("stage", ["bin", "wh"])
def test_restock_lugar_inativo(ctx, stage):
    from starrp.models import Warehouse
    api = ctx.client()
    v = ctx.product(price="10.00")
    w = stock.default_warehouse(ctx.store)
    stock.move(v, w, D(5), "purchase", unit_cost=D(1))
    sid = new(ctx, api, (v, 2)); pay(ctx, api, sid)
    if stage == "wh":
        Warehouse.all_objects.filter(pk=w.pk).update(is_default=False, deleted_at=timezone.now())
        Warehouse.all_objects.create(account=ctx.account, store=ctx.store, name="N", is_default=True)
    r = returns.create(S(sid), ctx.admin, [{"sale_item": S(sid).items.first(), "quantity": D(1)}], refund_method="original_payment", reason="x")
    returns.complete(r, ctx.admin)
    from starrp.models import StockMovement
    m = StockMovement.all_objects.get(kind="sale_return")
    assert m.warehouse.deleted_at is None


def test_etiqueta_muda_qtd(ctx):
    from starrp.tests.test_security_round6_sales import _scale, _label
    _scale(ctx, "price")
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    ctx.product(price="39.90", track_stock=False, scale_code="123")
    ctx.client()
    sid = api.post("/api/v1/sales/", {}, format="json").json()["id"]
    r = api.post(f"/api/v1/sales/{sid}/items/", {"code": _label(123, 1001)}, format="json")
    assert r.status_code == 201, r.json()
    it = S(sid).items.first()
    assert it.total == D("10.01")
    r = api.post(f"/api/v1/sales/{sid}/items/", {"code": _label(123, 2003)}, format="json")
    for q in ("0.200", "0.100"):
        r = api.patch(f"/api/v1/sales/{sid}/items/{it.pk}/", {"quantity": q}, format="json")
        assert r.status_code == 200, r.json()


def test_unsettle_duas_vezes(ctx):
    from starrp.services import finance, dre
    from starrp.models import FinancialAccount, InstallmentSettlement
    acc = FinancialAccount.all_objects.filter(account=ctx.account).first() or FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="C", kind="bank")
    t = finance.create_title(store=ctx.store, kind="receivable", description="x", total=D(100), user=ctx.admin)
    p = t.installments.get()
    for _ in range(2):
        finance.settle(p, acc, D(40), ctx.admin, interest=D(5))
        finance.settle(p, acc, D(30), ctx.admin, fine=D(2), discount=D(1))
        finance.unsettle(p, ctx.admin, "r")
    from django.db.models import Sum
    a = InstallmentSettlement.all_objects.aggregate(a=Sum("amount"), i=Sum("interest"), f=Sum("fine"), d=Sum("discount"))
    assert not any(a.values()), a
    assert dre.build(ctx.account, ctx.store, {})["other_revenue_total"] == 100


def test_controle_peso_normal(ctx):
    """controle: mesma fraude sem inflar o preço é marcada"""
    api = ctx.client(ctx.user("cx", "cashier")); _boot(api)
    v = ctx.product(price="1000.00", track_stock=False)
    assert flagged(send(api, body(ctx, v, "1000.00", "1.00", qty="1.001", discount="1000.00")))


def test_devolucao_consultas(ctx):
    api = ctx.client()
    sid = new(ctx, api, *[(ctx.product(name=f"P{i}", sku=f"P{i}", price="10.00", track_stock=False), 1) for i in range(20)])
    api.post(f"/api/v1/sales/{sid}/discount/", {"amount": "10.00"}, format="json")
    pay(ctx, api, sid)
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    with CaptureQueriesContext(connection) as q:
        returns.create(S(sid), ctx.admin, [{"sale_item": i, "quantity": D(1)} for i in S(sid).items.all()], refund_method="original_payment", reason="x")
    assert len(q) < 130


def test_is_purchase_devolucao():
    from starrp.services import nfe_xml
    x = '<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><infNFe><ide><tpNF>1</tpNF><finNFe>4</finNFe></ide></infNFe></NFe>'
    assert not nfe_xml.is_purchase(x)
