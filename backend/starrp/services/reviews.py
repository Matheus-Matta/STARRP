"""Avaliações: criar, moderar e o link que o cliente recebe (padrão do StarHub).

Quem chama (a tela pública do link, a retaguarda) só traduz a entrada; as regras ficam aqui:
nota de 1 a 5, comentário até 1500 caracteres, até 3 fotos, uma avaliação por cliente e
produto e uma por entrega (índices únicos no banco). Toda avaliação nasce PENDENTE.

O link (`ReviewLink`) é gravado no banco, um por TIPO do pedido: os produtos ("pedido") ou a
entrega. O cliente abre do celular, sem login; o link vale até a data limite e uma vez só: ao
enviar, fica usado e a avaliação, ligada ao pedido. Pedido e tipo já avaliados não ganham outro.
"""
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import Review, ReviewLink, Sale, SaleItem
from starrp.models.reviews import COMMENT_MAX, PHOTOS_MAX
from starrp.services import media

LINK_DAYS = 30  # padrão; a tela oferece de 7 a 120
LINK_DAYS_MAX = 120


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
           origin=Review.Origin.LINK, user=None, link=None):
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
                origin=origin, created_by=user, link=link)
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


# ── link do pedido ──────────────────────────────────────────────────────────
def _new_token(sale):
    """nº do pedido + início do id do cliente + hash aleatório (128 bits): `1234-3f9a1c2b-<32 hex>`."""
    customer = sale.customer_id.hex[:8] if sale.customer_id else "avulso"
    return f"{sale.number}-{customer}-{secrets.token_hex(16)}"


def kinds_of(sale):
    """Os tipos que a venda pode avaliar: sempre o pedido; a entrega, se teve entrega."""
    return [ReviewLink.Kind.ORDER] + ([ReviewLink.Kind.DELIVERY] if sale.shipping_address_id else [])


def done_products(sale):
    """Produtos da venda que já têm avaliação ativa: nesta venda, ou do mesmo cliente em outra
    compra (é uma avaliação por cliente e produto)."""
    active = Review.all_objects.filter(kind=Review.Kind.PRODUCT, deleted_at__isnull=True).exclude(
        status=Review.Status.REJECTED)
    mine = Q(sale=sale) | (Q(customer_id=sale.customer_id) if sale.customer_id else Q(pk__in=[]))
    return {str(pk) for pk in active.filter(mine).values_list("product_id", flat=True)}


def already_reviewed(sale, kind):
    """O tipo já foi avaliado neste pedido: link usado, entrega com avaliação ativa, ou todos os
    produtos já avaliados pelo cliente."""
    if ReviewLink.all_objects.filter(sale=sale, kind=kind, used_at__isnull=False, deleted_at__isnull=True).exists():
        return True
    if kind == ReviewLink.Kind.DELIVERY:
        return Review.all_objects.filter(sale=sale, kind=Review.Kind.DELIVERY, deleted_at__isnull=True).exclude(
            status=Review.Status.REJECTED).exists()
    products = {str(p.pk) for p in products_of(sale)}
    return bool(products) and products <= done_products(sale)


def link_state(link, now=None):
    now = now or timezone.now()
    return "used" if link.used_at else "expired" if link.expires_at <= now else "active"


@transaction.atomic
def generate_link(sale, kind, user=None, days=LINK_DAYS):
    """Link novo para o cliente avaliar um tipo do pedido. Já existe um valendo → devolve o
    mesmo (copiar de novo não cria outro). Já avaliado → recusa."""
    if sale.status != Sale.Status.COMPLETED:
        raise StateConflict("Só venda concluída pode ser avaliada.", code="sale_not_completed")
    if kind not in kinds_of(sale):
        raise BusinessError("Esta venda não teve entrega para avaliar." if kind == ReviewLink.Kind.DELIVERY
                            else "Tipo de avaliação inválido.", code="review_kind")
    days = int(days or LINK_DAYS)
    if not 1 <= days <= LINK_DAYS_MAX:
        raise BusinessError(f"O link vale de 1 a {LINK_DAYS_MAX} dias.", code="link_days")
    Sale.all_objects.select_for_update().filter(pk=sale.pk).first()  # dois cliques não geram dois links
    if already_reviewed(sale, kind):
        what = "a entrega" if kind == ReviewLink.Kind.DELIVERY else "o pedido"
        raise StateConflict(f"O cliente já avaliou {what} desta venda.", code="review_exists")
    now = timezone.now()
    current = ReviewLink.all_objects.filter(sale=sale, kind=kind, used_at__isnull=True, expires_at__gt=now,
                                            deleted_at__isnull=True).first()
    if current is not None:
        return current
    return ReviewLink.all_objects.create(account_id=sale.account_id, store_id=sale.store_id, sale=sale,
                                         customer_id=sale.customer_id, kind=kind, token=_new_token(sale),
                                         expires_at=now + timedelta(days=days), created_by=user)


