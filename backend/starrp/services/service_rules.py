"""Quais serviços valem para um produto e por qual preço (ServiceRule) — padrão do StarHub.

    products_of(rule)          -> produtos que a regra pega
    services_for(product)      -> [(variante do serviço, preço, regra)] para o produto
    price_for(service, product)-> preço do serviço naquele produto (None = não vale)

Por categoria: as categorias (e as de dentro, até 3 níveis) E a faixa de preço, pelo
preço da variante padrão. Por produto: só os escolhidos. Para cada serviço vale a
primeira regra ativa que casa, pela ordem; o preço dela ou o padrão do serviço.
"""
from django.db.models import Q

from starrp.models import Category, Product, ServiceRule


def _with_children(ids):
    ids, frontier = set(ids), set(ids)
    for _ in range(3):
        frontier = set(Category.all_objects.filter(parent__in=frontier, deleted_at__isnull=True)
                       .values_list("pk", flat=True)) - ids
        if not frontier:
            break
        ids |= frontier
    return ids


def _filter(rule):
    if rule.kind == ServiceRule.Kind.PRODUCT:
        chosen = list(rule.products.values_list("pk", flat=True))
        return Q(pk__in=chosen) if chosen else None
    query, used = Q(), False
    categories = list(rule.categories.values_list("pk", flat=True))
    if categories:
        query &= Q(category__in=_with_children(categories))
        used = True
    if rule.price_min is not None or rule.price_max is not None:
        query &= Q(variants__is_default=True, variants__deleted_at__isnull=True)
        if rule.price_min is not None:
            query &= Q(variants__price__gte=rule.price_min)
        if rule.price_max is not None:
            query &= Q(variants__price__lte=rule.price_max)
        used = True
    return query if used else None  # regra sem critério não vale para o catálogo inteiro


def products_of(rule):
    query = _filter(rule)
    if query is None:
        return Product.all_objects.none()
    return (Product.all_objects.filter(account_id=rule.account_id, deleted_at__isnull=True)
            .exclude(type=Product.Type.SERVICE).filter(query).distinct())


def _active_rules(account_id):
    return (ServiceRule.all_objects
            .filter(account_id=account_id, is_active=True, deleted_at__isnull=True,
                    service__is_active=True, service__deleted_at__isnull=True)
            .select_related("service").prefetch_related("service__variants")
            .order_by("service__name", "position", "created_at"))


def _matches(rule, product):
    return products_of(rule).filter(pk=product.pk).exists()


def services_for(product):
    """[(variante padrão do serviço, preço, regra)] na ordem do nome; cada serviço uma vez."""
    if product.type == Product.Type.SERVICE:
        return []
    out, seen = [], set()
    for rule in _active_rules(product.account_id):
        if rule.service_id in seen or not _matches(rule, product):
            continue
        variant = rule.service.default_variant
        if variant is None or not variant.is_active:
            continue
        seen.add(rule.service_id)
        out.append((variant, rule.price if rule.price is not None else variant.price, rule))
    return out


def price_for(service_variant, product):
    """Preço do serviço para o produto, ou None se nenhuma regra ativa o oferece."""
    for variant, price, _rule in services_for(product):
        if variant.pk == service_variant.pk:
            return price
    return None
