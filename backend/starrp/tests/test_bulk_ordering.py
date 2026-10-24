"""Ações em massa (estilo Django admin) e ordenação por qualquer coluna da lista."""
from decimal import Decimal

from starrp.models import AuditLog, Category, FiscalProfile, Product, ProductVariant

PRODUCTS = "/api/v1/catalog/products/"


def _seed(ctx):
    a = ctx.product(name="Arroz", sku="ARZ", price="25.00")
    b = ctx.product(name="Feijão", sku="FEJ", price="9.00")
    c = ctx.product(name="Açúcar", sku="ACU", price="5.00")
    return [v.product for v in (a, b, c)]


def test_lista_de_acoes_respeita_o_cargo(ctx):
    admin_actions = [a["name"] for a in ctx.client().get(f"{PRODUCTS}bulk/").json()]
    seller = ctx.user("vend", "seller", is_seller=True)
    seller_actions = [a["name"] for a in ctx.client(seller).get(f"{PRODUCTS}bulk/").json()]

    assert {"delete", "activate", "deactivate", "export", "set_category", "add_tags"} <= set(admin_actions)
    assert admin_actions[-1] == "delete"  # a perigosa fica por último
    assert "delete" not in seller_actions


def test_excluir_selecionados_e_quem_nao_pode_sair_volta_com_motivo(ctx):
    api = ctx.client()
    custom = FiscalProfile.all_objects.create(account=ctx.account, name="Meu perfil")
    system = FiscalProfile.all_objects.filter(account=ctx.account, is_system=True).first()

    body = api.post("/api/v1/fiscal/profiles/bulk/", {"action": "delete", "ids": [str(custom.pk), str(system.pk)]},
                    format="json").json()

    assert body["affected"] == 1 and body["total"] == 2
    assert body["skipped"][0]["id"] == str(system.pk) and "sistema" in body["skipped"][0]["reason"]
    assert FiscalProfile.all_objects.get(pk=custom.pk).deleted_at is not None


def test_todos_vale_para_os_filtrados_da_tela(ctx):
    _seed(ctx)
    api = ctx.client()

    body = api.post(f"{PRODUCTS}bulk/?search=a%C3%A7%C3%BAcar", {"action": "deactivate", "all": True}, format="json").json()

    assert body["affected"] == 1
    assert sorted(Product.all_objects.filter(is_active=False).values_list("name", flat=True)) == ["Açúcar"]
    assert AuditLog.all_objects.filter(entity="product", reason="ação em massa").count() == 1


def test_definir_categoria_e_tags_em_massa(ctx):
    rice, beans, _ = _seed(ctx)
    category = Category.all_objects.create(account=ctx.account, name="Mercearia")
    api = ctx.client()
    ids = [str(rice.pk), str(beans.pk)]

    api.post(f"{PRODUCTS}bulk/", {"action": "set_category", "ids": ids, "params": {"category": str(category.pk)}},
             format="json")
    api.post(f"{PRODUCTS}bulk/", {"action": "add_tags", "ids": ids, "params": {"tags": ["Cesta básica"]}}, format="json")
    missing = api.post(f"{PRODUCTS}bulk/", {"action": "set_category", "ids": ids, "params": {}}, format="json")

    assert set(Product.all_objects.filter(category=category).values_list("name", flat=True)) == {"Arroz", "Feijão"}
    assert [t.name for t in Product.all_objects.get(pk=rice.pk).tags.all()] == ["Cesta básica"]
    assert missing.status_code == 400


def test_vendedor_exporta_mas_nao_exclui(ctx):
    _seed(ctx)
    seller = ctx.user("vend", "seller", is_seller=True)
    api = ctx.client(seller)
    columns = [{"key": "name", "label": "Produto"}, {"key": "price", "label": "Preço"}]

    csv = api.post(f"{PRODUCTS}bulk/?ordering=name", {"action": "export", "all": True, "params": {"columns": columns}},
                   format="json")
    delete = api.post(f"{PRODUCTS}bulk/", {"action": "delete", "all": True}, format="json")

    lines = csv.content.decode("utf-8-sig").splitlines()
    assert csv["Content-Type"].startswith("text/csv")
    assert lines[0] == "Produto;Preço" and "Arroz;25,00" in lines
    assert delete.status_code == 403


def test_ordena_por_coluna_calculada_e_recusa_coluna_desconhecida(ctx):
    _seed(ctx)
    ProductVariant.all_objects.filter(sku="ACU").update(price=Decimal("99.00"))
    api = ctx.client()

    by_price = [p["name"] for p in api.get(PRODUCTS, {"ordering": "-price"}).json()["results"]]
    by_name = [p["name"] for p in api.get(PRODUCTS, {"ordering": "name"}).json()["results"]]
    by_sku = [p["sku"] for p in api.get(PRODUCTS, {"ordering": "-sku"}).json()["results"]]
    wrong = api.get(PRODUCTS, {"ordering": "senha"})

    assert by_price == ["Açúcar", "Arroz", "Feijão"]
    assert by_name[0] in {"Arroz", "Açúcar"} and by_name[-1] == "Feijão"
    assert by_sku == ["FEJ", "ARZ", "ACU"]
    assert wrong.status_code == 400
