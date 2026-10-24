"""Entrega (endereços do cliente + tabelas de frete do StarHub) e metacampos/ficha técnica."""
from decimal import Decimal
from unittest import mock

from starrp.models import Category, CustomerAddress, FreightTable
from starrp.services import freight


def _customer(api, **extra):
    return api.post("/api/v1/customers/", {"name": "Ana Souza", "addresses": [
        {"label": "Casa", "zip_code": "01310-100", "street": "Av. Paulista", "number": "1000", "district": "Bela Vista",
         "city": "São Paulo", "state": "sp"},
        {"label": "Trabalho", "zip_code": "04538133", "street": "Av. Faria Lima", "number": "3477",
         "city": "São Paulo", "state": "SP", "is_default": True},
    ], **extra}, format="json")


def test_cliente_guarda_enderecos_com_um_so_padrao(ctx):
    api = ctx.client()
    created = _customer(api).json()
    by_label = {a["label"]: a for a in created["addresses"]}
    home, work = by_label["Casa"], by_label["Trabalho"]
    edited = api.patch(f"/api/v1/customers/{created['id']}/", {"addresses": [
        {**work, "number": "3500"}, {"label": "", "zip_code": "22041001", "city": "Rio de Janeiro", "state": "RJ"},
    ]}, format="json").json()
    bad = api.post("/api/v1/customers/", {"name": "X", "addresses": [{"zip_code": "123"}]}, format="json")

    assert home["zip_code"] == "01310100" and home["state"] == "SP" and work["is_default"] and not home["is_default"]
    assert [a["number"] for a in edited["addresses"]][0] == "3500"  # o mesmo registro, alterado
    assert edited["addresses"][0]["id"] == work["id"] and edited["addresses"][1]["label"] == "Endereço 2"
    assert CustomerAddress.all_objects.get(pk=home["id"]).deleted_at is not None  # saiu da lista = apagado
    assert bad.status_code == 400


def test_frete_por_faixa_vale_a_mais_estreita_e_por_distancia_tem_minimo_e_limite(ctx):
    api = ctx.client()
    by_range = api.post("/api/v1/logistics/freight-tables/", {"name": "Motoboy SP", "kind": "zip_range", "lead_days": 2,
                                                              "ranges": [
        {"zip_start": "01000-000", "zip_end": "05999-999", "value": "25.00", "label": "Capital"},
        {"zip_start": "01300000", "zip_end": "01399999", "value": "15.00", "lead_days": 1, "label": "Centro"},
    ]}, format="json")
    by_km = api.post("/api/v1/logistics/freight-tables/", {"name": "Caminhão", "kind": "distance", "origin_zip": "01001000",
                                                           "price_per_km": "2.50", "fixed_fee": "10", "min_value": "40",
                                                           "max_distance_km": "100", "lead_days": 3}, format="json")
    no_origin = api.post("/api/v1/logistics/freight-tables/", {"name": "X", "kind": "distance"}, format="json")

    with mock.patch.object(freight, "km_between", side_effect=[(Decimal("8.0"), True), (Decimal("30.0"), False),
                                                                (Decimal("150.0"), True)]):
        near = api.get("/api/v1/logistics/freight-tables/quote/?zip=01310-100").json()
        mid = freight.quote(FreightTable.all_objects.get(name="Caminhão"), "04538133")
        far = api.get("/api/v1/logistics/freight-tables/quote/?zip=09000000").json()

    assert by_range.status_code == 201 and by_km.status_code == 201 and no_origin.status_code == 400
    by_name = {q["table_name"]: q for q in near}
    assert by_name["Motoboy SP"]["value"] == "15.00" and by_name["Motoboy SP"]["lead_days"] == 1  # faixa mais estreita
    assert by_name["Caminhão"]["value"] == "40.00"  # 10 + 8 km × 2,50 = 30 → mínimo 40
    assert mid.value == Decimal("85.00") and "estimados" in mid.detail
    far_by = {q["table_name"]: q for q in far}
    assert far_by["Motoboy SP"]["value"] is None and "faixa" in far_by["Motoboy SP"]["error"]
    assert far_by["Caminhão"]["value"] is None and "distância máxima" in far_by["Caminhão"]["error"]


