"""Endereços do pedido: entrega e cobrança próprios, herdados do cliente e corrigíveis no pedido."""
from starrp.models import Customer, CustomerAddress

HOME = {"label": "Casa", "zip_code": "01310100", "street": "Av. Paulista", "number": "1000", "district": "Bela Vista",
        "city": "São Paulo", "state": "SP", "is_default": True}
OFFICE = {"label": "Escritório", "zip_code": "20040002", "street": "Rua da Assembleia", "number": "10",
          "district": "Centro", "city": "Rio de Janeiro", "state": "RJ", "is_billing": True}


def _customer(api, same=True, addresses=(HOME, OFFICE)):
    return api.post("/api/v1/customers/", {"name": "Bia Souza", "billing_same_as_delivery": same,
                                           "addresses": list(addresses)}, format="json").json()


def test_pedido_herda_entrega_e_cobranca_separadas_do_cliente(ctx):
    api = ctx.client()
    customer = _customer(api, same=False)
    sale = api.post("/api/v1/sales/", {"customer": customer["id"]}, format="json").json()
    addresses = sale["addresses"]

    assert [a["is_billing"] for a in customer["addresses"]] == [False, True]
    assert addresses["billing_same_as_delivery"] is False
    assert addresses["delivery"]["street"] == "Av. Paulista" and addresses["delivery"]["from_customer"] is True
    assert addresses["billing"]["city"] == "Rio de Janeiro"


def test_cobranca_igual_a_entrega_e_herdada(ctx):
    api = ctx.client()
    customer = _customer(api, same=True)
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    linked = api.post(f"/api/v1/sales/{sale['id']}/customer/", {"customer": customer["id"]}, format="json").json()

    assert sale["addresses"]["delivery"] is None  # sem cliente, sem endereço
    assert linked["addresses"]["billing_same_as_delivery"] is True
    assert linked["addresses"]["billing"] == linked["addresses"]["delivery"]
    assert linked["addresses"]["delivery"]["zip_code"] == "01310100"


def test_corrigir_no_pedido_nao_mexe_no_cadastro(ctx):
    api = ctx.client()
    customer = _customer(api, same=True)
    sale = api.post("/api/v1/sales/", {"customer": customer["id"]}, format="json").json()
    url = f"/api/v1/sales/{sale['id']}/addresses/"
    fixed = {**HOME, "number": "1002", "complement": "Apto 5"}

    incomplete = api.post(url, {"delivery": {**fixed, "street": ""}}, format="json")
    saved = api.post(url, {"delivery": fixed, "billing": OFFICE, "billing_same_as_delivery": False}, format="json").json()
    again = api.post(url, {"inherit": True}, format="json").json()

    assert incomplete.status_code == 422 and incomplete.json()["error"]["code"] == "address_incomplete"
    assert saved["delivery"]["number"] == "1002" and saved["delivery"]["from_customer"] is False
    assert saved["billing"]["city"] == "Rio de Janeiro" and saved["billing_same_as_delivery"] is False
    assert CustomerAddress.all_objects.get(customer_id=customer["id"], is_default=True).number == "1000"
    assert again["delivery"]["number"] == "1000" and again["billing_same_as_delivery"] is True


def test_trocar_o_cliente_herda_o_endereco_do_novo(ctx):
    api = ctx.client()
    first = _customer(api)
    second = Customer.all_objects.create(account=ctx.account, name="Sem endereço")
    sale = api.post("/api/v1/sales/", {"customer": first["id"]}, format="json").json()
    swapped = api.post(f"/api/v1/sales/{sale['id']}/customer/", {"customer": str(second.pk)}, format="json").json()

    assert sale["addresses"]["delivery"] is not None
    assert swapped["addresses"]["delivery"] is None and swapped["addresses"]["billing"] is None
