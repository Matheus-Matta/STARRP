"""Leitura de código no PDV: EAN/GTIN, SKU e etiqueta de balança.

Etiqueta de balança (EAN-13 começando pelo prefixo da loja, padrão "2"):

    2 PPPPPP VVVVV C   ->  prefixo (1) + PLU (6) + valor (5) + verificador (1)

O valor é o PREÇO em centavos ou o PESO em gramas, conforme
`StoreRule.scale_barcode_mode` (a regra das filiais). No modo preço, a quantidade sai do preço/kg.

O código pode ser também o de um VOLUME (caixa "Vol 2/3"): o resultado traz a
variante e o volume, para a conferência saber que leu só uma parte da unidade.
"""
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from starrp.models import ProductBarcode, ProductVariant, ProductVolume, StockLot, StoreRule


@dataclass
class CodeResult:
    variant: ProductVariant
    quantity: Decimal | None = None
    total: Decimal | None = None  # etiqueta de PREÇO: o valor impresso (é ele que o cliente paga)
    volume: ProductVolume | None = None
    lot: StockLot | None = None


def ean_check_digit_ok(code):
    """Confere o dígito verificador GTIN-8/12/13/14 (peso 3 nas posições
    ímpares contadas da direita, sem o verificador)."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    *body, check = (int(c) for c in code)
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _scale_rule(account_id, store):
    """A regra da FILIAL que está lendo; sem filial, a de uma filial ativa que usa etiqueta."""
    if store is not None:
        return store.rule if store.rule and store.rule.scale_barcode_mode else None
    return StoreRule.all_objects.filter(account_id=account_id, deleted_at__isnull=True,
                                         stores__deleted_at__isnull=True).exclude(scale_barcode_mode="").first()


def _scale_label(account_id, code, store=None):
    rule = _scale_rule(account_id, store)
    if rule is None or not ean_check_digit_ok(code) or not code.startswith(rule.scale_barcode_prefix):
        return None
    plu, value = code[1:7].lstrip("0"), Decimal(code[7:12])
    variant = _alive(account_id).filter(scale_code=plu).first()
    if variant is None:
        return None
    if rule.scale_barcode_mode == StoreRule.ScaleBarcode.WEIGHT:
        return CodeResult(variant, (value / 1000).quantize(Decimal("0.001")))
    from starrp.services import pricing

    price = pricing.quote(variant, getattr(store, "pk", None)).unit_price  # o preço que será cobrado (com promoção)
    if not price:
        return CodeResult(variant)
    total = value / 100
    # Para CIMA no grama: peso × preço nunca fica abaixo da etiqueta (a sobra de centavos sai no desconto da linha).
    return CodeResult(variant, (total / price).quantize(Decimal("0.001"), rounding=ROUND_CEILING), total=total)


def _alive(account_id):
    return ProductVariant.all_objects.filter(
        account_id=account_id, deleted_at__isnull=True, product__deleted_at__isnull=True
    ).select_related("product")


def resolve_code(account_id, code, store=None):
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
    scale = _scale_label(account_id, code, store)
    if scale is not None:
        return scale
    variant = _alive(account_id).filter(sku=code).first()
    if variant is not None:
        return CodeResult(variant)
    # Etiqueta interna do lote (entrada de estoque): o leitor acha o produto e o lote.
    lot = StockLot.all_objects.filter(account_id=account_id, code__iexact=code, deleted_at__isnull=True,
                                      variant__deleted_at__isnull=True).select_related("variant__product").first()
    return CodeResult(lot.variant, lot=lot) if lot else None
