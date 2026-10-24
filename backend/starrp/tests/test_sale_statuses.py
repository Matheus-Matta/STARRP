"""Status do pedido: pagamento, entrega e o status geral (até o produto chegar no cliente)."""
from starrp.models import Customer, CustomerAddress


def _pay(api, ctx, sale_id, amount):
    return api.post(f"/api/v1/sales/{sale_id}/checkout/", {"payments": [
        {"method": str(ctx.methods["pix"].pk), "amount": amount, "nsu": "112233"}]}, format="json")


def _statuses(body):
    return body["overall_status"], body["payment_status"], body["fulfillment_status"]


def test_balcao_conclui_no_caixa_com_retirada(ctx):
    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    opened = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json").json()
    done = _pay(api, ctx, sale["id"], "30.00").json()

    listed = api.get("/api/v1/sales/?overall_status=completed").json()["results"]

    assert _statuses(opened) == ("open", "pending", "pending")
    assert _statuses(done) == ("completed", "paid", "picked_up")
    assert [_statuses(row) for row in listed if row["id"] == sale["id"]] == [("completed", "paid", "picked_up")]


def test_entrega_so_conclui_quando_chega_no_cliente(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana")
    address = CustomerAddress.all_objects.create(account=ctx.account, customer=customer, zip_code="01310100",
                                                 street="Av. Paulista", number="1000", city="São Paulo", state="SP")
    variant = ctx.product(name="Mesa", price="100.00", track_stock=False)
    api = ctx.client()
    table = api.post("/api/v1/logistics/freight-tables/", {"name": "Motoboy", "kind": "zip_range", "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "20.00"}]}, format="json").json()
    sale = api.post("/api/v1/sales/", {"customer": str(customer.pk)}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/delivery/", {"address": str(address.pk), "table": table["id"]}, format="json")
    paid = _pay(api, ctx, sale["id"], "120.00").json()
    url = f"/api/v1/sales/{sale['id']}/fulfillment/"

    shipped = api.post(url, {"status": "shipped"}, format="json").json()  # pulou "separado": preenche
    back_no_reason = api.post(url, {"status": "ready"}, format="json")
    back = api.post(url, {"status": "ready", "note": "Voltou: cliente não estava"}, format="json").json()
    delivered = api.post(url, {"status": "delivered"}, format="json").json()
    two_back = api.post(url, {"status": "ready", "note": "Errei"}, format="json")  # duas etapas de uma vez
    feed = api.get(f"/api/v1/sales/{sale['id']}/history/").json()["results"]

    assert _statuses(paid) == ("awaiting_picking", "paid", "pending")
    assert _statuses(shipped) == ("in_transit", "paid", "shipped") and shipped["ready_at"] and shipped["shipped_at"]
    assert back_no_reason.status_code == 422 and back["overall_status"] == "ready" and back["shipped_at"] is None
    assert two_back.status_code == 422
    assert _statuses(delivered) == ("completed", "paid", "delivered") and delivered["delivered_at"]
    assert {"Entregue", "Saiu para entrega", "Separado"} <= {row["label"] for row in feed}


def test_balcao_nao_tem_entrega_e_cancelada_ou_devolvida_refletem_no_geral(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Bia", document="98765432100")
    variant = ctx.product(name="Copo", price="10.00", track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {"customer": str(customer.pk)}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk), "quantity": "2"}, format="json")
    done = _pay(api, ctx, sale["id"], "20.00").json()
    no_delivery = api.post(f"/api/v1/sales/{sale['id']}/fulfillment/", {"status": "ready"}, format="json")

    first = api.post(f"/api/v1/sales/{sale['id']}/returns/", {
        "items": [{"sale_item": done["items"][0]["id"], "quantity": "1"}], "reason": "Quebrado"}, format="json").json()
    api.post(f"/api/v1/returns/{first['id']}/complete/", {}, format="json")
    partial = api.get(f"/api/v1/sales/{sale['id']}/").json()
    rest = api.post(f"/api/v1/sales/{sale['id']}/returns/", {
        "items": [{"sale_item": done["items"][0]["id"], "quantity": "1"}], "reason": "Desistiu"}, format="json").json()
    api.post(f"/api/v1/returns/{rest['id']}/complete/", {}, format="json")
    returned = api.get(f"/api/v1/sales/{sale['id']}/").json()

    other = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{other['id']}/items/", {"variant": str(variant.pk)}, format="json")
    cancelled = api.post(f"/api/v1/sales/{other['id']}/cancel/", {"reason": "Desistiu"}, format="json").json()

    assert no_delivery.status_code == 422
    assert _statuses(partial) == ("completed", "partially_refunded", "picked_up") and partial["refunded_amount"] == "10.00"
    assert _statuses(returned) == ("returned", "refunded", "returned")
    assert _statuses(cancelled) == ("cancelled", "cancelled", "cancelled")


def test_pedido_mostra_a_nota_fiscal_autorizada_primeiro(ctx):
    """Rejeitada e reemitida: a autorizada é a principal; as outras vêm depois."""
    from datetime import timedelta

    from django.utils import timezone

    from starrp.models import Invoice

    variant = ctx.product(name="Caneca", price="30.00", track_stock=False)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    _pay(api, ctx, sale["id"], "30.00")
    common = {"account": ctx.account, "store": ctx.store, "sale_id": sale["id"], "series": 1, "total": "30.00"}
    Invoice.all_objects.create(**common, number=10, status="rejected")
    good = Invoice.all_objects.create(**common, number=11, status="authorized", access_key="3" * 44, protocol="135",
                                      authorized_at=timezone.now() - timedelta(minutes=1))

    body = api.get(f"/api/v1/sales/{sale['id']}/").json()

    assert [i["number"] for i in body["invoices"]] == [11, 10]
    assert body["invoices"][0]["id"] == str(good.pk) and body["invoices"][0]["label"] == "NFC-e 11 · série 1"
    assert body["invoices"][0]["status_label"] == "Autorizada" and body["invoices"][0]["access_key"] == "3" * 44
