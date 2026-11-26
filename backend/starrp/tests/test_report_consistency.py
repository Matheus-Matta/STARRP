"""Rodada 6: o MESMO número em toda tela, filtro, export e na Cosmos."""
from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from starrp.models import (
    Category, Commission, Coupon, Customer, CustomerGroup, FinancialAccount, FinancialTransaction, Payment,
    PaymentMethod, Sale, SaleItem, SaleReturn, SaleReturnItem, Store,
)
from starrp.services import dre, finance, report_book as rb, report_export, report_promotions, reports
from starrp.services.cosmos import datasets

SP = ZoneInfo("America/Sao_Paulo")
P = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


def dt(*k):
    return datetime(*k, tzinfo=SP)


def kp(r, label):
    return next(k["value"] for k in r["kpis"] if k["label"] == label)


def bl(r, title):
    return next(b for b in r["blocks"] if b["title"].startswith(title))


class O:
    pass


@pytest.fixture
def S(ctx):
    a = ctx.account
    a.extra_modules = ["stock", "finance", "pricing", "inbound_nfe"]
    a.save()
    with ctx.tenant():
        yield build(ctx, a)


def build(ctx, a):
    s, s2 = ctx.store, Store.all_objects.create(account=a, name="Filial 2", rule=ctx.store.rule)
    c1 = Category.all_objects.create(account=a, name="Moveis")
    c2 = Category.all_objects.create(account=a, name="Decor")
    A_ = ctx.product(name="Mesa", price="100.00", sku="MESA", category=c1)
    B_ = ctx.product(name="Vaso", price="50.00", sku="VASO", category=c2)
    Z, Y = (Customer.all_objects.create(account=a, name=x) for x in ("Ze", "Ana"))
    v1, v2 = ctx.user("v1", "seller", is_seller=True), ctx.user("v2", "seller", is_seller=True)
    fs = Coupon.all_objects.create(account=a, code="FRETE", name="f", kind="free_shipping", value=0)
    cp = Coupon.all_objects.create(account=a, code="DEZ", name="d", kind="percent", value=10)
    m = ctx.methods
    card = next(x for x in m.values() if x.kind == "credit_card")
    PaymentMethod.all_objects.filter(pk=card.pk).update(fee_percent=D("3"))
    card.refresh_from_db()
    n = [0]

    def sale(store, when, items, cust, seller, disc=0, coupon=None, cd=0, fr=0, pays=None, status="completed"):
        n[0] += 1
        sub = sum(D(q) * D(p) - D(d) for _, q, p, d, _c in items)
        t = sub - D(disc) - D(cd) + D(fr)
        x = Sale.all_objects.create(
            account=a, store=store, number=900 + n[0], channel="pos", status=status, operator=ctx.admin, seller=seller,
            customer=cust, customer_name=cust.name if cust else "", subtotal=sub, discount=disc, coupon=coupon,
            coupon_code=coupon.code if coupon else "", coupon_discount=cd, freight=fr, total=t, paid_amount=t,
            completed_at=when if status == "completed" else None, cancelled_at=when if status == "cancelled" else None)
        for v, q, p, d, c in items:
            SaleItem.all_objects.create(account=a, sale=x, variant=v, description=v.sku, sku=v.sku, quantity=q,
                                        list_price=p, unit_price=p, discount=d, total=D(q) * D(p) - D(d), unit_cost=c)
        SaleItem.all_objects.create(account=a, sale=x, variant=B_, description="x", quantity=1, list_price=77,
                                    unit_price=77, total=77, unit_cost=40, status="cancelled")
        for meth, am in pays or [(m["pix"], t)]:
            Payment.all_objects.create(account=a, store=store, sale=x, method=meth, amount=t if am is None else am)
        if seller:
            Commission.all_objects.create(account=a, store=store, seller=seller, sale=x, base_amount=t, rate=5,
                                          amount=t * 5 / 100)
        return x

    R = [sale(s, dt(2026, 10, 1, 0, 10), [(A_, 2, 100, 0, 60)], Z, v1, disc=20),
         sale(s, dt(2026, 10, 31, 23, 50), [(A_, 1, 100, 10, 60), (B_, 2, 50, 0, 20)], Y, v2, coupon=cp, cd=19, fr=30,
              pays=[(m["cash"], D(101)), (card, D(100))]),
         sale(s2, dt(2026, 10, 15, 12), [(B_, 4, 50, 0, 20)], Z, v1, coupon=fs, cd=25, fr=25, pays=[(card, None)]),
         sale(s2, dt(2026, 10, 16, 22, 30), [(A_, 1, 100, 0, 60)], None, None)]
    sale(s, dt(2026, 9, 30, 23, 59), [(A_, 5, 100, 0, 60)], Z, v1)
    sale(s, dt(2026, 11, 1, 0, 1), [(A_, 5, 100, 0, 60)], Z, v1)
    sale(s, dt(2026, 10, 10, 10), [(A_, 1, 100, 0, 60)], Z, v1, status="cancelled")
    o = O()
    o.__dict__.update(a=a, s=s, s2=s2, c1=c1, c2=c2, R=R, card=card, v1=v1, v2=v2, rev=sum(x.total for x in R),
                      cost=D(120 + 60 + 40 + 80 + 60), ctx=ctx, Z=Z, Y=Y, A=A_, B=B_)
    o.net = sum(x.total - x.freight for x in R) + D(25)  # frete gratis abate o frete
    o.margin = o.net - o.cost
    return o


