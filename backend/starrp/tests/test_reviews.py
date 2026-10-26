"""Avaliações (padrão StarHub): link da venda, uma por produto/entrega, moderação."""
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from starrp.models import Customer, Review

from .test_sale_flow import _stock


def _png():
    import io

    from PIL import Image as Pil

    buf = io.BytesIO()
    Pil.new("RGB", (10, 10), "red").save(buf, "PNG")
    return SimpleUploadedFile("foto.png", buf.getvalue(), content_type="image/png")


@pytest.fixture
def sold(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Matheus Silva", phone="11988887777")
    product = ctx.product(name="Mesa", price="50.00")
    _stock(ctx, product, 10)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {"customer": str(customer.pk)}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "50.00"}]}, format="json")
    return ctx, api, sale, product


def test_cliente_avalia_pelo_link_e_nao_repete(sold):
    ctx, api, sale, variant = sold
    link = api.get("/api/v1/reviews/link/", {"sale": sale["id"]}).json()
    token = link["url"].rsplit("/", 1)[1]
    public = APIClient()

    view = public.get(f"/api/v1/public/reviews/{token}/").json()
    product_id = view["products"][0]["id"]
    sent = public.post(f"/api/v1/public/reviews/{token}/", {
        "data": json.dumps({"products": [{"product": product_id, "rating": 5, "comment": "Ótima mesa"}]}),
        f"photos_{product_id}": [_png()]}, format="multipart")
    again = public.post(f"/api/v1/public/reviews/{token}/", {
        "data": json.dumps({"products": [{"product": product_id, "rating": 1, "comment": "De novo"}]})}, format="multipart")
    bad = public.get("/api/v1/public/reviews/token-falso/")

    assert "avaliar/" in link["url"] and "menos de 1 minuto" in link["text"]
    assert view["products"][0]["done"] is False and view["delivery"]["available"] is False
    assert sent.status_code == 201, sent.json()
    review = Review.all_objects.get()
    assert (review.rating, review.status, review.verified_purchase, review.photos.count()) == (5, "pending", True, 1)
    assert again.status_code == 422 and again.json()["error"]["code"] == "review_empty"
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "link_invalid"


def test_moderacao_aprova_e_rejeita_com_motivo(sold):
    ctx, api, sale, variant = sold
    created = api.post("/api/v1/reviews/", {"kind": "product", "product": str(variant.product_id), "rating": 4,
                                            "comment": "Contou no balcão", "sale": sale["id"]}, format="json")
    review_id = created.json()["id"]
    no_reason = api.post(f"/api/v1/reviews/{review_id}/reject/", {}, format="json")
    approved = api.post(f"/api/v1/reviews/{review_id}/approve/", {}, format="json")
    rejected = api.post(f"/api/v1/reviews/{review_id}/reject/", {"reason": "Ofensivo"}, format="json")

    assert created.status_code == 201 and created.json()["origin"] == "backoffice", created.json()
    assert no_reason.status_code == 422
    assert approved.json()["status"] == "approved" and approved.json()["moderated_by_name"] is not None
    assert rejected.json()["status"] == "rejected" and rejected.json()["rejection_reason"] == "Ofensivo"
    # Rejeitada não conta: dá para avaliar de novo o mesmo produto na mesma compra.
    again = api.post("/api/v1/reviews/", {"kind": "product", "product": str(variant.product_id), "rating": 5,
                                          "sale": sale["id"]}, format="json")
    assert again.status_code == 201
