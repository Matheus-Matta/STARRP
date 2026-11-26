# ruff: noqa: F403, F405, E741
import pytest
from django.db.models import Sum
from django.utils import timezone
from starrp.models import *  # noqa
from starrp.services import stock
V = "/api/v1"


@pytest.mark.parametrize("track", [True, False])
def test_wms_identidade(ctx, track):
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    StoreRule.all_objects.filter(pk=ctx.store.rule_id).update(allow_store_credit_refund=True)
    api = ctx.client()
    w = stock.default_warehouse(ctx.store)
    Warehouse.all_objects.filter(pk=w.pk).update(uses_bins=True)
    w.refresh_from_db()
    api.post(V + "/stock/bins/generate/", {"warehouse": str(w.pk), "aisles": ["A"], "racks": 2, "levels": 1, "kind": "picking"}, format="json")
    b1, b2 = StorageBin.all_objects.filter(warehouse=w).order_by("code")[:2]
    w2 = Warehouse.all_objects.create(account=ctx.account, store=ctx.store, name="Dep", kind=w.kind)
    v = ctx.product("Iog", track_lots=track)
    lot = {"lot_number": "A"} if track else {}

    def check(step):
        b = stock.available(v, w)
        k = StockMovement.all_objects.filter(variant=v, warehouse=w).aggregate(t=Sum("quantity"))["t"]
        e = BinBalance.all_objects.filter(variant=v, bin__warehouse=w).aggregate(t=Sum("quantity"))["t"]
        l = StockLot.all_objects.filter(variant=v, warehouse=w).aggregate(t=Sum("quantity"))["t"]
        bl = [(x.lot_id and x.lot.quantity, x.quantity) for x in BinBalance.all_objects.filter(variant=v, bin__warehouse=w)]
        neg = BinBalance.all_objects.filter(variant=v, quantity__lt=0).exists()
        assert b == k == e and (not track or l == b) and not neg, (step, b, k, e, l, bl)

    def doc(kind, items, wh=w, **k):
        d = api.post(V + "/stock/documents/", {"kind": kind, "warehouse": str(wh.pk), "effective_date": str(timezone.localdate()), "items": items, **k}, format="json")
        assert d.status_code == 201, d.json()
        r = api.post(f"{V}/stock/documents/{d.json()['id']}/post/", {}, format="json")
        check(kind)
        return r
    vid = {"variant": str(v.pk)}
    assert doc("entry", [{**vid, "quantity": "10", "unit_cost": "1", "bin": str(b1.pk), **lot}, {**vid, "quantity": "6", "unit_cost": "1", "bin": str(b2.pk), **lot}]).status_code == 200
    assert doc("relocation", [{**vid, "quantity": "3", "bin": str(b1.pk), "destination_bin": str(b2.pk)}]).status_code == 200
    c = Customer.all_objects.create(account=ctx.account, name="A")
    s = api.post(V + "/sales/", {"customer": str(c.pk)}, format="json").json()
    s = api.post(f"{V}/sales/{s['id']}/items/", {**vid, "quantity": "9"}, format="json").json()
    s = api.post(f"{V}/sales/{s['id']}/checkout/", {"payments": [{"method": str(ctx.methods["pix"].pk), "amount": s["total"]}]}, format="json").json()
    check("venda")
    for q in ("4", "5"):
        r = api.post(f"{V}/sales/{s['id']}/returns/", {"items": [{"sale_item": s["items"][0]["id"], "quantity": q}], "refund_method": "store_credit", "reason": "x"}, format="json").json()
        assert api.post(f"{V}/returns/{r['id']}/complete/", {}, format="json").status_code == 200
        check("dev" + q)
    r = doc("transfer", [{**vid, "quantity": "5"}], destination=str(w2.pk))
    assert r.status_code == 200
    api.post(f"{V}/stock/documents/{r.json()['id']}/cancel/", {}, format="json")
    check("canc transf")
    r = doc("inventory", [{**vid, "quantity": "2", "bin": str(b1.pk)}])
    check("inv bin")
    r = doc("inventory", [{**vid, "quantity": "1"}])
    check("inv sem bin")
    r = doc("inventory", [{**vid, "quantity": "4", "bin": str(b2.pk)}])
    check("inv sobra bin")
