"""Imagens do catálogo, como no StarHub: o acervo (`Image`) e a galeria ordenada
do produto e de cada variante (`ProductImage`, com `variant` vazio = do produto).

Envio (`store_upload`): só imagem de verdade (o Pillow abre e confere), até 8 MB,
JPEG/PNG/WEBP/GIF. Lado maior que 2000 px é reduzido (foto de celular de 12 MP
vira ~400 KB). O mesmo arquivo enviado de novo reaproveita a imagem (checksum).

Galeria (`sync_gallery`): a lista enviada É a galeria, na ordem dela:

    sync_gallery(produto, None, [{"image": 7}, {"image": 9, "alt": "Verso"}])
    -> a 7 fica em 1º (capa), a 9 em 2º, as outras do produto saem.

Capa (`cover`): a 1ª imagem do produto; sem ela, a 1ª da variante padrão.
"""
import hashlib
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image as Pillow
from PIL import UnidentifiedImageError

from starrp.core.errors import BusinessError
from starrp.models import Image, ProductImage

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 2000
FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def _shrink(data, picture):
    """Reduz o lado maior para MAX_SIDE mantendo o formato (GIF animado fica como veio)."""
    if max(picture.size) <= MAX_SIDE or picture.format == "GIF":
        return data, picture.size
    picture.thumbnail((MAX_SIDE, MAX_SIDE))
    out = BytesIO()
    options = {"quality": 86, "optimize": True} if picture.format in {"JPEG", "WEBP"} else {"optimize": True}
    picture.save(out, format=picture.format, **options)
    return out.getvalue(), picture.size


@transaction.atomic
def store_upload(account, user, upload, alt=""):
    data = upload.read()
    if len(data) > MAX_BYTES:
        raise BusinessError("Imagem grande demais: o limite é 8 MB.", code="image_too_large")
    try:
        Pillow.open(BytesIO(data)).verify()
        picture = Pillow.open(BytesIO(data))
        picture.load()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise BusinessError("O arquivo não é uma imagem (use JPG, PNG, WEBP ou GIF).", code="image_invalid") from None
    if picture.format not in FORMATS:
        raise BusinessError("Formato não aceito: use JPG, PNG, WEBP ou GIF.", code="image_invalid")
    checksum = hashlib.sha256(data).hexdigest()
    same = Image.all_objects.filter(account=account, checksum=checksum, deleted_at__isnull=True).first()
    if same is not None:
        return same
    content, (width, height) = _shrink(data, picture)
    image = Image(account=account, created_by=user, original_name=upload.name[:255], checksum=checksum,
                  content_type=Pillow.MIME.get(picture.format, ""), size=len(content), width=width, height=height,
                  alt_text=alt[:255])
    image.file.save(f"{checksum[:16]}.{FORMATS[picture.format]}", ContentFile(content), save=False)
    image.save()
    return image


def gallery(links, variant_id=None):
    """Itens da galeria no formato da tela: [{"image", "url", "alt", "width", "height"}], na ordem."""
    rows = sorted((link for link in links if link.deleted_at is None and link.variant_id == variant_id),
                  key=lambda link: (link.position, link.created_at))
    return [{"image": str(link.image_id), "url": link.image.file.url, "alt": link.image.alt_text,
             "width": link.image.width, "height": link.image.height} for link in rows]


@transaction.atomic
def sync_gallery(product, variant, items, user=None):
    """Grava a galeria do produto (`variant=None`) ou da variante na ordem enviada."""
    scope = ProductImage.all_objects.filter(product=product, variant=variant, deleted_at__isnull=True)
    leftover = {link.image_id: link for link in scope}
    for position, item in enumerate(items or []):
        image = item["image"] if isinstance(item["image"], Image) else Image.objects.get(pk=item["image"])
        # Uma imagem fica num lugar só do produto: vinda de outra galeria dele, muda de lugar.
        link = leftover.pop(image.pk, None) or ProductImage.all_objects.filter(
            product=product, image=image, deleted_at__isnull=True).first() or ProductImage(
            account_id=product.account_id, product=product, image=image, created_by=user)
        link.variant, link.position = variant, position
        link.save()
        alt = (item.get("alt") or "").strip()[:255]
        if alt and alt != image.alt_text:
            Image.all_objects.filter(pk=image.pk).update(alt_text=alt)
    for link in leftover.values():
        link.delete()


def cover(product):
    """URL da capa (lista, PDV, loja virtual) com as imagens já pré-carregadas no produto."""
    links = [link for link in product.images.all() if link.deleted_at is None]
    if not links:
        return None
    default = next((v.pk for v in product.variants.all() if v.is_default and v.deleted_at is None), None)
    links.sort(key=lambda link: (link.variant_id is not None, link.variant_id != default, link.position))
    return links[0].image.file.url
