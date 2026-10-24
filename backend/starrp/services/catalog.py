"""Regras do cadastro de produto: variantes, grade e volumes.

Regras (as mesmas do StarHub):
- todo produto tem ao menos uma variante, e exatamente uma é a padrão;
- só produto "com variação" tem mais de uma; cada variante dele tem um valor
  por eixo da grade, e duas variantes não repetem a mesma combinação;
- excluir variante com saldo em estoque é proibido (zere antes, por ajuste).

Grade (eixos → variantes) fica em `variant_grid.py`. Exemplo: {"Tamanho": ["P", "M"], "Cor": ["Azul"]} gera
"P / Azul" (SKU CAM01-P-AZU) e "M / Azul" (SKU CAM01-M-AZU).
"""
import re

from django.db import models, transaction
from django.db.models import Sum

from starrp.core.errors import BusinessError
from starrp.models import (
    AttributeValue, Product, ProductBarcode, ProductVariant, ProductVolume, StockBalance, VariantValue,
)

VARIANT_FIELDS = (
    "name", "sku", "price", "promotional_price", "scale_code", "min_stock", "max_stock", "gross_weight",
    "net_weight", "height_cm", "width_cm", "length_cm", "is_active", "position",
)
VOLUME_FIELDS = ("description", "barcode", "gross_weight", "height_cm", "width_cm", "length_cm")


def _code(value):
    raw = value.code or value.value
    return re.sub(r"[^A-Z0-9]", "", raw.upper())[:3] or "X"


def variant_name(values):
    return " / ".join(v.value for v in sorted(values, key=lambda v: (v.attribute.position, v.attribute.name)))


def free_sku(account_id, wanted, exclude_pk=None):
    """`wanted` se estiver livre na conta; senão `wanted-2`, `wanted-3`...
    Ex.: dois produtos "Item lote" geram ITEMLOTE-1 e ITEMLOTE-1-2 (nunca erro de duplicado)."""
    taken = ProductVariant.all_objects.filter(account_id=account_id, deleted_at__isnull=True)
    if exclude_pk:
        taken = taken.exclude(pk=exclude_pk)
    candidate, suffix = wanted[:60], 2
    while taken.filter(sku=candidate).exists():
        candidate = f"{wanted[:56]}-{suffix}"
        suffix += 1
    return candidate


def free_slug(model, account_id, text, exclude_pk=None):
    """Slug livre na conta: "camiseta-basica", senão "camiseta-basica-2"... (como o SKU)."""
    from django.utils.text import slugify

    wanted = (slugify(text) or "item")[:170]
    taken = model.all_objects.filter(account_id=account_id, deleted_at__isnull=True)
    if exclude_pk:
        taken = taken.exclude(pk=exclude_pk)
    candidate, suffix = wanted, 2
    while taken.filter(slug=candidate).exists():
        candidate, suffix = f"{wanted}-{suffix}", suffix + 1
    return candidate


def _base_sku(product):
    default = product.variants.filter(deleted_at__isnull=True, is_default=True).first()
    return product.reference or (default.sku if default else "") or re.sub(r"\W", "", product.name.upper())[:8]


@transaction.atomic
def create_simple(account_id, user, *, name, sku, price, barcodes=(), **product_fields):
    """Produto simples + a variante padrão, num passo. Devolve a VARIANTE."""
    product = Product.all_objects.create(account_id=account_id, name=name, created_by=user, **product_fields)
    variant = ProductVariant.all_objects.create(
        account_id=account_id, product=product, sku=sku, price=price, is_default=True, created_by=user
    )
    for index, code in enumerate(barcodes):
        ProductBarcode.all_objects.create(account_id=account_id, variant=variant, code=code, is_primary=index == 0)
    return variant


def _stock_of(variant):
    return StockBalance.all_objects.filter(variant=variant).aggregate(t=Sum("quantity"))["t"] or 0


def _remove(variant):
    if _stock_of(variant):
        raise BusinessError(f"{variant.display_name} tem saldo em estoque: zere por ajuste antes de excluir.",
                            code="variant_has_stock")
    variant.delete()


