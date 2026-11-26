# ruff: noqa
"""Um mês de loja pela API: caixa, estoque, financeiro e relatórios fecham entre si."""
"""Um mes de loja pela API, 2 filiais, e as identidades contabeis."""
import csv
import io
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.utils import timezone

from starrp.models import *  # noqa
from starrp.models import LogisticsRule
from starrp.services import stock, cash, checkout
from starrp.services.provisioning import create_store
from starrp.services.cosmos import datasets
from starrp.tests.nfe_fixture import UNIT_EAN, nfe_xml

SP = ZoneInfo("America/Sao_Paulo")
V = "/api/v1"


class Clock:
    def __init__(s): s.t = datetime(2026, 10, 1, 9, tzinfo=SP)

    def now(s):
        s.t += timedelta(seconds=7)
        return s.t.astimezone(tz.utc)

    def day(s, d, h=9, m=10): s.t = datetime(2026, m, d, h, tzinfo=SP)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(timezone, "now", c.now)
    return c


class Api:
    def __init__(s, c): s.c = c

    def __call__(s, method, url, data=None, ok=(200, 201)):
        kw = {} if method == "get" else {"format": "json"}
        r = getattr(s.c, method)(V + url, data, **kw)
        assert r.status_code in ok, (url, data, r.status_code, r.content[:600].decode())
        return r.json()

    def post(s, u, d=None): return s("post", u, d or {})
    def get(s, u, d=None): return s("get", u, d)


def build(ctx):
    a = ctx.account
    a.extra_modules = ["stock", "finance", "inbound_nfe", "pricing"]
    a.save()
    Store.all_objects.filter(pk=ctx.store.pk).update(cnpj="11222333000181")
    LogisticsRule.all_objects.filter(account=a).update(allow_manual_conference=True)
    s1 = Store.all_objects.get(pk=ctx.store.pk)
    ctx.store = s1
    s2 = create_store(a, "Filial 2", rule=s1.rule, stock_rule=s1.stock_rule, logistics_rule=s1.logistics_rule)
    StoreRule.all_objects.filter(pk=s1.rule_id).update(require_open_cash_session=True, allow_store_credit_refund=True,
                                                       require_seller=False, cash_closing_tolerance=D("0"))
    ops = [ctx.user("op1", "cashier", [s1]), ctx.user("op2", "cashier", [s1]), ctx.user("op3", "cashier", [s2])]
    r12 = CashRegister.all_objects.create(account=a, store=s1, name="Caixa 02", code="02", operator=ops[1])
    r1 = ctx.link(ops[0])
    r2 = ctx.link(ops[2], CashRegister.all_objects.get(store=s2))
    from starrp.models import Permission
    for u in ops:
        u.profile.extra_permissions.add(Permission.objects.get(code="sales.return"))
    v1 = ctx.user("ven1", "seller", [s1, s2], is_seller=True, commission_percent=D("3.5"))
    v2 = ctx.user("ven2", "seller", [s1, s2], is_seller=True, commission_percent=D("2.25"))
    return dict(a=a, s1=s1, s2=s2, regs=[r1, r12, r2], v1=v1, v2=v2, adm=Api(ctx.client(store=s1)),
                adm2=Api(ctx.client(store=s2)), net=Api(ctx.client(store=None)),
                apis=[Api(ctx.client(ops[0], s1)), Api(ctx.client(ops[1], s1)), Api(ctx.client(ops[2], s2))])