def link_from_token(token, lock=False):
    """O link pelo token, ainda valendo. Usado ou vencido explica ao cliente o porquê."""
    links = ReviewLink.all_objects.select_related("sale__store__account", "sale__customer", "sale__shipping_address")
    if lock:
        links = links.select_for_update(of=("self",))
    link = links.filter(token=str(token or "")[:80], deleted_at__isnull=True).first()
    if link is None or link.sale.deleted_at is not None or link.sale.status != Sale.Status.COMPLETED:
        raise BusinessError("Link de avaliação inválido.", code="link_invalid")
    if link.used_at:
        raise BusinessError("Esta avaliação já foi enviada. Obrigado!", code="link_used")
    if link.expires_at <= timezone.now():
        raise BusinessError("Este link de avaliação expirou. Peça um novo à loja.", code="link_expired")
    return link


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


def public_view(link):
    """O que o cliente vê: só o tipo deste link (os produtos do pedido OU a entrega)."""
    sale = link.sale
    account = sale.store.account
    order = link.kind == ReviewLink.Kind.ORDER
    done = done_products(sale) if order else set()
    return {
        "kind": link.kind,
        "store": sale.store.name,
        "logo_url": account.logo.file.url if account.logo_id else None,
        "sale": sale.number, "date": timezone.localtime(sale.completed_at).date(),
        "expires_at": link.expires_at,
        "customer": public_name(sale.customer.name if sale.customer_id else sale.customer_name),
        "delivery": {"available": not order, "done": False},
        "products": [{"id": str(p.pk), "name": p.name, "image": media.cover(p), "done": str(p.pk) in done}
                     for p in products_of(sale)] if order else [],
    }


@transaction.atomic
def submit(token, payload, files):
    """Grava o que o cliente mandou pelo link e o marca como USADO (uma vez só): a entrega ou
    cada produto (nota obrigatória; fotos em `photos_<id do produto>`). Produto que o cliente
    já avaliou em outra compra é pulado; nada novo é erro e o link continua valendo."""
    link = link_from_token(token, lock=True)
    sale = link.sale
    created = []
    if link.kind == ReviewLink.Kind.DELIVERY:
        delivery = payload.get("delivery") or {}
        if delivery.get("rating"):
            created.append(create(account_id=sale.account_id, store_id=sale.store_id, kind=Review.Kind.DELIVERY,
                                  rating=delivery["rating"], comment=delivery.get("comment", ""), sale=sale, link=link))
    else:
        products = {str(p.pk): p for p in products_of(sale)}
        for entry in payload.get("products") or []:
            product = products.get(str(entry.get("product")))
            if product is None or not entry.get("rating"):
                continue
            try:
                created.append(create(account_id=sale.account_id, store_id=sale.store_id, kind=Review.Kind.PRODUCT,
                                      rating=entry["rating"], comment=entry.get("comment", ""), product=product,
                                      sale=sale, link=link,
                                      photos=files.getlist(f"photos_{product.pk}") if files else ()))
            except StateConflict:
                continue  # já avaliou este produto em outra compra: segue com os outros
    if not created:
        raise BusinessError("Dê uma nota (estrelas) a pelo menos um item.", code="review_empty")
    link.used_at = timezone.now()
    link.save(update_fields=["used_at", "updated_at"])
    return link, created