def _set_values(variant, value_ids):
    values = list(AttributeValue.all_objects.filter(
        pk__in=value_ids, account_id=variant.account_id, deleted_at__isnull=True
    ).select_related("attribute"))
    if len(values) != len(set(value_ids)):
        raise BusinessError("Valor de grade inexistente.", code="invalid_attribute_value")
    axes = [v.attribute_id for v in values]
    if len(axes) != len(set(axes)):
        raise BusinessError(f"{variant.sku}: um valor só por eixo (ex.: uma cor, um tamanho).")
    # Exclusão de verdade (não lógica): a tabela de ligação alimenta o M2M `values`.
    models.QuerySet.delete(VariantValue.all_objects.filter(variant=variant).exclude(value__in=values))
    current = set(variant.variant_values.filter(deleted_at__isnull=True).values_list("value_id", flat=True))
    for value in values:
        if value.pk not in current:
            VariantValue.all_objects.create(account_id=variant.account_id, variant=variant, value=value)
    return values


def _set_barcodes(variant, rows):
    keep = {row["code"] for row in rows}
    variant.barcodes.exclude(code__in=keep).delete()
    for row in rows:
        ProductBarcode.all_objects.update_or_create(
            variant=variant, code=row["code"], deleted_at=None,
            defaults={"account_id": variant.account_id, "is_primary": row.get("is_primary", False)},
        )


def _set_volumes(variant, rows):
    """Caixas numeradas na ordem enviada (1, 2, 3...)."""
    variant.volumes.filter(number__gt=len(rows)).delete()
    for number, row in enumerate(rows, start=1):
        ProductVolume.all_objects.update_or_create(
            variant=variant, number=number, deleted_at=None,
            defaults={"account_id": variant.account_id, **{f: row.get(f) for f in VOLUME_FIELDS if f in row}},
        )


@transaction.atomic
def save_variants(product, rows, user):
    """Grava a lista COMPLETA de variantes do produto (o que não veio é excluído).

    Cada linha: campos da variante + `id` (para alterar), `values` (ids de
    AttributeValue), `barcodes` e `volumes` (listas que substituem as anteriores).
    """
    if not rows:
        raise BusinessError("O produto precisa de ao menos uma variante.", code="variant_required")
    if product.type != Product.Type.VARIABLE and len(rows) > 1:
        raise BusinessError(f"Produto do tipo {product.get_type_display()} tem uma variante só. "
                            "Para várias, mude o tipo para Com variação.", code="single_variant_type")
    existing = {str(v.pk): v for v in product.variants.filter(deleted_at__isnull=True)}
    sent = {str(row["id"]) for row in rows if row.get("id")}
    for pk, variant in existing.items():
        if pk not in sent:
            _remove(variant)
    default = next((i for i, row in enumerate(rows) if row.get("is_default")), 0)
    for index, row in enumerate(rows):
        row["is_default"] = index == default
    product.variants.filter(deleted_at__isnull=True).update(is_default=False)
    combos, saved = set(), []
    for position, row in enumerate(rows):
        variant = existing.get(str(row.get("id"))) or ProductVariant(
            account_id=product.account_id, product=product, created_by=user
        )
        for field in VARIANT_FIELDS:
            if field in row:
                setattr(variant, field, row[field])
        variant.position, variant.is_default, variant.updated_by = position, bool(row.get("is_default")), user
        if not (variant.sku or "").strip():
            # SKU digitado que repete continua dando erro (é engano); o gerado nunca repete.
            variant.sku = free_sku(product.account_id, f"{_base_sku(product)}-{position + 1}", variant.pk)
        variant.save()
        if "values" in row:
            values = _set_values(variant, row["values"])
            key = frozenset(v.pk for v in values)
            # Sem valores (variante ainda sem grade) passa, como na criação; repetida não.
            if product.type == Product.Type.VARIABLE and key and key in combos:
                raise BusinessError(f"{variant.sku}: cada variante precisa de uma combinação própria da grade.",
                                    code="duplicate_combination")
            combos.add(key)
            if not variant.name and values:
                variant.name = variant_name(values)
                variant.save(update_fields=["name", "updated_at"])
        if "barcodes" in row:
            _set_barcodes(variant, row["barcodes"])
        if "volumes" in row:
            _set_volumes(variant, row["volumes"])
        saved.append(variant)
    return saved
