"""Imagens do produto e da variante (como no StarHub): envio conferido, galeria ordenada, capa."""
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image as Pillow

from starrp.models import Image, ProductImage

PRODUCTS = "/api/v1/catalog/products/"


def png(color="red", size=(40, 40), name="foto.png"):
    out = BytesIO()
    Pillow.new("RGB", size, color).save(out, format="PNG")
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/png")


def upload(api, file):
    return api.post("/api/v1/catalog/images/", {"file": file}, format="multipart")


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def test_envio_confere_reduz_e_reaproveita(ctx):
    api = ctx.client()
    first = upload(api, png(size=(3000, 1500)))
    again = upload(api, png(size=(3000, 1500), name="copia.png"))
    fake = upload(api, SimpleUploadedFile("virus.png", b"<script>alert(1)</script>", content_type="image/png"))

    assert first.status_code == 201, first.json()
    body = first.json()
    assert (body["width"], body["height"]) == (2000, 1000) and body["url"].startswith("/media/")
    assert again.json()["id"] == body["id"] and Image.all_objects.count() == 1  # mesmo arquivo, mesma imagem
    assert fake.status_code == 422 and fake.json()["error"]["code"] == "image_invalid"


def test_galeria_do_produto_e_da_variante_na_ordem_com_capa(ctx):
    api = ctx.client()
    a, b, c = (upload(api, png(color)).json()["id"] for color in ("red", "green", "blue"))
    product = api.post(PRODUCTS, {"name": "Tênis", "type": "variable", "images": [{"image": b}, {"image": a, "alt": "Lado"}],
                                  "variants": [{"sku": "T38", "price": "200", "images": [{"image": c}]},
                                               {"sku": "T39", "price": "200"}]}, format="json").json()

    assert [i["image"] for i in product["images"]] == [b, a]
    assert product["images"][1]["alt"] == "Lado" and product["cover"] == product["images"][0]["url"]
    t38 = next(v for v in product["variants"] if v["sku"] == "T38")
    assert [i["image"] for i in t38["images"]] == [c]

    # Reordena e tira a "a": a galeria enviada é a galeria.
    rows = [{**v, "images": [{"image": i["image"]} for i in v["images"]]} for v in product["variants"]]
    saved = api.patch(f"{PRODUCTS}{product['id']}/", {"images": [{"image": b}], "variants": rows}, format="json").json()
    listed = api.get(f"{PRODUCTS}?search=Tênis").json()["results"][0]
    variant = api.get(f"/api/v1/catalog/variants/?product={product['id']}&search=T38").json()["results"][0]

    assert [i["image"] for i in saved["images"]] == [b]
    assert ProductImage.all_objects.filter(product_id=product["id"], deleted_at__isnull=True).count() == 2
    assert listed["cover"] == saved["images"][0]["url"]
    assert variant["image"] == t38["images"][0]["url"]  # o PDV mostra a foto da variante
