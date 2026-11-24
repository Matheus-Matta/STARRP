"""Vendedor (sem `sales.view_all`) vê só as PRÓPRIAS vendas: na lista, nos itens vendidos e nos relatórios.
Quem tem a permissão (caixa, gerente, admin...) continua vendo as da equipe."""
from starrp.models import Sale
from starrp.services.access_catalog import SYSTEM_ROLES


def _sale(ctx, api, name):
    variant = ctx.product(name=name, price="10.00", track_stock=False)
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    done = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                    {"payments": [{"method": str(ctx.methods["pix"].pk), "amount": "10.00"}]}, format="json")
    assert done.status_code == 200, done.json()
    return done.json()


def test_so_o_vendedor_fica_sem_ver_as_vendas_da_equipe():
    roles = {r["code"]: r["permissions"] for r in SYSTEM_ROLES}
    assert "sales.view_all" not in roles["seller"]
    assert all("sales.view_all" in perms for code, perms in roles.items() if code != "seller" and "sales.view" in perms)


def test_vendedor_ve_so_as_proprias_vendas_e_o_caixa_ve_todas(ctx):
    admin = ctx.client()
    mine_user = ctx.user("ana", "seller", is_seller=True)
    mine = _sale(ctx, admin, "Mesa")
    other = _sale(ctx, admin, "Cadeira")
    Sale.all_objects.filter(pk=mine["id"]).update(seller=mine_user)

    seller = ctx.client(mine_user)
    cashier = ctx.client(ctx.user("caixa", "cashier"))
    listed = {s["id"] for s in seller.get("/api/v1/sales/").json()["results"]}
    items = {i["sale"] for i in seller.get("/api/v1/sales/items/").json()["results"]}
    summary = seller.get("/api/v1/reports/summary/").json()
    book = seller.get("/api/v1/reports/book/vendas/").json()

    assert listed == {mine["id"]}
    assert items == {mine["id"]}
    assert seller.get(f"/api/v1/sales/{other['id']}/").status_code == 404
    assert summary["sales_count"] == 1
    assert book["kpis"][0]["value"] in ("10.00", 10, "10")
    assert {s["id"] for s in cashier.get("/api/v1/sales/").json()["results"]} >= {mine["id"], other["id"]}
    assert admin.get("/api/v1/reports/summary/").json()["sales_count"] >= 2


def test_venda_que_o_vendedor_registrou_aparece_para_ele(ctx):
    user = ctx.user("bia", "seller", is_seller=True)
    api = ctx.client(user)
    sale = api.post("/api/v1/sales/", {"channel": "mobile"}, format="json").json()

    assert {s["id"] for s in api.get("/api/v1/sales/", {"status": "open"}).json()["results"]} == {sale["id"]}
