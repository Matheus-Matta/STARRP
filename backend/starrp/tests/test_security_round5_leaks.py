"""Rodada 5b: vazamento de custo, fechamento cego, escopo, WMS, entradas estranhas."""
import json

import pytest
from django.utils import timezone

from starrp.models import (
    AuditLog, BinBalance, Notification, Permission, Sale, StockBalance, StockMovement, StorageBin, Warehouse,
)
from starrp.services import cash, stock
from starrp.services.provisioning import create_store

from .test_security_round5_finance import A, D, _mods, sale, stocked  # noqa: F401


def custo_user(ctx, role="assets", *codes):
    u = ctx.user("curioso", role)
    for c in codes:
        u.profile.extra_permissions.add(Permission.objects.get(code=c))
    return u


def test_l01_dre_do_livro_sem_custo(ctx):
    v = stocked(ctx, price="100.00", cost="61.37")
    sale(ctx, ctx.client(), [(v, "1")])
    u = custo_user(ctx, "assets", "sales.view", "sales.view_all")
    r = ctx.client(u).get(f"{A}/reports/book/dre/")
    assert r.status_code == 200, r.json()
    assert "61.37" not in r.content.decode(), [b["title"] for b in r.json()["blocks"] if "61.37" in json.dumps(b)]


def test_l01b_fechamento_sem_custo(ctx):
    v = stocked(ctx, price="100.00", cost="61.37")
    sale(ctx, ctx.client(), [(v, "1")])
    u = custo_user(ctx, "assets", "sales.view", "sales.view_all")
    r = ctx.client(u).get(f"{A}/reports/book/fechamento/")
    assert r.status_code == 200, r.json()
    assert "61.37" not in r.content.decode(), [b["title"] for b in r.json()["blocks"] if "61.37" in json.dumps(b)]


