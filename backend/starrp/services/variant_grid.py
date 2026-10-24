"""A grade do produto: eixos e valores → as variantes.

A grade enviada é A grade do produto — o que saiu dela, sai das variantes:

    antes: Tamanho [P, M] × Cor [Azul, Preto]   (4 variantes)
    envia: Tamanho [P, M]                        (tirou o eixo Cor)
    depois: P e M — "P / Azul" vira "P" (mantém SKU, códigos e estoque) e
            "P / Preto" é excluída (ficou igual à outra).

- eixo novo: as variantes que já existem ganham o 1º valor dele (não perdem o
  histórico) e as combinações que faltam são criadas;
- eixo removido: o valor dele sai de cada variante; as que ficarem iguais viram
  uma só (fica a padrão, ou a primeira);
- valor removido (Tamanho sem o G): as variantes com G são excluídas.
Variante com saldo em estoque não é excluída: o salvar para e diz qual zerar.

Eixo e valor novos são cadastrados; "azul " e "Azul" são o mesmo valor.
"""
import itertools

from django.db import models, transaction

from starrp.core.errors import BusinessError
from starrp.models import Attribute, AttributeValue, Product, ProductVariant, VariantValue
from starrp.services.catalog import _base_sku, _code, _remove, free_sku, variant_name


def _value(account_id, attribute, text, user):
    found = AttributeValue.all_objects.filter(
        attribute=attribute, normalized=text.strip().casefold(), deleted_at__isnull=True
    ).first()
    return found or AttributeValue.all_objects.create(
        account_id=account_id, attribute=attribute, value=text, created_by=user
    )


def _axes(product, grid, user):
    """[(eixo, [valores])] na ordem enviada, cadastrando o que não existe."""
    axes = []
    for name, texts in grid.items():
        attribute = Attribute.all_objects.filter(
            account_id=product.account_id, name__iexact=name.strip(), deleted_at__isnull=True
        ).first() or Attribute.all_objects.create(account_id=product.account_id, name=name.strip(), created_by=user)
        values = [_value(product.account_id, attribute, text, user) for text in texts]
        axes.append((attribute, list({v.pk: v for v in values}.values())))
    return axes


@transaction.atomic
def generate_variants(product, grid, user, *, price=None):
    """Aplica a grade (`{"Cor": ["Azul", "Preto"]}`) às variantes. Devolve as criadas."""
    if product.type not in (Product.Type.SIMPLE, Product.Type.VARIABLE):
        raise BusinessError("Só produto simples ou com variação tem grade.")
    axes = _axes(product, grid, user)
    allowed = {attribute.pk: {v.pk for v in values} for attribute, values in axes}
    product.type = Product.Type.VARIABLE
    product.save(update_fields=["type", "updated_at"])

    variants = list(product.variants.filter(deleted_at__isnull=True).order_by("-is_default", "position", "created_at")
                    .prefetch_related("variant_values__value__attribute"))
    default_price = price if price is not None else (variants[0].price if variants else 0)
    survivors = {}
    for variant in variants:
        current = {vv.value.attribute_id: vv for vv in variant.variant_values.all() if vv.deleted_at is None}
        if any(attr in allowed and vv.value_id not in allowed[attr] for attr, vv in current.items()):
            _remove(variant)  # tinha um valor que saiu da grade (o tamanho G)
            continue
        dropped = [vv.pk for attr, vv in current.items() if attr not in allowed]
        if dropped:  # eixo que saiu da grade: o valor dele sai da variante
            models.QuerySet.delete(VariantValue.all_objects.filter(pk__in=dropped))
        values = {attr: vv.value for attr, vv in current.items() if attr in allowed}
        for attribute, options in axes:
            if attribute.pk not in values:  # eixo novo: a variante existente fica com o 1º valor
                values[attribute.pk] = options[0]
                VariantValue.all_objects.create(account_id=product.account_id, variant=variant, value=options[0])
        key = frozenset(v.pk for v in values.values())
        if key in survivors:
            _remove(variant)  # ficou igual a outra depois de tirar o eixo
            continue
        survivors[key] = variant
        name = variant_name(values.values())
        if variant.name != name:
            variant.name = name
            variant.save(update_fields=["name", "updated_at"])

    base, created = _base_sku(product), []
    for combo in itertools.product(*(options for _, options in axes)):
        key = frozenset(v.pk for v in combo)
        if key in survivors:
            continue
        variant = ProductVariant.all_objects.create(
            account_id=product.account_id, product=product, price=default_price, created_by=user,
            name=variant_name(combo), position=len(survivors) + len(created),
            sku=free_sku(product.account_id, f"{base}-{'-'.join(_code(v) for v in combo)}"),
        )
        for value in combo:
            VariantValue.all_objects.create(account_id=product.account_id, variant=variant, value=value)
        survivors[key] = variant
        created.append(variant)
    alive = product.variants.filter(deleted_at__isnull=True)
    if not alive.filter(is_default=True).exists() and alive.exists():
        alive.filter(pk=alive.order_by("position", "created_at").first().pk).update(is_default=True)
    return created
