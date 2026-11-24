"""Contrato do app móvel (mobile/): as chamadas exatamente como o app faz.

Login por usuário/senha com o token no header (sem cookie), `/me/` com cargos,
permissões e módulos, leitura de código, lançamento de estoque (rascunho →
confirmar → cancelar), kardex, alertas e relatórios — e o bloqueio por cargo/módulo.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient

from starrp.models import StockMovement
from starrp.services import stock

TODAY = str(date.today())


@pytest.fixture
def wh(ctx):
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    return stock.default_warehouse(ctx.store)


def _bearer(ctx, username, password="senha123"):
    """Login do app: POST /auth/login/ e depois só o header Authorization + X-Store-ID."""
    login = APIClient().post("/api/v1/auth/login/", {"username": username, "password": password}, format="json")
    assert login.status_code == 200, login.content
    tokens = login.json()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}", HTTP_X_STORE_ID=str(ctx.store.pk))
    return client, tokens


def test_login_por_token_e_me_trazem_cargo_permissoes_e_modulos(ctx, wh):
    user = ctx.user("estoquista", "stockist")
    client, tokens = _bearer(ctx, "estoquista")

    me = client.get("/api/v1/me/").json()
    refreshed = APIClient().post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")

    assert me["username"] == user.username and me["role"]["code"] == "stockist"
    assert "stock.manage" in me["permissions"] and "sales.view" not in me["permissions"]
    assert "stock" in me["account"]["modules"] and me["stores"][0]["id"] == str(ctx.store.pk)
    # O app guarda o refresh novo (rotação): a resposta precisa trazê-lo.
    assert refreshed.status_code == 200 and refreshed.json()["refresh"] != tokens["refresh"]


def test_estoquista_le_codigo_lanca_entrada_confirma_e_cancela(ctx, wh):
    coffee = ctx.product(name="Café", price="20.00", barcode="7891000100103")
    ctx.user("estoquista", "stockist")
    client, _ = _bearer(ctx, "estoquista")

    found = client.get("/api/v1/catalog/variants/lookup/", {"code": "7891000100103"}).json()
    missing = client.get("/api/v1/catalog/variants/lookup/", {"code": "000"})
    warehouses = client.get("/api/v1/stock/warehouses/", {"is_active": True, "page_size": 200}).json()["results"]
    created = client.post("/api/v1/stock/documents/", {
        "kind": "entry", "warehouse": str(wh.pk), "effective_date": TODAY, "reason": "", "destination": None,
        "exit_reason": "", "external_number": "NF 123",
        "items": [{"variant": found["id"], "quantity": "12", "unit_cost": "8.5", "lot_number": "L1"}],
    }, format="json")
    doc = created.json()
    posted = client.post(f"/api/v1/stock/documents/{doc['id']}/post/", {}, format="json")
    balances = client.get("/api/v1/stock/balances/", {"variant": str(coffee.pk), "page_size": 40,
                                                       "ordering": "variant_name"}).json()["results"]
    kardex = client.get("/api/v1/stock/movements/", {"variant": str(coffee.pk), "ordering": "-created_at"}).json()
    cancelled = client.post(f"/api/v1/stock/documents/{doc['id']}/cancel/", {"reason": "lançado errado"}, format="json")

    assert found["id"] == str(coffee.pk) and missing.json()["error"]["code"] == "product_not_found"
    assert any(w["id"] == str(wh.pk) and w["is_default"] for w in warehouses)
    assert created.status_code == 201, created.content
    assert posted.status_code == 200 and posted.json()["status"] == "posted"
    assert balances[0]["quantity"] == "12.000" and balances[0]["warehouse_name"] == wh.name
    assert kardex["results"][0]["kind_label"] == "Entrada por compra"
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert stock.available(coffee, wh) == 0


def test_saida_transferencia_e_inventario_pelo_app(ctx, wh):
    rice = ctx.product(name="Arroz", price="30.00")
    stock.move(rice, wh, 10, StockMovement.Kind.INITIAL, source_key="init:rice")
    client, _ = _bearer(ctx, ctx.admin.username)
    other = client.post("/api/v1/stock/warehouses/", {"name": "Fundos", "kind": "storage"}, format="json").json()

    def launch(body):
        doc = client.post("/api/v1/stock/documents/", {"warehouse": str(wh.pk), "effective_date": TODAY, **body,
                                                       "items": [{"variant": str(rice.pk), **body.pop("item")}]},
                          format="json")
        assert doc.status_code == 201, doc.content
        posted = client.post(f"/api/v1/stock/documents/{doc.json()['id']}/post/", {}, format="json")
        assert posted.status_code == 200, posted.content

    launch({"kind": "exit", "exit_reason": "loss", "item": {"quantity": "2"}})
    launch({"kind": "transfer", "destination": other["id"], "item": {"quantity": "3"}})
    launch({"kind": "inventory", "item": {"quantity": "4"}})  # contou 4 onde o sistema dizia 5
    balances = client.get("/api/v1/stock/balances/", {"variant": str(rice.pk)}).json()["results"]

    by_wh = {b["warehouse"]: b["quantity"] for b in balances}
    assert by_wh[str(wh.pk)] == "4.000" and by_wh[other["id"]] == "3.000"
    kinds = set(StockMovement.all_objects.filter(variant=rice).values_list("kind", flat=True))
    assert {"loss", "transfer_out", "transfer_in", "adjustment"} <= kinds


def test_cargo_e_modulo_barram_o_que_o_app_esconde(ctx, wh):
    ctx.user("vendedor", "seller")
    seller, _ = _bearer(ctx, "vendedor")
    me = seller.get("/api/v1/me/").json()

    assert "stock.view" not in me["permissions"]
    assert seller.get("/api/v1/stock/balances/").status_code == 403
    assert seller.post("/api/v1/stock/documents/", {"kind": "entry"}, format="json").status_code == 403
    assert seller.get("/api/v1/reports/book/posicao-de-estoque/").status_code == 403

    # Sem o módulo de estoque, nem o administrador movimenta.
    ctx.account.extra_modules = []
    ctx.account.save()
    admin, _ = _bearer(ctx, ctx.admin.username)
    assert "stock" not in admin.get("/api/v1/me/").json()["account"]["modules"]
    assert admin.get("/api/v1/stock/balances/").status_code == 403


def test_relatorios_e_painel_do_dia_no_formato_que_o_app_desenha(ctx, wh):
    ctx.product(name="Feijão", price="9.00", min_stock=5)
    client, _ = _bearer(ctx, ctx.admin.username)

    summary = client.get("/api/v1/reports/summary/", {"date_from": TODAY, "date_to": TODAY}).json()
    book = client.get("/api/v1/reports/book/posicao-de-estoque/", {"date_from": TODAY, "date_to": TODAY}).json()
    sales_book = client.get("/api/v1/reports/book/vendas/", {"date_from": TODAY, "date_to": TODAY}).json()
    alerts = client.get("/api/v1/stock/balances/alerts/")
    sales = client.get("/api/v1/sales/", {"page_size": 30, "ordering": "-created_at"})
    cash = client.get("/api/v1/cash/sessions/", {"status": "open", "ordering": "-opened_at"})

    assert {"sales_count", "revenue", "average_ticket"} <= set(summary)
    for report in (book, sales_book):
        assert report["kpis"] and all({"label", "value", "format"} <= set(k) for k in report["kpis"])
        assert all("type" in b and "title" in b for b in report["blocks"])
    assert alerts.status_code == 200
    assert sales.status_code == 200 and "results" in sales.json()
    assert cash.status_code == 200 and "results" in cash.json()
