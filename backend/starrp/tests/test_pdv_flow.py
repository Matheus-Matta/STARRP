"""PDV amarrado: vendedor monta e guarda o pedido, caixa retoma e cobra; nada se perde."""
from starrp.models import Sale, Store


def _open_cash(ctx, api):
    return api.post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"}, format="json")


def test_vendedor_guarda_o_pedido_e_o_caixa_retoma_e_cobra(ctx):
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    seller = ctx.user("vend", "seller", is_seller=True)
    cashier = ctx.user("caixa", "cashier")
    ctx.register.operators.add(cashier)
    by_seller, by_cashier = ctx.client(seller), ctx.client(cashier)

    boot = by_seller.post("/api/v1/pdv/bootstrap/", {"installation_id": "tab-1"}, format="json").json()
    sale = by_seller.post("/api/v1/sales/", {"seller": seller.pk}, format="json").json()
    by_seller.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk), "quantity": "2"}, format="json")
    charge = by_seller.post(f"/api/v1/sales/{sale['id']}/checkout/",
                            {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "60.00"}]}, format="json")
    parked = by_seller.post(f"/api/v1/sales/{sale['id']}/park/", {"note": "Cliente volta às 15h"}, format="json")
    waiting = by_cashier.get("/api/v1/sales/?status=draft").json()

    _open_cash(ctx, by_cashier)
    resumed = by_cashier.post(f"/api/v1/sales/{sale['id']}/resume/", {}, format="json")
    again = by_cashier.post(f"/api/v1/sales/{sale['id']}/resume/", {}, format="json")
    done = by_cashier.post(f"/api/v1/sales/{sale['id']}/checkout/",
                           {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "60.00"}]}, format="json")

    assert boot["mode"] == "seller"
    assert charge.status_code == 403  # vendedor não cobra
    assert parked.status_code == 200 and parked.json()["status"] == "draft"
    assert [row["id"] for row in waiting["results"]] == [sale["id"]]
    assert resumed.status_code == 200 and resumed.json()["status"] == "open"
    assert again.status_code == 409  # dois caixas não retomam o mesmo pedido
    assert done.status_code == 200 and done.json()["status"] == "completed"
    finished = Sale.all_objects.get(pk=sale["id"])
    assert finished.seller_id == seller.pk and finished.cash_session is not None


def test_pedido_com_pagamento_ou_vazio_nao_e_guardado(ctx):
    variant = ctx.product(name="Copo", price="10.00", track_stock=False)
    api = ctx.client()
    _open_cash(ctx, api)
    empty = api.post("/api/v1/sales/", {}, format="json").json()
    paid = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{paid['id']}/items/", {"variant": str(variant.pk), "quantity": "3"}, format="json")
    api.post(f"/api/v1/sales/{paid['id']}/payments/", {"nsu": "000123", "method": str(ctx.methods["cash"].pk), "amount": "10.00"},
             format="json")

    no_items = api.post(f"/api/v1/sales/{empty['id']}/park/", {}, format="json")
    with_payment = api.post(f"/api/v1/sales/{paid['id']}/park/", {}, format="json")

    assert no_items.status_code == 422 and no_items.json()["error"]["code"] == "sale_empty"
    assert with_payment.status_code == 409 and with_payment.json()["error"]["code"] == "sale_has_payment"


def test_desbloqueio_com_a_senha_do_operador_ou_a_do_caixa(ctx):
    cashier = ctx.user("caixa2", "cashier")
    Store.all_objects.filter(pk=ctx.store.pk).update(cash_action_password="")
    ctx.store.set_cash_action_password("gerente9")
    ctx.store.save()
    api = ctx.client(cashier)

    own = api.post("/api/v1/pdv/unlock/", {"password": "senha123"}, format="json")
    manager = api.post("/api/v1/pdv/unlock/", {"password": "gerente9"}, format="json")
    wrong = api.post("/api/v1/pdv/unlock/", {"password": "chute"}, format="json")
    boot = api.post("/api/v1/pdv/bootstrap/", {"installation_id": "tab-2"}, format="json").json()

    assert own.status_code == 200 and manager.status_code == 200 and wrong.status_code == 403
    assert boot["mode"] == "cashier" and boot["has_cash_action_password"] is True and boot["lock_minutes"] == 5


def test_categoria_traz_as_subcategorias(ctx):
    api = ctx.client()
    drinks = api.post("/api/v1/catalog/categories/", {"name": "Bebidas"}, format="json").json()
    beers = api.post("/api/v1/catalog/categories/", {"name": "Cervejas", "parent": drinks["id"]}, format="json").json()
    ctx.product(name="Cerveja", price="5", category_id=beers["id"])
    ctx.product(name="Pão", price="1")

    found = api.get(f"/api/v1/catalog/products/?category={drinks['id']}").json()["results"]

    assert [p["name"] for p in found] == ["Cerveja"]


def test_cartao_e_pix_sem_nsu_nao_lancam(ctx):
    """O comprovante amarra a venda à maquininha: sem NSU/autorização o pagamento é recusado."""
    variant = ctx.product(name="Bloco", price="20.00", track_stock=False)
    api = ctx.client()
    _open_cash(ctx, api)
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk), "quantity": "1"}, format="json")
    url = f"/api/v1/sales/{sale['id']}/checkout/"

    missing = api.post(url, {"payments": [{"method": str(ctx.methods["pix"].pk), "amount": "20.00"}]}, format="json")
    ok = api.post(url, {"payments": [{"method": str(ctx.methods["pix"].pk), "amount": "20.00", "nsu": "889911"}]},
                  format="json", HTTP_IDEMPOTENCY_KEY="nsu-ok")

    assert missing.status_code == 422 and missing.json()["error"]["code"] == "reference_required"
    assert ok.status_code == 200 and ok.json()["status"] == "completed"
