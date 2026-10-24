"""Serviços oferecidos com o produto (montagem, garantia) — padrão do StarHub."""
from starrp.models import Category, Product, SaleItem


def _setup(ctx):
    furniture = Category.all_objects.create(account=ctx.account, name="Móveis")
    bedroom = Category.all_objects.create(account=ctx.account, name="Quarto", parent=furniture)
    wardrobe = ctx.product(name="Guarda-roupa", price="1500.00", track_stock=False, category=bedroom)
    nightstand = ctx.product(name="Criado-mudo", price="200.00", track_stock=False, category=bedroom)
    mug = ctx.product(name="Caneca", price="30.00", track_stock=False)
    assembly = ctx.product(name="Montagem", price="80.00", type=Product.Type.SERVICE, track_stock=False)
    warranty = ctx.product(name="Garantia estendida", price="50.00", type=Product.Type.SERVICE, track_stock=False)
    return furniture, wardrobe, nightstand, mug, assembly, warranty


def test_regra_por_categoria_com_faixa_e_por_produto(ctx):
    furniture, wardrobe, nightstand, mug, assembly, warranty = _setup(ctx)
    api = ctx.client()
    url = "/api/v1/catalog/service-rules/"
    # Montagem: móveis (e subcategorias) a partir de R$ 500, por R$ 120.
    by_category = api.post(url, {"service": str(assembly.product_id), "kind": "category",
                                 "categories": [str(furniture.pk)], "price_min": "500.00", "price": "120.00"},
                           format="json")
    # Garantia: só a caneca, preço padrão do serviço.
    by_product = api.post(url, {"service": str(warranty.product_id), "kind": "product",
                                "products": [str(mug.product_id)]}, format="json")
    empty = api.post(url, {"service": str(assembly.product_id), "kind": "category"}, format="json")
    not_service = api.post(url, {"service": str(mug.product_id), "kind": "product",
                                 "products": [str(wardrobe.product_id)]}, format="json")

    def offered(variant):
        body = api.get(f"/api/v1/pdv/products/{variant.product_id}/").json()
        return {(s["name"], s["price"]) for s in body["services"]}

    assert by_category.status_code == 201 and by_product.status_code == 201
    assert empty.status_code == 400 and not_service.status_code == 400
    assert offered(wardrobe) == {("Montagem", "120.00")}
    assert offered(nightstand) == set()  # abaixo da faixa
    assert offered(mug) == {("Garantia estendida", "50.00")}


def test_produto_com_servicos_entra_junto_e_sai_junto(ctx):
    furniture, wardrobe, _night, mug, assembly, _warranty = _setup(ctx)
    api = ctx.client()
    api.post("/api/v1/catalog/service-rules/", {"service": str(assembly.product_id), "kind": "category",
                                                "categories": [str(furniture.pk)]}, format="json")
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    added = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(wardrobe.pk), "quantity": "2",
                                                            "services": [str(assembly.pk)]}, format="json").json()
    parent = next(i for i in added["items"] if not i["parent_item"])
    service = next(i for i in added["items"] if i["parent_item"])

    mug_item = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(mug.pk)}, format="json").json()
    mug_id = next(i["id"] for i in mug_item["items"] if i["description"] == "Caneca")
    not_offered = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(assembly.pk), "service_for": mug_id},
                           format="json")
    duplicated = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(assembly.pk),
                                                                  "service_for": parent["id"]}, format="json")
    api.delete(f"/api/v1/sales/{sale['id']}/items/{parent['id']}/", {"reason": "Desistiu"}, format="json")

    assert service["parent_item"] == parent["id"] and service["quantity"] == "2.000" and service["unit_price"] == "80.00"
    assert added["total"] == "3160.00"
    assert not_offered.status_code == 422 and not_offered.json()["error"]["code"] == "service_not_offered"
    assert duplicated.status_code == 409
    assert SaleItem.all_objects.get(pk=service["id"]).status == SaleItem.Status.CANCELLED


def test_vitrine_traz_eixos_variantes_e_fotos(ctx):
    variant = ctx.product(name="Bermuda", price="79.90", track_stock=False, promotional_price="63.92")
    body = ctx.client().get(f"/api/v1/pdv/products/{variant.product_id}/").json()
    assert body["name"] == "Bermuda" and body["axes"] == [] and body["images"] == []
    assert body["variants"][0]["current_price"] == "63.92" and body["variants"][0]["stock"] is None