def actor(S):
    ac = O()
    ac.user, ac.account, ac.store = S.ctx.admin, S.a, None
    return ac


def test_faturamento_igual(S):
    v = rb.movement_sales(S.a, None, P)
    assert kp(v, "Faturamento") == S.rev
    assert sum(bl(v, "Faturamento por dia")["series"][0]["values"]) == S.rev
    assert sum(r["total"] for r in bl(v, "Vendas do")["rows"]) == S.rev
    assert sum(r["value"] for r in bl(v, "Faturamento por canal")["rows"]) == S.rev
    assert kp(rb.movement_branches(S.a, S.s, P), "Faturamento da rede") == S.rev
    assert sum(sum(x) for x in rb.movement_hours(S.a, None, P)["blocks"][0]["values"]) == S.rev
    assert kp(rb.movement_payments(S.a, None, P), "Total recebido") == S.rev
    assert reports.summary(S.a, None, P)["revenue"] == S.rev
    assert [str(r["day"]) for r in reports.by_day(S.a, None, P)] == ["2026-10-01", "2026-10-15", "2026-10-16", "2026-10-31"]
    d = dre.build(S.a, None, P)
    assert d["net_revenue"] == S.rev and d["cmv"] == S.cost
    for st in (S.s, S.s2):
        assert reports.summary(S.a, st, P)["revenue"] == sum(x.total for x in S.R if x.store_id == st.pk)


def test_categorias_faturamento(S):
    assert kp(rb.goods_categories(S.a, None, P), "Faturamento") == S.net


def test_margem_kpi(S):
    assert kp(rb.movement_sales(S.a, None, P), "Margem bruta") == S.margin
    assert reports.summary(S.a, None, P)["gross_margin"] == S.margin


def test_margem_dre(S):
    d = dre.build(S.a, None, P)
    assert d["gross_profit"] - d["freight"] + 25 == S.margin


def test_margem_tabela_mesmo_relatorio(S):
    v = rb.movement_sales(S.a, None, P)
    assert sum(r["margin"] for r in bl(v, "Produtos vendidos")["rows"]) == S.margin


def test_margem_abc(S):
    assert sum(r["margin"] for r in bl(rb.goods_abc(S.a, None, P), "Curva completa")["rows"]) == S.margin


def test_margem_categorias(S):
    assert sum(r["margin"] for r in bl(rb.goods_categories(S.a, None, P), "Categorias")["rows"]) == S.margin


def test_margem_filiais(S):
    assert sum(r["margin"] for r in bl(rb.movement_branches(S.a, None, P), "Filiais")["rows"]) == S.margin


def test_margem_top_products(S):
    assert sum(r["margin"] for r in reports.top_products(S.a, None, P)) == S.margin


def test_margem_promocoes(S):
    assert sum(r["profit"] for r in report_promotions._sale_rows(rb._sales(S.a, None, P))) == S.margin


