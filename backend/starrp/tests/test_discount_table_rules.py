"""Regras de desconto DENTRO da tabela: criar, reordenar, tirar e o preço no PDV."""
from starrp.models import Category, Promotion


def test_tabela_com_regras_dentro(ctx):
    beach = Category.all_objects.create(account=ctx.account, name="Moda praia")
    shorts = ctx.product(name="Bermuda", price="100.00", track_stock=False, category=beach)
    cap = ctx.product(name="Boné", price="50.00", track_stock=False)
    api = ctx.client()
    created = api.post("/api/v1/promotions/tables/", {"name": "Liquida verão", "rules": [
        {"name": "Moda praia -20%", "target": "categories", "kind": "percent", "value": "20",
         "categories": [str(beach.pk)]},
        {"name": "Boné por 39,90", "target": "products", "kind": "percent", "value": "0",
         "products": [{"product": str(cap.product_id), "promotional_price": "39.90"}]},
    ]}, format="json")
    table = created.json()

    shorts_price = api.get(f"/api/v1/pdv/products/{shorts.product_id}/").json()["variants"][0]["current_price"]
    cap_price = api.get(f"/api/v1/pdv/products/{cap.product_id}/").json()["variants"][0]["current_price"]

    first, second = table["rules"]
    edited = api.patch(f"/api/v1/promotions/tables/{table['id']}/", {"rules": [
        {**second, "products": [{"product": str(cap.product_id), "promotional_price": "35.00"}]},
    ]}, format="json").json()
    bad = api.post("/api/v1/promotions/tables/", {"name": "Ruim", "rules": [
        {"name": "Sem categoria", "target": "categories", "kind": "percent", "value": "10"}]}, format="json")
    over = api.post("/api/v1/promotions/tables/", {"name": "Ruim 2", "rules": [
        {"name": "Tudo", "target": "all", "kind": "percent", "value": "150"}]}, format="json")

    assert created.status_code == 201 and table["rule_count"] == 2
    assert [r["name"] for r in table["rules"]] == ["Moda praia -20%", "Boné por 39,90"]
    assert shorts_price == "80.00" and cap_price == "39.90"
    assert [r["id"] for r in edited["rules"]] == [second["id"]]  # a que ficou é a mesma regra
    assert edited["rules"][0]["products"][0]["promotional_price"] == "35.00"
    assert Promotion.all_objects.get(pk=first["id"]).deleted_at is not None  # saiu da lista = excluída
    assert Promotion.all_objects.get(pk=second["id"]).position == 1  # a ordem é a prioridade
    assert bad.status_code == 400 and over.status_code == 400
