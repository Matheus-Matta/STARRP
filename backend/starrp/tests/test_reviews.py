"""Avaliações (padrão StarHub): link da venda, uma por produto/entrega, moderação."""
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from starrp.models import Customer, CustomerAddress, Review, ReviewLink, Sale

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


def _gen(api, sale, kind="order", **extra):
    return api.post("/api/v1/reviews/links/", {"sale": sale["id"], "kind": kind, **extra}, format="json")


def _row(response, kind="order"):
    return next(r for r in response.json() if r["kind"] == kind)


def test_cliente_avalia_pelo_link_uma_vez_e_fica_no_pedido(sold):
    ctx, api, sale, variant = sold
    before = api.get("/api/v1/reviews/links/", {"sale": sale["id"]}).json()
    link = _row(_gen(api, sale))
    token = link["url"].rsplit("/", 1)[1]
    same = _row(_gen(api, sale))  # gerar de novo enquanto vale = o mesmo link
    public = APIClient()

    view = public.get(f"/api/v1/public/reviews/{token}/").json()
    product_id = view["products"][0]["id"]
    sent = public.post(f"/api/v1/public/reviews/{token}/", {
        "data": json.dumps({"products": [{"product": product_id, "rating": 5, "comment": "Ótima mesa"}]}),
        f"photos_{product_id}": [_png()]}, format="multipart")
    again = public.post(f"/api/v1/public/reviews/{token}/", {
        "data": json.dumps({"products": [{"product": product_id, "rating": 1, "comment": "De novo"}]})}, format="multipart")
    reopen = public.get(f"/api/v1/public/reviews/{token}/")
    regenerate = _gen(api, sale)
    after = _row(api.get("/api/v1/reviews/links/", {"sale": sale["id"]}))
    bad = public.get("/api/v1/public/reviews/token-falso/")

    # nº do pedido + início do id do cliente + hash aleatório
    number, customer, secret = token.split("-")
    assert [r["kind"] for r in before] == ["order"] and before[0]["state"] == "none"  # sem entrega: só o pedido
    assert number == str(sale["number"]) and customer == sale["customer"].replace("-", "")[:8] and len(secret) == 32
    assert link["state"] == "active" and "menos de 1 minuto" in link["text"] and same["url"] == link["url"]
    assert view["kind"] == "order" and view["delivery"]["available"] is False
    assert sent.status_code == 201, sent.json()
    review = Review.all_objects.get()
    assert (review.rating, review.status, review.verified_purchase, review.photos.count()) == (5, "pending", True, 1)
    assert review.link.token == token and str(review.sale_id) == sale["id"]
    assert again.status_code == 422 and again.json()["error"]["code"] == "link_used"
    assert reopen.status_code == 422 and reopen.json()["error"]["code"] == "link_used"
    assert regenerate.status_code == 409 and regenerate.json()["error"]["code"] == "review_exists"
    assert after["state"] == "used" and after["reviewed"] is True and after["used_at"]
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "link_invalid"


def test_link_vence_no_prazo_e_entrega_so_com_entrega(sold):
    ctx, api, sale, variant = sold
    short = _row(_gen(api, sale, days=7))
    too_long = _gen(api, sale, days=365)
    no_delivery = _gen(api, sale, kind="delivery")
    ReviewLink.all_objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    expired = APIClient().get(f"/api/v1/public/reviews/{short['url'].rsplit('/', 1)[1]}/")
    fresh = _row(_gen(api, sale))

    assert (parse_datetime(short["expires_at"]) - timezone.now()).days == 6  # 7 dias (menos os segundos)
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "link_days"
    assert no_delivery.status_code == 422 and no_delivery.json()["error"]["code"] == "review_kind"
    assert expired.status_code == 422 and expired.json()["error"]["code"] == "link_expired"
    assert fresh["state"] == "active" and fresh["url"] != short["url"]  # vencido: gera outro


def test_entrega_tem_link_proprio(sold):
    ctx, api, sale, variant = sold
    address = CustomerAddress.all_objects.create(account=ctx.account, customer_id=sale["customer"], street="Rua A",
                                                 number="1", city="São Paulo", state="SP")
    Sale.all_objects.filter(pk=sale["id"]).update(shipping_address=address)
    rows = api.get("/api/v1/reviews/links/", {"sale": sale["id"]}).json()
    delivery = _row(_gen(api, sale, kind="delivery"), "delivery")
    token = delivery["url"].rsplit("/", 1)[1]
    public = APIClient()

    view = public.get(f"/api/v1/public/reviews/{token}/").json()
    sent = public.post(f"/api/v1/public/reviews/{token}/", {"data": json.dumps({"delivery": {"rating": 4}})},
                       format="multipart")
    order = _row(_gen(api, sale))  # avaliar a entrega não gasta o link do pedido

    assert [r["kind"] for r in rows] == ["order", "delivery"]
    assert view["kind"] == "delivery" and view["products"] == [] and view["delivery"]["available"] is True
    assert sent.status_code == 201 and Review.all_objects.get().kind == "delivery"
    assert order["state"] == "active"


def test_produto_ja_avaliado_em_outra_compra_aparece_avaliado(sold):
    ctx, api, sale, variant = sold
    Review.all_objects.create(account=ctx.account, store=ctx.store, kind="product", product_id=variant.product_id,
                              customer_id=sale["customer"], public_name="Matheus S.", rating=4)
    blocked = _gen(api, sale)  # o único produto da venda já foi avaliado pelo cliente
    rows = api.get("/api/v1/reviews/links/", {"sale": sale["id"]}).json()

    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "review_exists"
    assert rows[0]["reviewed"] is True and rows[0]["state"] == "used"


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


def test_relatorios_trazem_o_produto_com_a_nota(sold):
    ctx, api, sale, variant = sold
    Review.all_objects.create(account=ctx.account, store=ctx.store, kind="product", product_id=variant.product_id,
                              sale_id=sale["id"], customer_id=sale["customer"], public_name="Matheus S.", rating=4,
                              comment="Firme")

    def book(slug, **params):
        body = api.get(f"/api/v1/reports/book/{slug}/", {"periodo": "30", **params}).json()
        return {b["title"]: b for b in body["blocks"]}, body

    vendas, _ = book("vendas")
    abc, _ = book("curva-abc")
    avaliacoes, body = book("avaliacoes", product=str(variant.product_id))

    produto = vendas["Produtos vendidos e a nota deles"]["rows"][0]
    venda = vendas["Vendas do período e a nota do cliente"]["rows"][0]
    linha = abc["Curva completa"]["rows"][0]
    ficha = avaliacoes["Produtos e as avaliações deles"]["rows"][0]
    assert (produto["product"], Decimal(produto["rating"]), produto["reviews"]) == ("Mesa", 4, 1)
    assert Decimal(venda["order_rating"]) == 4 and venda["delivery_rating"] is None
    assert (Decimal(linha["rating"]), linha["reviews"]) == (4, 1)
    assert (ficha["product"], ficha["s4"], ficha["sales"], Decimal(ficha["coverage"]), ficha["last"]) == ("Mesa", 1, 1, 100, "Firme")
    assert any(f["name"] == "product" for f in body["filters"])