def test_margem_cosmos(S):
    r = datasets.query(actor(S), "itens_vendidos", metrics=["margem"], date_from="2026-10-01", date_to="2026-10-31")
    assert str(S.margin) in str(r), r


def test_filtro_cat_vendas_grafico(S):
    v = rb.movement_sales(S.a, None, {**P, "category": str(S.c1.pk)})
    assert sum(bl(v, "Faturamento por dia")["series"][0]["values"]) == kp(v, "Faturamento")


def test_filtro_cat_soma(S):
    tot = sum(kp(rb.movement_sales(S.a, None, {**P, "category": str(c.pk)}), "Faturamento") for c in (S.c1, S.c2))
    assert abs(tot - S.net) <= D("0.02")


def test_filtro_cat_desconto(S):
    t = sum(kp(rb.movement_sales(S.a, None, {**P, "category": str(c.pk)}), "Descontos concedidos") for c in (S.c1, S.c2))
    assert t <= kp(rb.movement_sales(S.a, None, P), "Descontos concedidos")


def test_filtro_cat_vendedores(S):
    t = sum(kp(rb.movement_sellers(S.a, None, {**P, "category": str(c.pk)}), "Vendido com vendedor") for c in (S.c1, S.c2))
    assert t <= kp(rb.movement_sellers(S.a, None, P), "Vendido com vendedor")


def test_filtro_cat_filiais(S):
    t = sum(kp(rb.movement_branches(S.a, None, {**P, "category": str(c.pk)}), "Faturamento da rede") for c in (S.c1, S.c2))
    assert t <= S.rev


def test_filtro_cat_horas(S):
    t = sum(sum(sum(x) for x in rb.movement_hours(S.a, None, {**P, "category": str(c.pk)})["blocks"][0]["values"])
            for c in (S.c1, S.c2))
    assert t <= S.rev


def test_filtro_forma_anterior(S):
    Payment.all_objects.filter(sale__completed_at__month=11).update(method=S.card, fee_percent=3)
    p = {"date_from": "2026-11-01", "date_to": "2026-11-30", "method": str(S.card.pk)}
    k = next(x for x in rb.movement_payments(S.a, None, p)["kpis"] if x["label"] == "Total recebido")
    ant = kp(rb.movement_payments(S.a, None, {**p, "date_from": "2026-10-02", "date_to": "2026-10-31"}), "Total recebido")
    assert k["delta"] == rb._delta(k["value"], ant)


def test_taxas(S):
    assert kp(rb.movement_payments(S.a, None, P), "Taxas estimadas") == D("9.00") == dre.build(S.a, None, P)["card_fees"]


def test_desconto_todas(S):
    d = dre.build(S.a, None, P)["discounts"]
    assert kp(rb.movement_sales(S.a, None, P), "Descontos concedidos") == d == reports.summary(S.a, None, P)["discounts"]
    assert sum(r["discount"] for r in bl(rb.movement_sellers(S.a, None, P), "Vendedores")["rows"]) == d


def test_desconto_geral_manual(S):
    r = rb.BOOK["descontos"][0](S.a, None, P)
    assert kp(r, "Em cupons") + kp(r, "Em desconto manual") == 20 + 19 + 25 + 10  # inclui o de item (documentado la)


def test_desconto_pct_vendedor(S):
    a = {r["name"]: r["discount_pct"] for r in bl(rb.movement_sellers(S.a, None, P), "Vendedores")["rows"]}
    b = {r["label"]: r["discount"] for r in rb.BOOK["cruzamento-vendedores"][0](S.a, None, P)["blocks"][1]["rows"]}
    assert a == b


def test_margem_pct_vendedor(S):
    r = rb.BOOK["cruzamento-vendedores"][0](S.a, None, P)["blocks"][1]["rows"]
    assert next(x for x in r if x["label"] == "V2")["margin_pct"] == rb._pct(D(171 - 100), D(171)), r


def test_margem_pct_desconto(S):
    r = rb.BOOK["cruzamento-descontos"][0](S.a, None, P)["blocks"][1]["rows"]
    tot = report_promotions.overview(S.a, None, P)["blocks"][1]["rows"]
    assert next(x for x in r if x["label"] == "5% a 10%")["margin_pct"] == rb._pct(180 - 120 + 171 - 100, 180 + 171), (r, tot)


