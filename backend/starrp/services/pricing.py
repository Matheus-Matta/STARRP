"""Quem decide o preço de uma variante AGORA. É aqui e em nenhum outro lugar.

A promoção é ligada ao PRODUTO (vale para todas as variantes: "camiseta básica
por R$ 29,90" vale para P, M e G); o desconto incide no preço de cada variante.

Ordem da disputa quando mais de uma regra alcança o produto:
  1. a tabela MAIS ANTIGA ganha (o que foi prometido primeiro);
  2. dentro da tabela, a regra mais ao topo (`position`).
A primeira que alcança vence; descontos não se somam.

O desconto incide sobre o preço de PRATELEIRA (promocional do cadastro ou
preço cheio), o que garante que uma promoção nunca aumente um preço.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q

from starrp.models import Promotion, PromotionProduct


@dataclass(frozen=True)
class Offer:
    price: Decimal
    compare_at: Decimal
    promotion: Promotion

    @property
    def discount_amount(self):
        return self.compare_at - self.price


@dataclass(frozen=True)
class PriceQuote:
    list_price: Decimal  # preço de prateleira (o "de")
    unit_price: Decimal  # preço cobrado (o "por")
    promotion: Promotion | None = None


def shelf_price(variant):
    manual = variant.promotional_price
    if manual is not None and manual > 0:
        return Decimal(manual)
    return Decimal(variant.price or 0)


def active_rules(account_id, store_id=None):
    """Regras vigentes já na ordem da disputa. Usa `all_objects` com a conta
    explícita: este código roda também fora de requisição (tarefa, sync)."""
    qs = (
        Promotion.all_objects.filter(
            account_id=account_id,
            deleted_at__isnull=True,
            is_enabled=True,
            table__deleted_at__isnull=True,
            table__is_enabled=True,
        )
        .select_related("table")
        .prefetch_related("categories", "brands")
    )
    if store_id:
        qs = qs.filter(Q(table__store__isnull=True) | Q(table__store_id=store_id))
    rules = [rule for rule in qs if rule.is_active]
    rules.sort(key=lambda r: (r.table.created_at, r.position, r.created_at))
    return rules


def _links(rules, product_ids):
    target = [r.pk for r in rules if r.target == Promotion.Target.PRODUCTS]
    if not target or not product_ids:
        return {}
    links = PromotionProduct.all_objects.filter(
        promotion_id__in=target, product_id__in=product_ids, deleted_at__isnull=True
    )
    return {(link.promotion_id, link.product_id): link for link in links}


def _reaches(rule, variant, link):
    category_id, brand_id = variant.product.category_id, variant.product.brand_id
    if rule.target == Promotion.Target.ALL:
        return True
    if rule.target == Promotion.Target.PRODUCTS:
        return link is not None
    if rule.target == Promotion.Target.CATEGORIES:
        return bool(category_id) and any(c.pk == category_id for c in rule.categories.all())
    if rule.target == Promotion.Target.BRANDS:
        return bool(brand_id) and any(b.pk == brand_id for b in rule.brands.all())
    return False


def _offer(rule, variant, link):
    shelf = shelf_price(variant)
    typed_compare = getattr(link, "compare_at_price", None)
    compare_at = Decimal(typed_compare) if typed_compare is not None else shelf
    price = rule.price_for(shelf, link)
    if price >= compare_at and typed_compare is None:
        return None
    return Offer(price=price, compare_at=compare_at, promotion=rule)


def offers_for(variants, store_id=None, rules=None):
    """Oferta vencedora de cada variante (chave = id da variante). Poucas consultas, para listagens."""
    variants = [v for v in variants if v is not None]
    if not variants:
        return {}
    if rules is None:
        rules = active_rules(variants[0].account_id, store_id)
    links = _links(rules, {v.product_id for v in variants})
    result = {}
    for variant in variants:
        for rule in rules:
            link = links.get((rule.pk, variant.product_id))
            if not _reaches(rule, variant, link):
                continue
            offer = _offer(rule, variant, link)
            if offer is not None:
                result[variant.pk] = offer
                break
    return result


def quote(variant, store_id=None):
    """Preço de uma variante para venda agora."""
    offer = offers_for([variant], store_id).get(variant.pk)
    shelf = shelf_price(variant)
    if offer is None:
        return PriceQuote(list_price=Decimal(variant.price or 0), unit_price=shelf)
    return PriceQuote(list_price=offer.compare_at, unit_price=offer.price, promotion=offer.promotion)