def test_l02_vendedor_descobre_custo_no_relatorio_de_descontos(ctx):
    v = stocked(ctx, price="50.00", cost="61.37")
    seller = ctx.user("vend", "seller", is_seller=True)
    api = ctx.client(seller)
    sid = api.post(f"{A}/sales/", {}, format="json").json()["id"]
    api.post(f"{A}/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
    r = ctx.client().post(f"{A}/sales/{sid}/checkout/", {"payments": [
        {"nsu": "1", "method": str(ctx.methods["pix"].pk), "amount": "50.00"}]}, format="json")
    assert r.status_code == 200, r.json()
    r = api.get(f"{A}/reports/book/descontos/")
    assert r.status_code == 200
    t = r.content.decode()
    assert "11.37" not in t and "11,37" not in t, [b for b in r.json()["blocks"] if "11.37" in json.dumps(b)]


def test_l02b_varredura_de_custo_em_todos_os_relatorios(ctx):
    from starrp.services import report_book
    from starrp.views.reports import REPORTS
    v = stocked(ctx, price="100.00", cost="61.37")
    api = ctx.client()
    sale(ctx, api, [(v, "1")])
    sale(ctx, api, [(v, "1")], discount="45.00")
    u = custo_user(ctx, "manager")
    ctx.user_role("manager").permissions.remove(Permission.objects.get(code="catalog.view_costs"))
    c = ctx.client(u)
    bad = {}
    nums = ("61.37", "61,37", "38.63", "6.37", "6,37", "122.74", "122,74", "77.26", "32.26", "32,26", "38.6", "38,6",
            "20.8", "20,8")
    for name in list(report_book.BOOK):
        r = c.get(f"{A}/reports/book/{name}/")
        t = r.content.decode()
        hits = [x for x in nums if x in t]
        if hits:
            bad[name] = (hits, [b.get("title") for b in r.json().get("blocks", [])
                                if any(h in json.dumps(b, ensure_ascii=False) for h in hits)])
    for name in REPORTS:
        t = c.get(f"{A}/reports/{name}/").content.decode()
        hits = [x for x in ("61.37", "38.63", "122.74", "77.26", "32.26") if x in t]
        if hits:
            bad["raw " + name] = hits
    assert not bad, "\n".join(f"{k}: {v}" for k, v in bad.items())


def test_l03_documento_de_estoque_sem_custo(ctx):
    v = ctx.product(name="Mesa", price="100.00")
    wh = stock.default_warehouse(ctx.store)
    r = ctx.client().post(f"{A}/stock/documents/", {
        "kind": "entry", "warehouse": str(wh.pk), "effective_date": str(timezone.localdate()),
        "items": [{"variant": str(v.pk), "quantity": "1", "unit_cost": "61.37"}]}, format="json")
    assert r.status_code == 201, r.json()
    doc = r.json()["id"]
    ctx.client().post(f"{A}/stock/documents/{doc}/post/", {}, format="json")
    r = ctx.client(ctx.user("log", "logistics_lead")).get(f"{A}/stock/documents/{doc}/")
    assert r.status_code == 200
    assert "61.37" not in r.content.decode(), r.json()["items"]


def test_l04_auditoria_do_ti_sem_custo_nem_gaveta(ctx):
    v = stocked(ctx)
    for entity, key, val in (("productvariant", "average_cost", "61.37"), ("cashsession", "expected_amount", "777.77")):
        AuditLog.all_objects.create(account=ctx.account, store=ctx.store, action="updated", entity=entity,
                                    object_id=str(v.pk), changes={"fields": [{"key": key, "from": "10", "to": val}]})
    r = ctx.client(ctx.user("ti", "it")).get(f"{A}/audit-logs/")
    assert r.status_code == 200
    t = r.content.decode()
    assert "61.37" not in t and "777.77" not in t, t[:400]


def _cego(ctx):
    ctx.require_cash()
    v = ctx.product(name="X", price="123.45", track_stock=False)
    u = ctx.user("cx", "cashier")
    ctx.link(u)
    s = cash.open_session(ctx.register, u, D("0"))
    api = ctx.client(u)
    sid = api.post(f"{A}/sales/", {}, format="json").json()["id"]
    api.post(f"{A}/sales/{sid}/items/", {"variant": str(v.pk)}, format="json")
    r = api.post(f"{A}/sales/{sid}/checkout/", {"payments": [
        {"method": str(ctx.methods["cash"].pk), "amount": "123.45", "tendered": "123.45"}]}, format="json")
    assert r.status_code == 200, r.json()
    return api, s


@pytest.mark.parametrize("path", ["reports/payment-methods/", "reports/dashboard/", "reports/book/recebimentos/"])
def test_l05_fechamento_cego_por_relatorio(ctx, path):
    api, _s = _cego(ctx)
    r = api.get(f"{A}/{path}")
    t = r.content.decode()
    assert r.status_code == 403 or not ("123.45" in t and "inheiro" in t), t[:300]


def test_l06_notificacao_da_outra_filial(ctx):
    sb = create_store(ctx.account, "Filial B")
    ger_b = ctx.user("gerb", "manager", stores=[sb])
    cx = ctx.user("cx", "cashier")
    from starrp.services.offline_sales import _flag
    s = Sale.all_objects.create(account=ctx.account, store=ctx.store, number=9)
    _flag(s, cx, ["Desconto de 90% sem autorizacao"])
    assert not Notification.all_objects.filter(recipient=ger_b).exists()


def _bins(ctx):
    wh = stock.default_warehouse(ctx.store)
    Warehouse.all_objects.filter(pk=wh.pk).update(uses_bins=True)
    wh.refresh_from_db()
    b = StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="A")
    v = ctx.product(name="X", price="10")
    stock.move(v, wh, D(10), StockMovement.Kind.PURCHASE, unit_cost=D(1), bin=b)
    return wh, b, v, ctx.client(ctx.user("est", "stockist"))


def test_l07_endereco_com_saldo_nao_muda_de_deposito(ctx):
    wh, b, v, api = _bins(ctx)
    wh2 = Warehouse.all_objects.create(account=ctx.account, store=ctx.store, name="D2", uses_bins=True)
    r = api.patch(f"{A}/stock/bins/{b.pk}/", {"warehouse": str(wh2.pk)}, format="json")
    t = sum(x.quantity for x in BinBalance.all_objects.filter(bin__warehouse=wh, variant=v))
    assert t == StockBalance.all_objects.get(variant=v, warehouse=wh).quantity, (r.status_code, t)


def test_l07b_endereco_com_saldo_nao_exclui(ctx):
    _wh, b, _v, api = _bins(ctx)
    assert api.delete(f"{A}/stock/bins/{b.pk}/").status_code != 204


def test_l07c_endereco_com_saldo_desativado(ctx):
    _wh, b, _v, api = _bins(ctx)
    r = api.patch(f"{A}/stock/bins/{b.pk}/", {"is_active": False}, format="json")
    assert r.status_code >= 400, r.status_code


