"""Avaliações: criar, moderar e o link que o cliente recebe (padrão do StarHub).

Quem chama (a tela pública do link, a retaguarda) só traduz a entrada; as regras ficam aqui:
nota de 1 a 5, comentário até 1500 caracteres, até 3 fotos, uma avaliação por cliente e
produto e uma por entrega (índices únicos no banco). Toda avaliação nasce PENDENTE.

O link da venda é assinado (não vai para o banco) e vale 120 dias: o cliente avalia, do
celular e sem login, os produtos que comprou e a entrega (quando a venda teve entrega).
"""
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import Review, Sale, SaleItem
from starrp.models.reviews import COMMENT_MAX, PHOTOS_MAX
from starrp.services import media

SALT = "starrp.review-link"
LINK_DAYS = 120


def public_name(name):
    """"Matheus Silva" vira "Matheus S.": o sobrenome inteiro não vai para a vitrine."""
    parts = (name or "").strip().split()
    if not parts:
        return "Cliente"
    return f"{parts[0]} {parts[-1][0].upper()}." if len(parts) > 1 else parts[0]


def _rating(value):
    try:
        rating = int(str(value).strip())
    except (TypeError, ValueError):
        rating = 0
    if not 1 <= rating <= 5:
        raise BusinessError("Escolha uma nota de 1 a 5 estrelas.", code="review_rating")
    return rating


def _comment(value, required):
    text = str(value or "").strip()
    if required and not text:
        raise BusinessError("Escreva um comentário sobre o produto.", code="review_comment")
    if len(text) > COMMENT_MAX:
        raise BusinessError(f"O comentário passa de {COMMENT_MAX} caracteres; encurte o texto.", code="review_comment")
    return text


@transaction.atomic
def create(*, account_id, store_id, kind, rating, comment="", product=None, sale=None, customer=None, photos=(),
           origin=Review.Origin.LINK, user=None):
    """Grava a avaliação PENDENTE (com as fotos). Tudo validado antes de gravar: foto
    recusada não deixa avaliação pela metade."""
    rating = _rating(rating)
    comment = _comment(comment, required=kind == Review.Kind.PRODUCT and origin == Review.Origin.LINK)
    photos = list(photos or [])
    if len(photos) > PHOTOS_MAX:
        raise BusinessError(f"Envie no máximo {PHOTOS_MAX} fotos.", code="review_photos")
    if kind == Review.Kind.PRODUCT and product is None:
        raise BusinessError("Informe o produto avaliado.", code="review_product")
    if kind == Review.Kind.DELIVERY and sale is None:
        raise BusinessError("A avaliação da entrega precisa da venda.", code="review_sale")
    if customer is None and sale is not None:
        customer = sale.customer
    # Sem cliente no cadastro, o "um por produto" vale para a venda (o índice do banco cobre o cliente).
    if kind == Review.Kind.PRODUCT and customer is None and sale is not None and Review.all_objects.filter(
            sale=sale, product=product, deleted_at__isnull=True).exclude(status=Review.Status.REJECTED).exists():
        raise StateConflict("Este produto já foi avaliado nesta compra.", code="review_exists")
    verified = sale is not None and sale.status == Sale.Status.COMPLETED and (
        product is None or SaleItem.all_objects.filter(sale=sale, variant__product=product,
                                                       status=SaleItem.Status.ACTIVE).exists())
    name = customer.name if customer else (sale.customer_name if sale else "")
    try:
        with transaction.atomic():
            review = Review.all_objects.create(
                account_id=account_id, store_id=store_id, kind=kind, product=product, sale=sale, customer=customer,
                public_name=public_name(name), rating=rating, comment=comment, verified_purchase=verified,
                origin=origin, created_by=user)
    except IntegrityError as error:
        what = "este produto" if kind == Review.Kind.PRODUCT else "esta entrega"
        raise StateConflict(f"Já existe uma avaliação de {what}.", code="review_exists") from error
    if photos:
        account = review.store.account
        review.photos.set([media.store_upload(account, user, f, alt=f"Foto da avaliação de {review.public_name}")
                           for f in photos])
    return review