def test_entrega_entra_no_total_e_retirada_tira(ctx):
    api = ctx.client()
    customer = _customer(api).json()
    table = api.post("/api/v1/logistics/freight-tables/", {"name": "Motoboy", "kind": "zip_range", "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "19.90", "lead_days": 1}]}, format="json").json()
    variant = ctx.product(name="Mesa", price="100.00", track_stock=False)
    sale = api.post("/api/v1/sales/", {"customer": customer["id"]}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    home = next(a["id"] for a in customer["addresses"] if a["label"] == "Casa")

    delivered = api.post(f"/api/v1/sales/{sale['id']}/delivery/", {"address": home, "table": table["id"]},
                         format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/metafields/", {"metafields": {"pedido_loja": "A-77", "_entrega": "x"}},
             format="json")
    kept = api.get(f"/api/v1/sales/{sale['id']}/").json()
    pickup = api.delete(f"/api/v1/sales/{sale['id']}/delivery/").json()

    assert delivered["freight"] == "19.90" and delivered["total"] == "119.90"
    assert delivered["shipping_address_detail"]["zip_code"] == "01310-100"
    assert delivered["metafields"]["_entrega"]["lead_days"] == 1
    assert kept["metafields"]["pedido_loja"] == "A-77" and kept["metafields"]["_entrega"]["table_name"] == "Motoboy"
    assert pickup["freight"] == "0.00" and pickup["total"] == "100.00" and pickup["shipping_address"] is None
    assert "_entrega" not in pickup["metafields"] and pickup["metafields"]["pedido_loja"] == "A-77"


def test_ficha_tecnica_personalizada_por_categoria(ctx):
    api = ctx.client()
    furniture = Category.all_objects.create(account=ctx.account, name="Móveis")
    bedroom = Category.all_objects.create(account=ctx.account, name="Quarto", parent=furniture)
    url = "/api/v1/metafield-definitions/"
    assembly = api.post(url, {"name": "Tempo de montagem", "type": "number", "unit": "h", "position": 1,
                              "categories": [str(furniture.pk)]}, format="json").json()
    api.post(url, {"name": "Garantia", "type": "select", "unit": "", "options": ["3 meses", "12 meses"]}, format="json")
    api.post(url, {"name": "Código no ERP", "type": "text", "show_in_specs": False}, format="json")
    variant = ctx.product(name="Cama", price="900.00", track_stock=False, category=bedroom)
    product_url = f"/api/v1/catalog/products/{variant.product_id}/"

    bad = api.patch(product_url, {"metafields": {"tempo_de_montagem": "duas", "garantia": "5 anos"}}, format="json")
    ok = api.patch(product_url, {"metafields": {"tempo_de_montagem": "2,5", "garantia": "12 meses",
                                                "codigo_no_erp": "X1", "cor_do_puxador": "Preto"}}, format="json")
    specs = api.get(f"/api/v1/pdv/products/{variant.product_id}/").json()["specs"]
    mug = ctx.product(name="Caneca", price="20", track_stock=False)
    other = api.patch(f"/api/v1/catalog/products/{mug.product_id}/", {"metafields": {"tempo_de_montagem": "abc"}},
                      format="json")

    errors = bad.json()["error"]["message"]["metafields"]
    assert assembly["key"] == "tempo_de_montagem"
    assert bad.status_code == 400 and set(errors) == {"tempo_de_montagem", "garantia"}
    assert ok.status_code == 200 and ok.json()["metafields"]["tempo_de_montagem"] == 2.5
    assert ok.json()["metafields"]["cor_do_puxador"] == "Preto"  # chave livre fica, como no StarHub
    # Ficha técnica: na ordem das definições, com unidade; a que não vai na ficha (código ERP) não aparece.
    assert [(x["label"], x["text"]) for x in specs] == [("Garantia", "12 meses"), ("Tempo de montagem", "2,5 h")]
    assert other.status_code == 200  # fora de Móveis a definição não vale: vira texto livre
