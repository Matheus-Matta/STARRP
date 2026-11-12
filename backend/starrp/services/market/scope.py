"""As regras: quais produtos a precificação e o Analítico de SEO pegam (botão "Regras" de cada um, guardadas à parte).

Nada marcado = todos. Com regra: (categorias E marcas) OU os produtos escolhidos; depois tiram-se os excluídos
e valem a faixa de preço, "só com estoque" e "só com código de barras". A categoria leva as subcategorias.
O botão "Precificar" do produto ignora as regras: quem clicou escolheu aquele produto.
"""
from django.db.models import Exists, OuterRef, Q

from starrp.models import Category, Module, ProductBarcode, StockBalance

EMPTY = {"categories": [], "brands": [], "products": [], "exclude_products": [], "min_price": None, "max_price": None,
         "only_in_stock": False, "only_with_barcode": False}


def of(account, field="price_scope"):
    return {**EMPTY, **(getattr(account, field) or {})}


def _with_children(account, ids):
    found, level = set(), set(ids)
    while level:
        found |= level
        children = Category.all_objects.filter(account=account, parent__in=level, deleted_at__isnull=True)
        level = set(children.values_list("pk", flat=True)) - found
    return found


def apply(rows, account, field="price_scope"):
    """`rows`: variantes desta conta. Devolve só as que entram nas regras."""
    scope = of(account, field)
    narrow = {}
    if scope["categories"]:
        narrow["product__category__in"] = _with_children(account, scope["categories"])
    if scope["brands"]:
        narrow["product__brand__in"] = scope["brands"]
    chosen = Q(**narrow) if narrow else Q()
    if scope["products"]:
        chosen |= Q(product__in=scope["products"])
    if chosen:
        rows = rows.filter(chosen)
    if scope["exclude_products"]:
        rows = rows.exclude(product__in=scope["exclude_products"])
    if scope["min_price"] is not None:
        rows = rows.filter(price__gte=scope["min_price"])
    if scope["max_price"] is not None:
        rows = rows.filter(price__lte=scope["max_price"])
    if scope["only_in_stock"] and account.has_module(Module.STOCK):
        rows = rows.filter(Exists(StockBalance.all_objects.filter(
            variant=OuterRef("pk"), quantity__gt=0, deleted_at__isnull=True)))
    if scope["only_with_barcode"]:
        rows = rows.filter(Exists(ProductBarcode.all_objects.filter(variant=OuterRef("pk"), deleted_at__isnull=True)))
    return rows