def test_mes(ctx, clock):
    e = build(ctx)
    a, s1, s2, adm, adm2 = e["a"], e["s1"], e["s2"], e["adm"], e["adm2"]
    A1, A2, A3 = e["apis"]
    AP = {"username": "admin-lojateste", "password": "senha123"}
    bad = []

    def check(n, x, y, tol="0"):
        if abs(D(str(x)) - D(str(y))) > D(tol):
            bad.append((n, str(x), str(y)))

    cat1 = Category.all_objects.create(account=a, name="Bebidas")
    cat2 = Category.all_objects.create(account=a, name="Casa")
    soda = ctx.product("Refri", "5.37", sku="REFRI", category=cat1)
    ProductBarcode.all_objects.create(account=a, variant=soda, code=UNIT_EAN)
    yog = ctx.product("Iogurte", "6.99", sku="IOG", track_lots=True, category=cat1)
    meat = ctx.product("Carne kg", "39.90", sku="CARNE")
    mug = ctx.product("Caneca", "33.33", sku="CAN", category=cat2)
    promo = ctx.product("Vaso", "80.00", sku="VASO", category=cat2, promotional_price=D("64.90"))
    kit = ctx.product("Kit", "40.00", sku="KIT", type="kit", track_stock=False)
    KitComponent.all_objects.create(account=a, kit=kit.product, component=mug, quantity=D(1))
    KitComponent.all_objects.create(account=a, kit=kit.product, component=soda, quantity=D(2))
    ward = ctx.product("Armario", "999.99", sku="ARM", category=cat2)
    serv = ctx.product("Montagem", "80.00", sku="MONT", type="service", track_stock=False)
    adm.post("/catalog/service-rules/", {"service": str(serv.product_id), "kind": "product", "products": [str(ward.product_id)]})
    M = {k: str(m.pk) for k, m in ctx.methods.items()}
    for k, f, d, i in (("credit_card", "3.19", 30, 6), ("debit_card", "1.37", 0, 1), ("pix", "0.99", 0, 1),
                       ("installment_plan", "0", 0, 10), ("bank_slip", "0", 0, 3), ("voucher", "4.5", 0, 1)):
        if k in ctx.methods:
            PaymentMethod.all_objects.filter(pk=ctx.methods[k].pk).update(
                fee_percent=D(f), settlement_days=d, max_installments=i, requires_reference=False)
    bank = FinancialAccount.all_objects.filter(account=a, kind="bank").first()
    vaults = [FinancialAccount.all_objects.filter(store=s, kind="cash").first() for s in (s1, s2)]
    for v, o in zip(vaults, ("1000", "500")):
        FinancialAccount.all_objects.filter(pk=v.pk).update(opening_balance=D(o))
    W1, W2 = stock.default_warehouse(s1), stock.default_warehouse(s2)
    ana = adm.post("/customers/", {"name": "Ana", "document": "52998224725"})["id"]
    Customer.all_objects.filter(pk=ana).update(credit_limit=D(3000))
    addr = adm.post("/customers/addresses/", {"customer": ana, "label": "Casa", "zip_code": "01310100", "street": "X",
                                              "number": "1", "district": "C", "city": "SP", "state": "SP"})["id"]
    table = adm.post("/logistics/freight-tables/", {"name": "Moto", "kind": "zip_range", "lead_days": 2, "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "15.55"}]})["id"]
    adm.post("/promotions/coupons/", {"name": "Dez", "code": "DEZ", "kind": "percent", "value": "10"})
    adm.post("/promotions/coupons/", {"name": "Frete", "code": "FRETE", "kind": "free_shipping", "value": "0"})

    def doc(api, kind, w, items, **k):
        d = api.post("/stock/documents/", {"kind": kind, "warehouse": str(w.pk), "effective_date": "2026-10-01", "items": items, **k})
        return api.post(f"/stock/documents/{d['id']}/post/")

    doc(adm, "entry", W1, [{"variant": str(v.pk), "quantity": q, "unit_cost": c} for v, q, c in (
        (soda, "100", "2.13"), (meat, "50.500", "21.337"), (mug, "30", "11.11"), (promo, "20", "30.01"), (ward, "5", "500.50"))]
        + [{"variant": str(yog.pk), "quantity": "20", "unit_cost": "3.07", "lot_number": "L1", "expires_at": "2026-11-29"},
           {"variant": str(yog.pk), "quantity": "10", "unit_cost": "3.33", "lot_number": "L2", "expires_at": "2026-12-30"}])
    nfe = ctx.client().post(V + "/inbound-nfe/import/", {"file": SimpleUploadedFile("n.xml", nfe_xml(), content_type="text/xml")}, format="multipart").json()
    it = next(i for i in nfe["items"] if not i["variant"])
    adm.post(f"/inbound-nfe/{nfe['id']}/map-item/", {"item": it["id"], "variant": str(yog.pk)})
    clock.day(1, 10)
    adm.post(f"/inbound-nfe/{nfe['id']}/receive/", {"warehouse": str(W1.pk), "post": True})
    doc(adm, "transfer", W1, [{"variant": str(soda.pk), "quantity": "40"}, {"variant": str(mug.pk), "quantity": "10"},
                              {"variant": str(yog.pk), "quantity": "25"}], destination=str(W2.pk))
    sess, closed = {}, []

    def op(i, amount):
        s = e["apis"][i].post("/cash/sessions/", {"register": str(e["regs"][i].pk), "opening_amount": amount})
        assert s["status"] == "open", s
        sess[i] = s["id"]

    def cl(i, diff="0"):
        sid = sess.pop(i)
        o = CashSession.all_objects.get(pk=sid)
        exp = cash.expected_cash(o)
        check("gaveta=movs", exp, o.opening_amount + sum((m.amount * m.SIGN[m.kind] for m in o.movements.filter(status="approved")), D(0)))
        e["apis"][i].post(f"/cash/sessions/{sid}/close/", {"counted_amount": str(exp + D(diff))})
        if D(diff):
            (adm2 if i == 2 else adm).post(f"/cash/sessions/{sid}/approve/", {"reason": "troco errado"})
        assert CashSession.all_objects.get(pk=sid).status == "closed"
        closed.append(sid)
        return exp + D(diff)

    def sell(api, items, pays, customer=None, seller=None, disc=None, pct=None, coupon=None, freight=False):
        s = api.post("/sales/", {k: v for k, v in (("customer", customer), ("seller", seller.pk if seller else None)) if v})
        u = f"/sales/{s['id']}"
        for v, q, *x in items:
            s = api.post(u + "/items/", {"variant": str(v.pk), "quantity": q, **(x[0] if x else {})})
        if disc:
            s = api.post(u + "/discount/", {"amount": disc, "approval": AP})
        if pct:
            s = api.post(u + "/discount/", {"percent": pct, "approval": AP})
        if freight:
            s = api.post(u + "/delivery/", {"address": addr, "table": table})
        if coupon:
            s = api.post(u + "/coupon/", {"code": coupon})
        left, out = D(s["total"]), []
        for k, v, *x in pays:
            v = left if v is None else D(v)
            left -= v
            out.append({"method": M[k], "amount": str(v), **(x[0] if x else {})})
        return api.post(u + "/checkout/", {"payments": out})

    def ret(api, sale, rows, method, restock=True):
        r = api.post(f"/sales/{sale['id']}/returns/", {"items": [
            {"sale_item": sale["items"][i]["id"], "quantity": q, "restock": restock} for i, q in rows],
            "refund_method": method, "reason": "x", "approval": AP})
        # concluir exige a permissao: quem conclui eh o gerente quando o operador nao pode
        return api.post(f"/returns/{r['id']}/complete/")

    clock.day(2)
    op(0, "100"), op(1, "50"), op(2, "80")
    x1 = sell(A1, [(soda, "3"), (mug, "2", {"discount": "1.11", "approval": AP})], [("cash", None, {"tendered": "200"})], seller=e["v1"])
    x2 = sell(A1, [(meat, "1.237"), (kit, "3")], [("pix", "50"), ("debit_card", None)], seller=e["v2"], pct="7.5")
    sell(A2, [(yog, "12"), (promo, "1")], [("credit_card", None, {"installments": 3})], seller=e["v1"])
    x4 = sell(A2, [(ward, "1", {"services": [str(serv.pk)]})], [("installment_plan", "700", {"installments": 7}), ("cash", None)],
              customer=ana, seller=e["v2"], freight=True)
    x5 = sell(A3, [(soda, "10"), (yog, "4"), (mug, "1")], [("cash", None)], seller=e["v1"], customer=ana, coupon="DEZ")
    sell(A1, [(promo, "3")], [("pix", None)], customer=ana, seller=e["v1"], freight=True, coupon="FRETE")
    A1.post(f"/cash/sessions/{sess[0]}/movements/", {"kind": "withdrawal", "amount": "20", "reason": "s", "approval": AP})
    A2.post(f"/cash/sessions/{sess[1]}/movements/", {"kind": "supply", "amount": "35.5", "reason": "s", "approval": AP})
    clock.day(5)
    ret(A1, x1, [(0, "1")], "cash")
    ret(A1, x1, [(0, "2"), (1, "1")], "cash")
    ret(A1, x2, [(1, "1")], "cash", restock=False)
    ret(A3, x5, [(0, "3"), (1, "1")], "store_credit")
    ret(A3, x5, [(0, "7"), (1, "3"), (2, "1")], "exchange")
    check("vale=devolvido", checkout.credit_balance(Customer.all_objects.get(pk=ana)), x5["total"])
    sell(A3, [(soda, "4")], [("store_credit", None)], customer=ana, seller=e["v2"])
    sell(A1, [(mug, "2"), (soda, "1")], [("store_credit", "20"), ("cash", None)], customer=ana, seller=e["v2"], disc="3.33")
    x9 = sell(A1, [(soda, "7")], [("pix", None)], seller=e["v1"])
    ret(A1, x9, [(0, "3")], "original_payment")
    ret(A1, x9, [(0, "4")], "original_payment")
    for api, its, pays in ((A2, [(mug, "1"), (yog, "1")], [("credit_card", None, {"installments": 2})]),
                           (A2, [(soda, "2")], [("cash", None)]), (A3, [(soda, "2"), (mug, "1")], [("cash", "10"), ("pix", None)])):
        x = sell(api, its, pays, seller=e["v1"])
        api.post(f"/sales/{x['id']}/cancel/", {"reason": "cliente desistiu da compra", "approval": AP})
    if "bank_slip" in M:
        sell(A1, [(promo, "2")], [("bank_slip", None, {"installments": 3})], customer=ana, seller=e["v2"])
    if "voucher" in M:
        sell(A1, [(soda, "5")], [("voucher", None)], seller=e["v2"])
    c0 = cl(0, "-2.50")
    cl(1)
    c2 = cl(2, "1.25")
    clock.day(10)
    parts = adm.get("/finance/installments/", {"title__customer": ana, "ordering": "due_date"})["results"]
    p = [q for q in parts if D(q["amount"]) == 100]
    adm.post(f"/finance/installments/{p[0]['id']}/settle/", {"financial_account": str(bank.pk), "amount": "102.5", "interest": "1.5", "fine": "1"})
    adm.post(f"/finance/installments/{p[1]['id']}/settle/", {"financial_account": str(bank.pk), "amount": "40", "discount": "5"})
    adm.post(f"/finance/installments/{p[1]['id']}/unsettle/", {"reason": "erro"})
    adm.post(f"/finance/installments/{p[1]['id']}/settle/", {"financial_account": str(vaults[0].pk), "amount": "60"})
    card = Installment.all_objects.filter(title__payment__method__kind="credit_card").exclude(status="cancelled").order_by("due_date").first()
    adm.post(f"/finance/installments/{card.pk}/settle/", {"financial_account": str(bank.pk), "amount": str(card.amount)})
    doc(adm, "exit", W1, [{"variant": str(meat.pk), "quantity": "0.333"}], exit_reason="loss")
    doc(adm2, "exit", W2, [{"variant": str(yog.pk), "quantity": "2"}], exit_reason="expiration")
    doc(adm, "inventory", W1, [{"variant": str(soda.pk), "quantity": str(stock.available(soda, W1) - 3)},
                               {"variant": str(mug.pk), "quantity": str(stock.available(mug, W1) + 2)},
                               {"variant": str(yog.pk), "quantity": str(stock.available(yog, W1) + 2)}])
    dd = doc(adm, "exit", W1, [{"variant": str(promo.pk), "quantity": "1"}], exit_reason="consumption")
    adm.post(f"/stock/documents/{dd['id']}/cancel/", {"reason": "x"})
    rent = FinancialCategory.all_objects.create(account=a, name="AluguelX", kind="expense")
    inc = FinancialCategory.all_objects.create(account=a, name="ServX", kind="income")
    t = adm.post("/finance/titles/", {"kind": "payable", "description": "Luz", "total": "300.01", "installment_count": 3,
                                      "first_due": "2026-10-15", "category": str(rent.pk)})
    t0 = t["installments"][0]
    adm.post(f"/finance/installments/{t0['id']}/settle/", {"financial_account": str(bank.pk), "amount": t0["amount"]})

    def tx(acc, kind, amount, cat):
        return adm.post("/finance/transactions/", {"financial_account": str(acc.pk), "kind": kind, "amount": amount,
                                                   "date": "2026-10-10", "description": "x", "category": str(cat.pk)})
    tx(vaults[0], "out", "12", rent)
    z = tx(vaults[0], "out", "77", rent)
    adm.post(f"/finance/transactions/{z['id']}/reverse/")
    tx(bank, "in", "45.67", inc)
    adm.post("/finance/accounts/transfer/", {"source": str(vaults[0].pk), "target": str(bank.pk), "amount": "30", "description": "dep"})
    adm.post("/finance/recurring/", {"kind": "payable", "description": "Aluguel", "amount": "150", "frequency": "monthly",
                                     "due_day": 20, "start_date": "2026-10-01", "lead_days": 10, "category": str(rent.pk)})
    adm.post("/finance/recurring/generate-all/")
    for s_ in (e["v1"], e["v2"]):
        adm.post("/commissions/payout/", {"seller": s_.pk, "financial_account": str(bank.pk)})
    clock.day(20)
    op(0, str(c0)), op(2, str(c2))
    y1 = sell(A1, [(meat, "0.457"), (promo, "1"), (kit, "1")], [("cash", "20"), ("credit_card", None)], seller=e["v1"], customer=ana)
    ret(A1, y1, [(2, "1")], "store_credit")
    sell(A3, [(soda, "1", {"discount": "0.36", "approval": AP}), (mug, "1")], [("pix", None)], seller=e["v2"], disc="1.99")
    ret(A1, x4, [(0, "1"), (1, "1")], "store_credit")
    cl(0)
    cl(2)

    # ---- identidades
    P = {"date_from": "2026-10-01", "date_to": "2026-10-31"}
    net = e["net"]
    done = Sale.all_objects.filter(account=a, status="completed")
    rev = sum(s.total for s in done)

    def tot(qs, f="quantity"):
        return qs.aggregate(t=Sum(f))["t"] or D(0)
    for v in (soda, yog, meat, mug, promo, ward):
        for w in (W1, W2):
            b = stock.available(v, w)
            check(f"saldo=kardex {v.sku}", b, tot(StockMovement.all_objects.filter(variant=v, warehouse=w)))
            if v == yog:
                check(f"saldo=lotes {w.store}", b, tot(StockLot.all_objects.filter(variant=v, warehouse=w)))
    for acc in FinancialAccount.all_objects.filter(account=a):
        st = net.get(f"/finance/accounts/{acc.pk}/statement/", P)
        check(f"extrato {acc.name}", st["closing_balance"], acc.opening_balance + sum(
            (x.amount if x.kind == "in" else -x.amount) for x in acc.transactions.filter(deleted_at=None)))
    bl = {r["name"]: r["balance"] for r in net.get("/reports/balances/")["accounts"]}
    for s, vault, opening, extra in ((s1, vaults[0], D(1000), D(60) - 12 - 30), (s2, vaults[1], D(500), D(0))):
        ss = CashSession.all_objects.filter(store=s)
        m = CashMovement.all_objects.filter(session__in=ss, status="approved")
        check(f"cofre {s}", bl[vault.name], opening + tot(m.filter(kind="sale"), "amount") - tot(m.filter(kind="refund"), "amount")
              + sum(x.difference for x in ss) + extra)
    op_ = sum(i.balance for i in Installment.all_objects.filter(account=a, title__kind="receivable", status__in=["open", "partial"]))
    check("aging", sum(D(x) for x in net.get("/reports/aging/")["receivable"].values()), op_)
    for t_ in FinancialTitle.all_objects.filter(account=a):
        check("titulo=parcelas", t_.total, sum(i.amount for i in t_.installments.all()))
    d, d1, d2 = net.get("/reports/dre/", P), adm.get("/reports/dre/", P), adm2.get("/reports/dre/", P)
    items = SaleItem.all_objects.filter(sale__in=done, status="active")
    rets = SaleReturn.all_objects.filter(account=a, status="completed")
    check("dre bruto", d["gross_revenue"], sum(i.total for i in items))
    check("dre dev", d["returns"], sum(r.total for r in rets))
    check("dre liquida", d["net_revenue"], rev - sum(r.total for r in rets) + D("45.67") + D("2.5"))
    check("cmv", d["cmv"], sum(i.unit_cost * i.quantity for i in items) - sum(
        r.sale_item.unit_cost * r.quantity for r in SaleReturnItem.all_objects.filter(sale_return__in=rets, restock=True)), "0.01")
    kardex = sum((m.total_cost if m.quantity < 0 else -m.total_cost) for m in StockMovement.all_objects.filter(
        account=a, kind__in=["sale", "sale_return"]).exclude(sale_item__sale__status="cancelled"))
    check("cmv=kardex", d["cmv"], kardex, "0.50")
    com = Commission.all_objects.filter(account=a).exclude(status="cancelled")
    check("dre comissao", d["commissions"], sum(c.amount for c in com))
    for s_ in done:
        for i in s_.items.filter(status="active"):
            rows = com.filter(sale_item=i)
            rq = sum((r.quantity for r in SaleReturnItem.all_objects.filter(sale_item=i, sale_return__in=rets)), D(0))
            if rq == i.quantity and rows:
                check(f"comissao zera {i.sku} {i.quantity}", sum(r.amount for r in rows), 0)
    check("comissao paga", tot(FinancialTransaction.all_objects.filter(account=a, category__system_key="commissions"), "amount"),
          sum(c.amount for c in com.filter(status="paid")))
    check("dre taxas", d["card_fees"], sum(x.amount * x.fee_rate / 100 for x in Payment.all_objects.filter(sale__in=done, status="approved")), "0.01")
    check("dre dif", d["cash_differences"], "-1.25")
    for k in ("gross_revenue", "freight", "discounts", "returns", "cmv", "card_fees", "commissions", "cash_differences"):
        check(f"dre filiais {k}", d[k], D(d1[k]) + D(d2[k]), "0.02")
    cf = net.get("/reports/book/fechamento/", P)
    K = {k["label"]: k["value"] for k in cf["kpis"]}
    check("fech=dre", K["Resultado"], d["operating_result"], "0.01")
    check("fech fat", K["Faturamento total"], d["net_revenue"], "0.01")
    ccost = next(b for b in cf["blocks"] if b["title"] == "Custos por categoria")["rows"]
    check("fech custos", sum(D(r["value"]) for r in ccost) - D(d["cash_differences"]), K["Custo total"], "0.03")

    def kp(slug, label):
        return next(x["value"] for x in net.get(f"/reports/book/{slug}/", P)["kpis"] if x["label"] == label)

    def rows(slug, title):
        return next(b for b in net.get(f"/reports/book/{slug}/", P)["blocks"] if b["title"].startswith(title))["rows"]

    def col(slug, title, key):
        return sum(D(r[key]) for r in rows(slug, title))
    s_ = net.get("/reports/summary/", P)
    check("summary", s_["revenue"], rev)
    check("vendas", kp("vendas", "Faturamento"), rev)
    check("dia", sum(D(r["revenue"]) for r in net.get("/reports/sales-by-day/", P)), rev)
    check("forma", kp("recebimentos", "Total recebido"), rev)
    check("forma tab", col("recebimentos", "Resumo", "value"), rev)
    check("filial", col("filiais", "Filiais", "revenue"), rev)
    check("vendedor", col("vendedores", "Vendedores", "revenue"), rev)
    check("comissao rel", kp("vendedores", "Comissões"), sum(c.amount for c in com.filter(sale__in=done)))
    netrev = sum(x.total - x.freight for x in done) + sum(x.coupon_discount for x in done if x.coupon and x.coupon.kind == "free_shipping")
    check("categoria", col("categorias", "Categorias", "revenue"), netrev, "0.03")
    check("abc", col("curva-abc", "Curva completa", "revenue"), netrev, "0.03")
    mar = D(s_["gross_margin"])
    for sl, t_ in (("vendas", "Produtos vendidos"), ("curva-abc", "Curva completa"), ("categorias", "Categorias"), ("filiais", "Filiais")):
        check("margem " + sl, col(sl, t_, "margin"), mar, "0.03")

    def num(x):
        x = x.replace("R$", "").replace("\xa0", "").strip()
        try:
            return D(x.replace(".", "").replace(",", ".")) if "," in x else D(x)
        except Exception:
            return None
    for sl in ("vendas", "vendedores", "filiais", "recebimentos", "fechamento", "dre", "categorias", "curva-abc", "clientes", "descontos"):
        rep = net.get(f"/reports/book/{sl}/", P)
        for i, b in enumerate(rep["blocks"]):
            if b["type"] != "table":
                continue
            c = net.c.get(f"{V}/reports/book/{sl}/export/", {**P, "formato": "csv", "bloco": i}).content.decode("utf-8-sig")
            n = [r for r in csv.reader(io.StringIO(c), delimiter=";") if r]
            if len(n) < len(b["rows"]):
                bad.append(("export", sl, b["title"], len(n), len(b["rows"])))
            for co in b["columns"]:
                if co.get("format") != "money" or not b["rows"]:
                    continue
                ix = next((j for h in n for j, x in enumerate(h) if x == co["label"]), None)
                if ix is None:
                    bad.append(("col", sl, b["title"], co["label"], n[:1]))
                    continue
                scr = sum(D(str(r.get(co["key"]) or 0)) for r in b["rows"])
                exp = sum((x for x in (num(r[ix]) for r in n if len(r) > ix) if x is not None), D(0))
                if abs(scr - exp) > D("0.05"):
                    bad.append(("export soma", sl, b["title"], co["label"], str(scr), str(exp)))

    class Act:
        pass
    ac = Act()
    ac.user, ac.account, ac.store = ctx.admin, a, None
    with ctx.tenant():
        def q(ds, m, *g):
            return sum(D(str(r[m])) for r in datasets.query(ac, ds, metrics=[m], group_by=list(g), **P)["rows"])
        for g in ((), ("filial",), ("vendedor",), ("dia",)):
            check(f"cosmos fat {g}", q("vendas", "faturamento", *g), rev)
        check("cosmos dev", q("devolucoes", "valor"), d["returns"])
        check("cosmos margem", q("itens_vendidos", "margem", "categoria"), mar, "0.05")
    cred = tot(CustomerCredit.all_objects.filter(customer=ana, deleted_at=None), "amount")
    back = sum(r.total for r in rets.filter(customer=ana, refund_method__in=["store_credit", "exchange"]))
    used = tot(Payment.all_objects.filter(method__kind="store_credit", status="approved"), "amount")
    check("carteira", cred, back - used)
    for sid in closed:
        api = adm if CashSession.all_objects.get(pk=sid).store_id == s1.pk else adm2
        z = api.get(f"/cash/sessions/{sid}/report/")
        dr = z["drawer"]
        check("Z gaveta", D(dr["opening"]) + D(dr["sale"]) + D(dr["supply"]) - D(dr["withdrawal"]) - D(dr["refund"]), dr["expected"])
        check("Z vendas=formas", z["sales"]["total"], sum(D(m["total"]) for m in z["by_payment_method"]))
    c = net.get("/reports/cash-flow/", P)
    check("fluxo", c["closing_balance"], sum(D(x) for x in bl.values()))
    assert not bad, "\n".join(map(str, bad))
