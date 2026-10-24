"""Leitura de código no PDV: EAN/GTIN, SKU e etiqueta de balança.

Etiqueta de balança (EAN-13 começando pelo prefixo da loja, padrão "2"):

    2 PPPPPP VVVVV C   ->  prefixo (1) + PLU (6) + valor (5) + verificador (1)

O valor é o PREÇO em centavos ou o PESO em gramas, conforme
`Store.scale_barcode_mode`. No modo preço, a quantidade sai do preço/kg.

O código pode ser também o de um VOLUME (caixa "Vol 2/3"): o resultado traz a
variante e o volume, para a conferência saber que leu só uma parte da unidade.
"""
from dataclasses import dataclass
from decimal import Decimal

from starrp.models import ProductBarcode, ProductVariant, ProductVolume, Store


@dataclass
class CodeResult:
    variant: ProductVariant
    quantity: Decimal | None = None
    volume: ProductVolume | None = None


def ean_check_digit_ok(code):
    """Confere o dígito verificador GTIN-8/12/13/14 (peso 3 nas posições
    ímpares contadas da direita, sem o verificador)."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    *body, check = (int(c) for c in code)
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _scale_label(account_id, code):
    store = Store.all_objects.filter(account_id=account_id, deleted_at__isnull=True).exclude(
        scale_barcode_mode=""
    ).first()
    if store is None or not ean_check_digit_ok(code) or not code.startswith(store.scale_barcode_prefix):
        return None
    plu, value = code[1:7].lstrip("0"), Decimal(code[7:12])
    variant = _alive(account_id).filter(scale_code=plu).first()
    if variant is None:
        return None
    if store.scale_barcode_mode == Store.ScaleBarcode.WEIGHT:
        return CodeResult(variant, (value / 1000).quantize(Decimal("0.001")))
    if not variant.price:
        return CodeResult(variant)
    return CodeResult(variant, (value / 100 / variant.price).quantize(Decimal("0.001")))


def _alive(account_id):
    return ProductVariant.all_objects.filter(
        account_id=account_id, deleted_at__isnull=True, product__deleted_at__isnull=True
    ).select_related("product")


def resolve_code(account_id, code):
    code = (code or "").strip()
    if not code:
        return None
    barcode = ProductBarcode.all_objects.filter(
        account_id=account_id, code=code, deleted_at__isnull=True, variant__deleted_at__isnull=True
    ).select_related("variant__product").first()
    if barcode is not None:
        return CodeResult(barcode.variant)
    volume = ProductVolume.all_objects.filter(
        account_id=account_id, barcode=code, deleted_at__isnull=True, variant__deleted_at__isnull=True
    ).select_related("variant__product").first()
    if volume is not None:
        return CodeResult(volume.variant, volume=volume)
    scale = _scale_label(account_id, code)
    if scale is not None:
        return scale
    variant = _alive(account_id).filter(sku=code).first()
    return CodeResult(variant) if variant else None
