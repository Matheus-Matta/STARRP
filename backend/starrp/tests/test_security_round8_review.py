# ruff: noqa: E702, E741, F403, F405, E501
from datetime import timedelta
from decimal import Decimal as D
import pytest
from django.utils import timezone
from starrp.models import *  # noqa
from starrp.models import (Coupon, Promotion, ServiceRule, StorageBin, StockLot, Warehouse, Customer, CustomerCredit)
from starrp.services import stock, returns
from starrp.tests.test_security_round4_money import _boot, _off
from starrp.tests.test_security_round6_sales import S, cust, new, pay, ret
P = "/api/v1/pdv/offline-sales/"


def svc(ctx, rule_price="50.00"):
    sv = ctx.product(name="Montagem", price="100.00", track_stock=False)
    sv.product.type = "service"; sv.product.save()
    g = ctx.product(name="Roupeiro", price="1000.00", track_stock=False)
    r = ServiceRule.all_objects.create(account=ctx.account, service=sv.product, kind="product", price=D(rule_price))
    r.products.add(g.product)
    return sv, g


@pytest.mark.parametrize("pedido", [True, False])
def test_servico_vira_autorizacao(ctx, pedido):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    sv, g = svc(ctx)
    sid = new(ctx, api, (g, 1))
    it = S(sid).items.first()
    r = api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(sv.pk), "quantity": "1", "service_for": str(it.pk)}, format="json")
    assert r.status_code == 201, r.json()
    assert S(sid).total == 1050, S(sid).total
    b = _off(ctx, g, "1000.00", total="1025.00", **({"replaces": sid} if pedido else {}))
    b["items"].append({"id": "b", "parent": "a", "variant": str(sv.pk), "quantity": "1", "unit_price": "25.00", "discount": "0"})
    b["payments"][0].update(amount="1025.00", tendered="1025.00")
    r = api.post(P, b, format="json")
    assert r.status_code == 201, r.json()
    s = S(r.json()["id"])
    assert "_approval_unverified" in s.metafields


@pytest.mark.parametrize("kind", ["installment_plan", "store_credit"])
def test_fato_a_prazo_recusado(ctx, kind):
    from starrp.models import PaymentMethod
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    c = cust(ctx, credit_limit=D(100)); v = ctx.product(price="100.00", track_stock=False)
    cr = CustomerCredit.all_objects.create(account=ctx.account, customer=c, kind="adjustment", amount=D(100))
    m = PaymentMethod.all_objects.filter(account=ctx.account, kind=kind).first()
    assert m
    b = _off(ctx, v, total="100.00", customer=str(c.pk)); b["payments"] = [{"method": str(m.pk), "amount": "100.00"}]
    d = api.post(P + "?dry_run=1", b, format="json"); assert d.status_code in (200, 201), d.json()
    Customer.all_objects.filter(pk=c.pk).update(credit_limit=0)
    CustomerCredit.all_objects.filter(pk=cr.pk).update(amount=D(50))
    r = api.post(P, b, format="json")
    assert r.status_code == 201, r.json()


def test_cupom_promocao(ctx):
    cx = ctx.user("cx", "cashier"); api = ctx.client(cx); _boot(api)
    v = ctx.product(price="100.00", track_stock=False)
    from starrp.models import DiscountTable
    Coupon.all_objects.create(account=ctx.account, code="C10", kind="amount", value=D(10), combines_with_promotions=False)
    t = DiscountTable.all_objects.create(account=ctx.account, name="t")
    Promotion.all_objects.create(account=ctx.account, table=t, name="p", target="all", kind="percent", value=D(20))
    from starrp.services import pricing
    assert pricing.quote(v).unit_price == 80
    b = _off(ctx, v, "80.00", total="70.00", coupon_code="C10"); b["payments"][0].update(amount="70.00", tendered="70.00")
    r = api.post(P + "?dry_run=1", b, format="json")
    assert r.status_code == 400 or r.status_code == 422, r.json().get("total")


def test_rascunhos_centavo(ctx):
    api = ctx.client()
    sid = new(ctx, api, (ctx.product(price="10.00", track_stock=False), 3))
    api.post(f"/api/v1/sales/{sid}/discount/", {"amount": "10.00"}, format="json")
    pay(ctx, api, sid)
    rs = [ret(api, sid, "original_payment") for _ in range(3)]
    for r in rs:
        returns.complete(r, ctx.admin)
    assert S(sid).refunded_amount <= S(sid).total, (S(sid).refunded_amount, S(sid).total)


@pytest.mark.parametrize("first", ["bin", "lot"])
def test_inventario_endereco_e_lote(ctx, first):
    w = stock.default_warehouse(ctx.store)
    Warehouse.all_objects.filter(pk=w.pk).update(uses_bins=True); w.refresh_from_db()
    bn = StorageBin.all_objects.create(account=ctx.account, warehouse=w, code="A1", kind="picking")
    v = ctx.product("Iog", track_lots=True)
    L = [StockLot.all_objects.create(account=ctx.account, variant=v, warehouse=w, code=f"L{i}", received_at=timezone.localdate() - timedelta(days=9 - i),
         expires_at=timezone.localdate() + timedelta(days=10 + i), initial_quantity=0, quantity=0) for i in range(2)]
    for l, q in zip(L, (4, 6), strict=False):
        stock.move(v, w, D(q), "purchase", lot=l, bin=bn, unit_cost=D(1))
    # contado: endereço 8 no total, dos quais L1(novo) = 4 -> saldo certo 8
    rows = [{"quantity": "8"}, {"quantity": "4", "lot": str(L[1].pk)}]
    if first == "lot":
        rows.reverse()
    api = ctx.client(); ctx.account.extra_modules = ["stock"]; ctx.account.save()
    d = api.post("/api/v1/stock/documents/", {"kind": "inventory", "warehouse": str(w.pk), "effective_date": str(timezone.localdate()),
        "items": [{"variant": str(v.pk), "bin": str(bn.pk), **r} for r in rows]}, format="json")
    assert d.status_code == 201, d.json()
    r = api.post(f"/api/v1/stock/documents/{d.json()['id']}/post/", {}, format="json")
    assert r.status_code != 200 or stock.available(v, w) == 8, stock.available(v, w)