def moderate(review, status, user, reason=""):
    """Aprova ou rejeita (rejeitar pede o motivo). Desfazer uma rejeição quando o cliente já
    mandou outra deixaria duas ativas: o banco recusa e a gente explica."""
    if status not in (Review.Status.APPROVED, Review.Status.REJECTED):
        raise BusinessError("Situação inválida para moderação.")
    if status == Review.Status.REJECTED and len(reason.strip()) < 3:
        raise BusinessError("Diga o motivo da rejeição (o cliente pode avaliar de novo).", code="reason_required")
    with transaction.atomic():
        review = Review.all_objects.select_for_update().get(pk=review.pk)
        review.status = status
        review.rejection_reason = reason.strip()[:255] if status == Review.Status.REJECTED else ""
        review.moderated_at, review.moderated_by = timezone.now(), user
        try:
            with transaction.atomic():
                review.save()
        except IntegrityError as error:
            raise StateConflict("O cliente já tem outra avaliação ativa disto; exclua uma delas antes.",
                                code="review_exists") from error
    return review


# ── link da venda ───────────────────────────────────────────────────────────
def link_token(sale):
    if sale.status != Sale.Status.COMPLETED:
        raise StateConflict("Só venda concluída pode ser avaliada.", code="sale_not_completed")
    return signing.dumps({"s": str(sale.pk)}, salt=SALT, compress=True)


def sale_from_token(token):
    try:
        data = signing.loads(token, salt=SALT, max_age=LINK_DAYS * 86400)
    except signing.SignatureExpired:
        raise BusinessError("Este link de avaliação expirou. Peça um novo à loja.", code="link_expired") from None
    except signing.BadSignature:
        raise BusinessError("Link de avaliação inválido.", code="link_invalid") from None
    sale = Sale.all_objects.select_related("store__account", "customer", "shipping_address").filter(
        pk=data.get("s"), deleted_at__isnull=True).first()
    if sale is None or sale.status != Sale.Status.COMPLETED:
        raise BusinessError("Esta compra não está disponível para avaliação.", code="link_invalid")
    return sale


def products_of(sale):
    """Os produtos da venda (um por produto, mesmo com várias variações), com a foto de capa."""
    seen, out = set(), []
    for item in SaleItem.all_objects.filter(sale=sale, status=SaleItem.Status.ACTIVE).select_related("variant__product"):
        product = item.variant.product if item.variant_id else None
        if product is None or product.pk in seen or getattr(product, "type", "") == "service":
            continue
        seen.add(product.pk)
        out.append(product)
    return out


def public_view(sale):
    reviewed = Review.all_objects.filter(sale=sale, deleted_at__isnull=True).exclude(status=Review.Status.REJECTED)
    done_products = {str(pid) for pid in reviewed.filter(kind=Review.Kind.PRODUCT).values_list("product_id", flat=True)}
    account = sale.store.account
    return {
        "store": sale.store.name,
        "logo_url": account.logo.file.url if account.logo_id else None,
        "sale": sale.number, "date": timezone.localtime(sale.completed_at).date(),
        "customer": public_name(sale.customer.name if sale.customer_id else sale.customer_name),
        "delivery": {"available": bool(sale.shipping_address_id),
                     "done": reviewed.filter(kind=Review.Kind.DELIVERY).exists()},
        "products": [{"id": str(p.pk), "name": p.name, "image": media.cover(p), "done": str(p.pk) in done_products}
                     for p in products_of(sale)],
    }


@transaction.atomic
def submit(sale, payload, files):
    """Grava o que o cliente mandou pelo link: a entrega e cada produto (nota obrigatória;
    fotos em `photos_<id do produto>`). Item já avaliado é ignorado; nada novo é erro."""
    created = []
    products = {str(p.pk): p for p in products_of(sale)}
    delivery = payload.get("delivery") or {}
    if delivery.get("rating"):
        if not sale.shipping_address_id:
            raise BusinessError("Esta compra não teve entrega.", code="no_delivery")
        if not Review.all_objects.filter(sale=sale, kind=Review.Kind.DELIVERY, deleted_at__isnull=True).exclude(
                status=Review.Status.REJECTED).exists():
            created.append(create(account_id=sale.account_id, store_id=sale.store_id, kind=Review.Kind.DELIVERY,
                                  rating=delivery["rating"], comment=delivery.get("comment", ""), sale=sale))
    for entry in payload.get("products") or []:
        product = products.get(str(entry.get("product")))
        if product is None or not entry.get("rating"):
            continue
        try:
            created.append(create(account_id=sale.account_id, store_id=sale.store_id, kind=Review.Kind.PRODUCT,
                                  rating=entry["rating"], comment=entry.get("comment", ""), product=product, sale=sale,
                                  photos=files.getlist(f"photos_{product.pk}") if files else ()))
        except StateConflict:
            continue  # já avaliado (outra aba, duplo toque): segue com os outros
    if not created:
        raise BusinessError("Dê uma nota (estrelas) a pelo menos um item.", code="review_empty")
    return created
