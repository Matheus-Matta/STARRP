from datetime import date
from decimal import Decimal as D

import pytest

from starrp.core.permissions import has_permission_code
from starrp.models import (
    Customer, FinancialAccount, FinancialCategory, StockMovement, StorageBin,
)
from starrp.services import cash, cash_flow, dre, finance, ledger, stock, wms

A = "/api/v1"


@pytest.fixture(autouse=True)
def m(ctx):
    ctx.account.extra_modules = ["stock", "inbound_nfe", "finance", "pricing", "wms"]
    ctx.account.save()


def bank(ctx):
    return FinancialAccount.all_objects.filter(account=ctx.account, kind="bank").first()


def stocked(ctx, cost="10"):
    v, w = ctx.product(), stock.default_warehouse(ctx.store)
    stock.move(v, w, D(10), StockMovement.Kind.PURCHASE, unit_cost=D(cost))
    return v, w


def title(ctx, kind="receivable", total="100", **kw):
    return finance.create_title(store=ctx.store, kind=kind, description="t", total=D(total), **kw)


def test_bin_bulk_desativar(ctx):
    w, v = stock.default_warehouse(ctx.store), ctx.product()
    b = StorageBin.all_objects.create(account=ctx.account, warehouse=w, code="R1", kind="receiving")
    w.uses_bins = True
    w.save()
    stock.move(v, w, D(5), StockMovement.Kind.PURCHASE, unit_cost=D(1))
    url = next(u for u in (f"{A}/stock/bins/", f"{A}/storage-bins/", f"{A}/wms/bins/") if ctx.client().get(u).status_code == 200)
    r = ctx.client().post(f"{url}bulk/", {"action": "deactivate", "ids": [str(b.pk)]}, format="json")
    b.refresh_from_db()
    assert b.is_active, (r.status_code, r.content[:200])


def test_unsettle_conta_excluida(ctx):
    api, b = ctx.client(), bank(ctx)
    x = FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="X", kind="bank")
    p = title(ctx, customer=Customer.all_objects.create(account=ctx.account, name="Ze")).installments.first()
    finance.settle(p, x, D(100), ctx.admin)
    ledger.transfer(x, b, D(100), description="t", user=ctx.admin)
    d = api.delete(f"{A}/finance/accounts/{x.pk}/")
    assert d.status_code == 204, d.content
    r = api.post(f"{A}/finance/installments/{p.pk}/unsettle/", {"reason": "erro"}, format="json")
    tot = cash_flow.balances(ctx.account, None)["total"]
    assert r.status_code >= 400 or tot == 0, (r.status_code, tot)


def test_juros_parcial_mes(ctx):
    p = title(ctx, customer=Customer.all_objects.create(account=ctx.account, name="Ze"), issue_date=date(2026, 1, 1)).installments.first()
    finance.settle(p, bank(ctx), D(60), ctx.admin, interest=10, date=date(2026, 1, 31))
    q = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
    antes = dre.build(ctx.account, None, q)["operating_result"]
    finance.settle(p, bank(ctx), D(50), ctx.admin, date=date(2026, 2, 15))
    assert dre.build(ctx.account, None, q)["operating_result"] == antes


@pytest.mark.parametrize("role", ["logistics", "logistics_lead", "assets"])
def test_estoque_custo(ctx, role):
    u = ctx.user("u1", role)
    stocked(ctx, "37.13")
    assert not has_permission_code(u, "catalog.view_costs")
    r = ctx.client(u).get(f"{A}/reports/book/posicao-de-estoque/")
    assert r.status_code == 403 or "371.3" not in r.content.decode()


def test_fechamento_lucro_vaza(ctx):
    u = ctx.user("f1", "assets")
    assert not has_permission_code(u, "catalog.view_costs")
    FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name="Socio", kind="partner", partner_share=D(50))
    title(ctx, total="1234.60")
    r = ctx.client(u).get(f"{A}/reports/book/fechamento/")
    assert r.status_code == 200, r.content
    assert "617.3" not in r.content.decode()


def test_start_bins_sem_endereco(ctx):
    _, w = stocked(ctx)
    r = ctx.client().patch(f"{A}/stock/warehouses/{w.pk}/", {"uses_bins": True}, format="json")
    assert r.status_code < 500


def test_start_bins_religar(ctx):
    v, w = stocked(ctx)
    StorageBin.all_objects.create(account=ctx.account, warehouse=w, code="R1", kind="receiving")
    for on, q in ((True, 10), (False, 0), (True, 9)):
        r = ctx.client().patch(f"{A}/stock/warehouses/{w.pk}/", {"uses_bins": on}, format="json")
        assert r.status_code == 200, r.content
        if on:
            assert wms.bin_total(w, v) == q
        else:
            w.refresh_from_db()
            stock.move(v, w, D(-1), StockMovement.Kind.SALE)


@pytest.mark.parametrize("key", ["commissions", "card_fees"])
def test_titulo_manual_categoria_automatica(ctx, key):
    cat = FinancialCategory.all_objects.get(account=ctx.account, system_key=key)
    title(ctx, kind="payable", total="300", category=cat)
    assert dre.build(ctx.account, None, {})["expenses_total"] == 300


@pytest.mark.parametrize("kind", ["loss", "adjustment", "asset_disposal"])
def test_perda_dre(ctx, kind):
    v, w = stocked(ctx)
    stock.move(v, w, D(-3), kind)
    assert dre.build(ctx.account, None, {})["expenses_total"] == 30


def test_cego(ctx):
    ctx.require_cash()
    u = ctx.user("cx", "cashier")
    ctx.link(u)
    cash.open_session(ctx.register, u, D(0))
    c = ctx.client(u)
    assert c.get(f"{A}/reports/book/vendas/").status_code == 200
    assert c.get(f"{A}/reports/book/recebimentos/").status_code == 403


def test_unsettle_ciclo(ctx):
    p = title(ctx, customer=Customer.all_objects.create(account=ctx.account, name="Ze")).installments.first()
    for total, juros in (("110", 10), ("100", 0)):
        finance.settle(p, bank(ctx), D(total), ctx.admin, interest=juros)
        finance.unsettle(p, ctx.admin, "x")
        p.refresh_from_db()
        assert p.status == "open" and p.balance == 100 and cash_flow.balances(ctx.account, None)["total"] == 0
