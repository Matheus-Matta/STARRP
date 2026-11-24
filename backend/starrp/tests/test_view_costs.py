"""Custo e margem só para quem tem `catalog.view_costs` (core/costs.py)."""
import json
from decimal import Decimal

import pytest

from starrp.core.costs import COST_KEY, redact_report
from starrp.models import StockMovement
from starrp.services import stock


def _keys(data):
    """Todas as chaves e as `key` de colunas/métricas de uma resposta."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(key)
                if key == "key" and isinstance(value, str):
                    found.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def _cost_keys(data):
    return {k for k in _keys(data) if COST_KEY.search(str(k))}


@pytest.fixture
def sold(ctx):
    """Uma venda concluída de um produto com custo."""
    variant = ctx.product(name="Caneca", price="30.00")
    stock.move(variant, stock.default_warehouse(ctx.store), Decimal(10), StockMovement.Kind.PURCHASE,
               unit_cost=Decimal("12.00"))
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    done = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                    {"payments": [{"nsu": "1", "method": str(ctx.methods["pix"].pk), "amount": "30.00"}]}, format="json")
    assert done.status_code == 200, done.json()
    return variant, done.json()


def test_caixa_nao_ve_custo_nem_margem(ctx, sold):
    variant, sale = sold
    cashier = ctx.user("caixa", "cashier")
    api = ctx.client(cashier)

    product = api.get(f"/api/v1/catalog/products/{variant.product_id}/").json()
    detail = api.get(f"/api/v1/sales/{sale['id']}/").json()
    items = api.get("/api/v1/sales/items/").json()
    dashboard = api.get("/api/v1/reports/dashboard/").json()
    book = api.get("/api/v1/reports/book/vendas/").json()
    abc = api.get("/api/v1/reports/book/curva-abc/").json()

    for name, body in {"produto": product, "venda": detail, "itens": items, "dashboard": dashboard,
                       "vendas": book, "curva": abc}.items():
        assert not _cost_keys(body), (name, _cost_keys(body))
    assert not any("argem" in k["label"] for k in book["kpis"])
    assert api.get("/api/v1/reports/book/curva-abc/", {"measure": "margin"}).status_code == 403


def test_gerente_ve_custo_e_margem(ctx, sold):
    variant, sale = sold
    manager = ctx.user("gerente", "manager")
    api = ctx.client(manager)

    product = api.get(f"/api/v1/catalog/products/{variant.product_id}/").json()
    items = api.get("/api/v1/sales/items/").json()["results"]
    dashboard = api.get("/api/v1/reports/dashboard/").json()

    assert Decimal(product["variants"][0]["average_cost"]) == Decimal("12.00")
    assert Decimal(items[0]["margin"]) == Decimal("18.00")
    assert "gross_margin" in dashboard["summary"]


def test_caixa_nao_grava_custo(ctx):
    """Campo de custo enviado por quem não vê é ignorado (não chega ao modelo)."""
    from starrp.models import SupplierProduct, Supplier

    marketing = ctx.user("mkt", "marketing")
    marketing.profile.role.permissions.remove(*marketing.profile.role.permissions.filter(code="catalog.view_costs"))
    variant = ctx.product(name="Copo", price="10.00")
    supplier = Supplier.all_objects.create(account=ctx.account, name="Fornecedor")
    response = ctx.client(marketing).post("/api/v1/catalog/supplier-products/", {
        "supplier": str(supplier.pk), "variant": str(variant.pk), "last_cost": "99.00"}, format="json")

    assert response.status_code in (200, 201), response.json()
    assert "last_cost" not in response.json()
    assert SupplierProduct.all_objects.get(pk=response.json()["id"]).last_cost != Decimal("99.00")


def test_cosmos_nao_consulta_margem_sem_permissao(ctx):
    from starrp.services.cosmos import bridge, datasets

    # Líder de vendas: vê relatórios (o conjunto "itens vendidos"), mas não custo e margem.
    lead = ctx.user("lider", "sales_lead")
    actor = bridge.actor_for(lead, str(ctx.store.pk))
    with pytest.raises(datasets.Denied):
        datasets.query(actor, "itens_vendidos", ["margem"])
    medidas = datasets.available(actor)["itens_vendidos"]["medidas"]
    assert "margem" not in medidas and "custo" not in medidas


def test_redact_mantem_o_que_nao_e_custo():
    report = {"title": "Vendas", "kpis": [{"label": "Faturamento", "value": 10}, {"label": "Margem bruta", "value": 3}],
              "blocks": [{"type": "table", "title": "Itens", "columns": [{"key": "customer", "label": "Cliente"},
                                                                       {"key": "margin", "label": "Margem"}],
                          "rows": [{"customer": "Ana", "margin": 3}]},
                         {"type": "bars", "title": "Margem bruta por categoria (%)", "x": ["A"],
                          "series": [{"name": "Margem", "values": [1]}]}],
              "filters": [{"name": "measure", "options": [{"value": "revenue", "label": "Faturamento"},
                                                          {"value": "margin", "label": "Margem bruta"}]}]}
    out = json.loads(json.dumps(redact_report(report)))
    assert [k["label"] for k in out["kpis"]] == ["Faturamento"]
    assert len(out["blocks"]) == 1 and out["blocks"][0]["rows"] == [{"customer": "Ana"}]
    assert out["filters"][0]["options"] == [{"value": "revenue", "label": "Faturamento"}]


def test_caixa_fecha_o_turno_sem_ver_custo_nem_margem(ctx):
    """Relatório e extrato do turno (abertos pelo próprio operador) e movimentações de estoque."""
    variant = ctx.product(name="Caneca", price="30.00")
    stock.move(variant, stock.default_warehouse(ctx.store), Decimal(10), StockMovement.Kind.PURCHASE,
               unit_cost=Decimal("12.00"))
    cashier = ctx.user("caixa", "cashier")
    ctx.link(cashier)
    api = ctx.client(cashier)
    session = api.post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                       format="json").json()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    done = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                    {"payments": [{"nsu": "1", "method": str(ctx.methods["pix"].pk), "amount": "30.00"}]}, format="json")
    assert done.status_code == 200, done.json()

    report = api.get(f"/api/v1/cash/sessions/{session['id']}/report/").json()
    statement = api.get(f"/api/v1/cash/sessions/{session['id']}/statement/").json()
    assert report["sales"]["count"] == 1 and not _cost_keys(report), _cost_keys(report)
    assert statement["items"] and not _cost_keys(statement), _cost_keys(statement)

    manager = ctx.client(ctx.user("gerente", "manager"))
    assert "gross_margin" in manager.get(f"/api/v1/cash/sessions/{session['id']}/report/").json()["sales"]
    ctx.account.extra_modules = ["stock"]
    ctx.account.save(update_fields=["extra_modules"])
    movements = ctx.client().get("/api/v1/stock/movements/")
    assert movements.status_code == 200, movements.json()
    assert "unit_cost" in movements.json()["results"][0]
    stockist = ctx.user("estoq", "stockist")
    stockist.profile.role.permissions.remove(*stockist.profile.role.permissions.filter(code="catalog.view_costs"))
    hidden = ctx.client(stockist).get("/api/v1/stock/movements/")
    assert hidden.status_code == 200, hidden.json()
    assert hidden.json()["results"] and not _cost_keys(hidden.json()), _cost_keys(hidden.json())
