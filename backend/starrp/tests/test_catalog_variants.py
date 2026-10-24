"""Produto no modelo do StarHub: produto + variantes, grade em tabela, tipos e volumes."""
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.models import (
    DiscountTable, LabelTemplate, Product, ProductVariant, Promotion, PromotionProduct, StockDocument, StockMovement,
)
from starrp.services import stock

from .nfe_fixture import UNIT_EAN

PRODUCTS = "/api/v1/catalog/products/"


def _create(api, **body):
    response = api.post(PRODUCTS, body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_produto_simples_nasce_com_a_variante_padrao_e_codigo(ctx):
    api = ctx.client()

    body = _create(api, name="Café 500g", variants=[{"sku": "CAF500", "price": "18.90",
                                                      "barcodes": [{"code": UNIT_EAN, "is_primary": True}]}])

    assert body["type"] == "simple" and body["sku"] == "CAF500" and body["price"] == "18.90"
    [variant] = body["variants"]
    assert variant["is_default"] and variant["barcodes"][0]["code"] == UNIT_EAN
    lookup = api.get("/api/v1/catalog/variants/lookup/", {"code": UNIT_EAN}).json()
    assert lookup["id"] == variant["id"] and lookup["display_name"] == "Café 500g"


def test_produto_simples_nao_aceita_duas_variantes(ctx):
    response = ctx.client().post(PRODUCTS, {"name": "Arroz", "variants": [
        {"sku": "A1", "price": "5"}, {"sku": "A2", "price": "6"}]}, format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "single_variant_type"


def test_grade_vira_variantes_e_a_padrao_vira_a_primeira_combinacao(ctx):
    """O simples que ganha grade não perde SKU nem estoque: a variante padrão vira "P / Azul"."""
    api = ctx.client()
    product = _create(api, name="Camiseta", reference="CAM", variants=[{"sku": "CAM", "price": "50.00"}])
    original = ProductVariant.all_objects.get(pk=product["variants"][0]["id"])
    stock.move(original, stock.default_warehouse(ctx.store), Decimal("4"), StockMovement.Kind.PURCHASE)

    url = f"{PRODUCTS}{product['id']}/generate-variants/"
    grid = {"attributes": {"Tamanho": ["P", "M"], "Cor": ["Azul", "azul ", "Preto"]}}
    body = api.post(url, grid, format="json").json()
    again = api.post(url, grid, format="json").json()

    names = sorted(v["name"] for v in body["variants"])
    assert body["type"] == "variable"
    assert names == ["Azul / M", "Azul / P", "Preto / M", "Preto / P"]  # eixos em ordem alfabética
    assert len(again["variants"]) == 4  # rodar de novo não duplica; "azul " é a mesma cor
    original.refresh_from_db()
    assert original.name and original.sku == "CAM" and stock.available(original) == Decimal("4")
    skus = {v["sku"] for v in body["variants"]}
    assert "CAM" in skus and any(s.startswith("CAM-") for s in skus)


def test_variante_com_saldo_nao_e_excluida(ctx):
    api = ctx.client()
    product = _create(api, name="Tênis", type="variable", variants=[{"sku": "T38", "price": "200"},
                                                                    {"sku": "T39", "price": "200"}])
    t38 = ProductVariant.all_objects.get(sku="T38")
    stock.move(t38, stock.default_warehouse(ctx.store), Decimal("1"), StockMovement.Kind.PURCHASE)

    keep_only_39 = [v for v in product["variants"] if v["sku"] == "T39"]
    response = api.patch(f"{PRODUCTS}{product['id']}/", {"variants": keep_only_39}, format="json")

    assert response.status_code == 422 and response.json()["error"]["code"] == "variant_has_stock"


def test_promocao_do_produto_vale_para_todas_as_variantes(ctx):
    api = ctx.client()
    product = _create(api, name="Bermuda", type="variable", variants=[{"sku": "B-P", "price": "80"},
                                                                     {"sku": "B-G", "price": "90"}])
    table = DiscountTable.all_objects.create(account=ctx.account, name="Liquida")
    rule = Promotion.all_objects.create(account=ctx.account, table=table, name="Bermudas -10%", target="products",
                                        kind="percent", value=Decimal("10"))
    PromotionProduct.all_objects.create(account=ctx.account, promotion=rule, product_id=product["id"])

    rows = api.get("/api/v1/catalog/variants/", {"product": product["id"]}).json()["results"]

    assert sorted(row["current_price"] for row in rows) == ["72.00", "81.00"]


def test_kit_baixa_as_variantes_componentes(ctx):
    mug, spoon = ctx.product(name="Caneca", sku="CAN", price="10"), ctx.product(name="Colher", sku="COL", price="5")
    warehouse = stock.default_warehouse(ctx.store)
    stock.move(mug, warehouse, Decimal("10"), StockMovement.Kind.PURCHASE)
    stock.move(spoon, warehouse, Decimal("10"), StockMovement.Kind.PURCHASE)
    kit = ctx.product(name="Kit café", sku="KIT", price="30", type="kit")
    api = ctx.client()
    for component, qty in ((mug, "2"), (spoon, "1")):
        api.post("/api/v1/catalog/components/", {"kit": str(kit.product_id), "component": str(component.pk),
                                                 "quantity": qty}, format="json")

    stock.move_with_components(kit, warehouse, Decimal("-3"), StockMovement.Kind.SALE, source_key="t")

    assert stock.available(mug) == Decimal("4") and stock.available(spoon) == Decimal("7")
    assert stock.available(kit) == 0  # kit não tem saldo próprio
    assert kit.track_stock is False


@pytest.fixture
def wardrobe(ctx):
    """Guarda-roupa em 3 volumes, cada caixa com código, peso e medidas."""
    ctx.account.extra_modules = ["stock"]
    ctx.account.save()
    body = _create(ctx.client(), name="Guarda-roupa Casal", variants=[{"sku": "GR6P", "price": "1500", "volumes": [
        {"description": "Laterais", "barcode": "GR6P-V1", "gross_weight": "40", "height_cm": "200",
         "width_cm": "50", "length_cm": "10"},
        {"description": "Portas", "barcode": "GR6P-V2", "gross_weight": "35", "height_cm": "190",
         "width_cm": "45", "length_cm": "10"},
        {"description": "Ferragens", "barcode": "GR6P-V3", "gross_weight": "5", "height_cm": "30",
         "width_cm": "20", "length_cm": "10"},
    ]}])
    assert [v["number"] for v in body["variants"][0]["volumes"]] == [1, 2, 3]
    return ProductVariant.all_objects.get(pk=body["variants"][0]["id"])


def _entry(ctx, variant, quantity):
    doc = StockDocument.all_objects.create(
        account=ctx.account, store=ctx.store, kind="entry", number=1, warehouse=stock.default_warehouse(ctx.store),
        effective_date=timezone.localdate())
    doc.items.create(account=ctx.account, variant=variant, quantity=Decimal(quantity))
    return doc


def test_conferencia_por_volume_so_conta_a_unidade_completa(ctx, wardrobe):
    doc = _entry(ctx, wardrobe, "2")

    scans = ["GR6P-V1", "GR6P-V2", "GR6P-V3", "GR6P-V1", "GR6P-V2", "NAO-EXISTE"]
    body = ctx.client().post(f"/api/v1/stock/documents/{doc.pk}/conference/", {"codes": scans}, format="json").json()

    [row] = body["rows"]
    assert Decimal(row["counted_quantity"]) == 1 and Decimal(row["difference_quantity"]) == -1
    assert row["loose_volumes"] == ["Vol 1", "Vol 2"] and row["missing_volumes"] == ["Vol 3"]
    assert body["unknown_codes"] == ["NAO-EXISTE"] and body["ok"] is False


def test_separacao_traz_caixas_peso_e_cubagem(ctx, wardrobe):
    warehouse = stock.default_warehouse(ctx.store)
    stock.move(wardrobe, warehouse, Decimal("5"), StockMovement.Kind.PURCHASE)
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="exit", number=2,
                                           warehouse=warehouse, effective_date=timezone.localdate())
    doc.items.create(account=ctx.account, variant=wardrobe, quantity=Decimal("2"))

    load = ctx.client().get(f"/api/v1/stock/documents/{doc.pk}/picking-list/").json()["load"]

    assert load["box_count"] == 6  # 2 guarda-roupas × 3 caixas
    assert Decimal(load["gross_weight"]) == Decimal("160")  # (40 + 35 + 5) × 2
    # (0,1 + 0,0855 + 0,006) m³ × 2
    assert Decimal(load["cubic_meters"]) == Decimal("0.3830")
    assert [box["label"] for box in load["boxes"]] == ["Vol 1/3", "Vol 2/3", "Vol 3/3"]


def test_etiqueta_de_volume_sai_uma_por_caixa_de_cada_unidade(ctx, wardrobe):
    doc = _entry(ctx, wardrobe, "2")
    template = LabelTemplate.all_objects.create(account=ctx.account, name="Caixas", subject="volume",
                                                code_type="code128")

    html = ctx.client().get(f"/api/v1/stock/documents/{doc.pk}/labels/", {"template": str(template.pk)}).content.decode()

    assert html.count('class="label"') == 6
    assert "Vol 2/3" in html and "Portas" in html


def test_codigo_de_volume_no_pdv_identifica_a_variante(ctx, wardrobe):
    lookup = ctx.client().get("/api/v1/catalog/variants/lookup/", {"code": "GR6P-V2"}).json()

    assert lookup["id"] == str(wardrobe.pk) and lookup["volume"] == 2 and lookup["volume_count"] == 3


def test_tipo_servico_nao_estoca(ctx):
    service = ctx.product(name="Montagem", sku="MONT", price="120", type="service")

    assert stock.move(service, stock.default_warehouse(ctx.store), Decimal("1"), StockMovement.Kind.PURCHASE) == []
    assert Product.all_objects.get(pk=service.product_id).type == "service"


def test_produto_com_grade_nasce_num_salvar_so(ctx):
    body = _create(ctx.client(), name="Meia", type="variable", grid={"Tamanho": ["P", "M", "G"]})

    assert body["variant_count"] == 3 and sorted(v["name"] for v in body["variants"]) == ["G", "M", "P"]
    assert sum(v["is_default"] for v in body["variants"]) == 1


def test_tags_nascem_no_salvar_sem_duplicar_e_filtram(ctx):
    api = ctx.client()
    body = _create(api, name="Chinelo", tags=["Verão", "verão ", "Lançamento"],
                   variants=[{"sku": "CHI", "price": "30"}])
    _create(api, name="Bota", tags=["Inverno"], variants=[{"sku": "BOT", "price": "200"}])

    assert sorted(body["tags"]) == ["Lançamento", "Verão"]
    names = [t["name"] for t in api.get("/api/v1/tags/", {"scope": "product"}).json()["results"]]
    assert names == ["Inverno", "Lançamento", "Verão"]
    found = api.get(PRODUCTS, {"tag": "VERÃO"}).json()["results"]
    assert [p["name"] for p in found] == ["Chinelo"]
    customer = api.post("/api/v1/customers/", {"name": "Ana", "tags": ["Vip"]}, format="json").json()
    assert customer["tags"] == ["Vip"]
    assert "Vip" not in [t["name"] for t in api.get("/api/v1/tags/", {"scope": "product"}).json()["results"]]


def test_sku_gerado_nunca_repete(ctx):
    api = ctx.client()
    first = _create(api, name="Item lote A", variants=[{"price": "1"}])
    second = _create(api, name="Item lote B", variants=[{"price": "1"}])
    typed = api.post(PRODUCTS, {"name": "Outro", "variants": [{"sku": first["sku"], "price": "1"}]}, format="json")

    assert first["sku"] == "ITEMLOTE-1" and second["sku"] == "ITEMLOTE-1-2"
    assert typed.status_code == 409  # SKU digitado repetido continua sendo erro


def test_salvar_o_produto_mantem_as_variantes_e_o_estoque(ctx):
    """Editar o produto (o formulário manda a lista inteira de volta) não pode recriar as variantes."""
    api = ctx.client()
    body = _create(api, name="Tênis", type="variable", variants=[{"sku": "T38", "price": "200"}, {"sku": "T39", "price": "200"}])
    t38 = ProductVariant.all_objects.get(sku="T38")
    stock.move(t38, stock.default_warehouse(ctx.store), Decimal("3"), StockMovement.Kind.PURCHASE)

    rows = [{**v, "price": "210.00"} for v in body["variants"]]
    response = api.patch(f"{PRODUCTS}{body['id']}/", {"variants": rows}, format="json")

    assert response.status_code == 200, response.json()
    assert sorted(v["id"] for v in response.json()["variants"]) == sorted(v["id"] for v in body["variants"])
    assert ProductVariant.all_objects.filter(product_id=body["id"]).count() == 2  # nenhuma apagada e recriada
    t38.refresh_from_db()
    assert t38.price == Decimal("210.00") and stock.available(t38) == Decimal("3")


def _grid_product(api):
    return _create(api, name="Camisa", reference="CAMI", type="variable",
                   grid={"Tamanho": ["P", "M"], "Cor": ["Azul", "Preto"]})


def _save_grid(api, product, grid):
    """Como o formulário salva: a lista de variantes de volta + a grade nova."""
    response = api.patch(f"{PRODUCTS}{product['id']}/", {"variants": product["variants"], "grid": grid}, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def test_tirar_um_eixo_junta_as_variantes_e_mantem_sku_e_estoque(ctx):
    """Sem o eixo Cor, "P / Azul" vira "P" (mesmo SKU e saldo) e "P / Preto" sai."""
    api = ctx.client()
    product = _grid_product(api)
    p_azul = ProductVariant.all_objects.get(product_id=product["id"], name="Azul / P")
    stock.move(p_azul, stock.default_warehouse(ctx.store), Decimal("2"), StockMovement.Kind.PURCHASE)

    body = _save_grid(api, product, {"Tamanho": ["P", "M"]})

    assert sorted(v["name"] for v in body["variants"]) == ["M", "P"]
    kept = next(v for v in body["variants"] if v["name"] == "P")
    assert kept["id"] == str(p_azul.pk) and kept["sku"] == p_azul.sku and stock.available(p_azul) == Decimal("2")
    assert all(len(v["options"]) == 1 for v in body["variants"])


def test_tirar_um_valor_exclui_as_variantes_dele(ctx):
    api = ctx.client()
    body = _save_grid(api, (product := _grid_product(api)), {"Tamanho": ["P"], "Cor": ["Azul", "Preto"]})

    assert sorted(v["name"] for v in body["variants"]) == ["Azul / P", "Preto / P"]
    assert ProductVariant.all_objects.filter(product_id=product["id"], deleted_at__isnull=True).count() == 2


def test_eixo_novo_estende_as_variantes_existentes_sem_duplicar(ctx):
    """Voltagem nova: "P / Azul" vira "P / Azul / 110" (mesmo id) e as de 220 são criadas — sem sobrar "P / Azul"."""
    api = ctx.client()
    product = _grid_product(api)
    before = {v["name"]: v["id"] for v in product["variants"]}

    body = _save_grid(api, product, {"Tamanho": ["P", "M"], "Cor": ["Azul", "Preto"], "Voltagem": ["110", "220"]})

    names = {v["name"]: v["id"] for v in body["variants"]}
    assert len(names) == 8 and all(len(v["options"]) == 3 for v in body["variants"])
    assert names["Azul / P / 110"] == before["Azul / P"]
    assert all(v["sku"] for v in body["variants"])


def test_tirar_eixo_com_saldo_na_variante_que_sairia_para_e_avisa(ctx):
    api = ctx.client()
    product = _grid_product(api)
    p_preto = ProductVariant.all_objects.get(product_id=product["id"], name="Preto / P")
    stock.move(p_preto, stock.default_warehouse(ctx.store), Decimal("1"), StockMovement.Kind.PURCHASE)

    response = api.patch(f"{PRODUCTS}{product['id']}/", {"variants": product["variants"], "grid": {"Tamanho": ["P", "M"]}},
                         format="json")

    assert response.status_code == 422 and response.json()["error"]["code"] == "variant_has_stock"
    assert ProductVariant.all_objects.filter(product_id=product["id"], deleted_at__isnull=True).count() == 4


def test_descricao_rica_e_limpa_e_slug_sai_do_nome(ctx):
    """O editor manda HTML: formatação fica, script e evento somem; o slug vem do nome e não repete."""
    api = ctx.client()
    dirty = '<p onclick="roubar()">Algodão <strong>100%</strong></p><script>alert(1)</script><a href="javascript:x()">x</a>'
    first = _create(api, name="Camiseta Básica", description=dirty, variants=[{"sku": "CB1", "price": "10"}])
    second = _create(api, name="Camiseta Básica", variants=[{"sku": "CB2", "price": "10"}])

    assert first["description"].startswith("<p>Algodão <strong>100%</strong></p>")
    assert "script" not in first["description"] and "onclick" not in first["description"]
    assert "javascript" not in first["description"]
    assert (first["slug"], second["slug"]) == ("camiseta-basica", "camiseta-basica-2")