def test_l08_deposito_com_saldo_nao_muda_de_filial(ctx):
    sb = create_store(ctx.account, "Filial B")
    wh = stock.default_warehouse(ctx.store)
    v = ctx.product(name="X", price="10")
    stock.move(v, wh, D(10), StockMovement.Kind.PURCHASE, unit_cost=D(1))
    u = ctx.user("est", "stockist", stores=[ctx.store, sb])
    r = ctx.client(u).patch(f"{A}/stock/warehouses/{wh.pk}/", {"store": str(sb.pk)}, format="json")
    wh.refresh_from_db()
    assert wh.store_id == ctx.store.pk, r.status_code


def test_l08b_liga_enderecos_com_saldo(ctx):
    wh = stock.default_warehouse(ctx.store)
    v = ctx.product(name="X", price="10")
    stock.move(v, wh, D(10), StockMovement.Kind.PURCHASE, unit_cost=D(1))
    StorageBin.all_objects.create(account=ctx.account, warehouse=wh, code="A")
    r = ctx.client(ctx.user("est", "stockist")).patch(f"{A}/stock/warehouses/{wh.pk}/", {"uses_bins": True}, format="json")
    total = sum(x.quantity for x in BinBalance.all_objects.filter(bin__warehouse=wh, variant=v))
    assert r.status_code >= 400 or total == 10, (r.status_code, total)


def _dataset(ctx, u):
    from starrp.core.tenant import set_own_sales_user
    from starrp.services.cosmos import datasets

    class Actor:
        user, account, store, profile = u, ctx.account, ctx.store, u.profile

    with ctx.tenant():
        set_own_sales_user(u.pk)  # o que o middleware faz para quem nao tem sales.view_all
        try:
            return str(datasets.query(Actor, "vendas", ["faturamento"], ["vendedor"]))
        except datasets.Denied:
            return ""
        finally:
            set_own_sales_user(None)


def test_l09_cosmos_dataset_respeita_proprias_vendas(ctx):
    v = ctx.product(name="X", price="123.45", track_stock=False)
    sale(ctx, ctx.client(), [(v, "1")])
    u = custo_user(ctx, "seller", "reports.view")
    u = type(u).objects.get(pk=u.pk)
    assert "123.45" not in _dataset(ctx, u)


def test_l09b_coordenador_de_estoque_na_cosmos(ctx):
    """Cargo padrao stock_lead: reports.view + cosmos, SEM sales.view."""
    v = ctx.product(name="X", price="123.45", track_stock=False)
    sale(ctx, ctx.client(), [(v, "1")])
    u = ctx.user("est", "stock_lead")
    assert ctx.client(u).get(f"{A}/reports/book/vendas/").status_code == 403
    assert "123.45" not in _dataset(ctx, u)


@pytest.mark.parametrize("path", [
    "reports/book/curva-abc/?measure=x", "reports/book/curva-abc-clientes/?measure=x",
    "reports/book/vendas/?method=x", "reports/book/vendas/?category=x", "reviews/links/?sale=x",
    "reports/book/vendas/export/?bloco=%C2%B2", "catalog/products/?category=x",
    "catalog/products/?ordering=category__parent__parent", "finance/accounts/transfer/",
    "reports/book/vendas/?date_from=0001-01-01&date_to=0001-01-02",
    "reports/book/vencimentos/?kind=x", "reports/book/fluxo-de-caixa/?financial_account=x",
])
def test_l10_entrada_estranha(ctx, path):
    assert ctx.client().get(f"{A}/{path}").status_code < 500


@pytest.mark.parametrize("days", ["abc", [1], "1e400"])
def test_l11_link_dias(ctx, days):
    v = ctx.product(name="X", price="10", track_stock=False)
    s = sale(ctx, ctx.client(), [(v, "1")])
    r = ctx.client().post(f"{A}/reviews/links/", {"sale": str(s.pk), "kind": "order", "days": days}, format="json")
    assert r.status_code < 500


@pytest.mark.parametrize("body", [
    {"action": "export", "ids": ["x"]}, {"action": "export", "all": True, "params": []},
    {"action": "export", "all": True, "params": {"columns": ["a"]}}, {"action": "export", "all": True, "params": "a"}])
def test_l12_bulk_lixo(ctx, body):
    assert ctx.client().post(f"{A}/customers/bulk/", body, format="json").status_code < 500