def test_ultima_compra_fuso(S):
    x = next(i for i in bl(rb.relationship_customers(S.a, None, P), "Os que mais")["rows"] if i["label"] == "Ana")
    assert "31/10" in x["sub"], x


def test_comissao(S):
    c = sum(x.total for x in S.R if x.seller_id) * 5 / 100
    assert kp(rb.movement_sellers(S.a, None, P), "Comissões") == c == sum(r["commission"] for r in reports.by_seller(S.a, None, P))


@pytest.mark.parametrize("k", ["category", "method", "brand", "product", "customer_group", "seller", "channel",
                               "warehouse", "supplier", "financial_account", "measure", "store"])
def test_lixo_nao_500(S, k):
    cli = S.ctx.client()
    cli.raise_request_exception = False
    bad = [s for s in rb.BOOK if cli.get(f"/api/v1/reports/book/{s}/", {**P, k: "lixo"}).status_code >= 500]
    assert not bad, bad


def test_export_todos(S):
    for f, _, _ in rb.BOOK.values():
        r = f(S.a, None, P)
        assert report_export.to_xlsx(r, {}, charts=True)
        report_export.to_csv(r)


def test_fluxo_conta_categorias(S):
    a = FinancialAccount.all_objects.filter(account=S.a, kind="bank").first()
    b = FinancialAccount.all_objects.create(account=S.a, name="B2", kind="bank")
    for x, v in ((a, 10), (b, 90)):
        FinancialTransaction.all_objects.create(account=S.a, financial_account=x, kind="in", amount=v,
                                                date="2026-10-05", description="x")
    r = rb.ledger_cash_flow(S.a, None, {**P, "financial_account": str(a.pk)})
    assert kp(r, "Entradas") == sum(x["value"] for x in bl(r, "Entradas por categoria")["rows"])


def test_cosmos_em_aberto_cancelada(S):
    t = finance.create_title(store=S.s, kind="receivable", description="x", total=D(100))
    finance.cancel_title(t, S.ctx.admin)
    r = datasets.query(actor(S), "contas", metrics=["em_aberto"], date_from="2026-01-01", date_to="2027-12-31")
    assert "100" not in str(r.get("rows", r)), r


def test_devolucoes(S):
    it = S.R[0].items.filter(status="active").first()
    for rs, q in ((True, D(1)), (False, D("0.5"))):
        x = SaleReturn.all_objects.create(account=S.a, store=S.s, number=int(rs) + 1, sale=S.R[0], customer=S.Z,
                                          status="completed", refund_method="store_credit", reason="r", total=90 * q,
                                          completed_at=dt(2026, 10, 31, 23, 30))
        SaleReturnItem.all_objects.create(account=S.a, sale_return=x, sale_item=it, quantity=q, unit_price=90,
                                          total=90 * q, restock=rs)
    d, canc = dre.build(S.a, None, P), rb.movement_cancellations(S.a, None, P)
    assert d["returns"] == 135 == reports.summary(S.a, None, P)["returns_total"] == kp(canc, "Valor devolvido")
    assert d["cmv"] == S.cost - 60
    assert sum(bl(canc, "Cancelado e")["series"][1]["values"]) == 135


def test_resumo_filtro_vendedor(S):
    p = {**P, "seller": str(S.v2.pk)}
    assert reports.summary(S.a, None, p)["cancelled_count"] == kp(rb.movement_cancellations(S.a, None, p), "Vendas canceladas")


def test_filtro_grupo(S):
    g1 = CustomerGroup.all_objects.create(account=S.a, name="g1")
    S.Z.groups.add(g1)
    v = rb.movement_sales(S.a, None, {**P, "customer_group": str(g1.pk)})
    t = S.R[0].total + S.R[2].total
    assert kp(v, "Faturamento") == t == sum(bl(v, "Faturamento por dia")["series"][0]["values"])
    assert t == sum(r["value"] for r in bl(v, "Faturamento por canal")["rows"])


def test_subtotal_zero(S):
    x = S.R[3]
    x.items.update(total=0, unit_price=0)
    Sale.all_objects.filter(pk=x.pk).update(subtotal=0, total=0)
    assert kp(rb.movement_sales(S.a, None, P), "Margem bruta") == S.margin - 100
