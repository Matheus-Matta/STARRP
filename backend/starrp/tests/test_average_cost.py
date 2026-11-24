"""Custo médio: entradas em sequência e estornos."""
from decimal import Decimal

from starrp.models import ProductVariant, StockMovement
from starrp.services import checkout, stock
from starrp.tests.test_security_round2 import _open_sale, _paid

PURCHASE = StockMovement.Kind.PURCHASE


def _fresh(variant):
    return ProductVariant.all_objects.get(pk=variant.pk)


def _buy(ctx, variant, quantity, cost):
    return stock.move(variant, stock.default_warehouse(ctx.store), Decimal(quantity), PURCHASE,
                      unit_cost=Decimal(cost))[0]


def test_duas_linhas_do_mesmo_produto_usam_o_custo_atual(ctx):
    """Cada linha do documento traz a SUA cópia da variante: a segunda não pode partir do custo antigo."""
    variant = ctx.product()
    first, second = _fresh(variant), _fresh(variant)
    _buy(ctx, first, 10, 10)
    _buy(ctx, second, 10, 20)
    assert _fresh(variant).average_cost == Decimal("15")


def test_cancelar_entrada_devolve_o_custo_medio_e_o_ultimo_custo(ctx):
    variant = ctx.product()
    _buy(ctx, _fresh(variant), 10, 10)
    wrong = _buy(ctx, _fresh(variant), 10, 100)
    assert _fresh(variant).average_cost == Decimal("55")

    stock.reverse(StockMovement.all_objects.get(pk=wrong.pk))

    assert _fresh(variant).average_cost == Decimal("10") and _fresh(variant).last_cost == Decimal("10")


def test_estorno_repetido_nao_mexe_de_novo(ctx):
    variant = ctx.product()
    _buy(ctx, _fresh(variant), 10, 10)
    wrong = _buy(ctx, _fresh(variant), 10, 100)
    first = stock.reverse(StockMovement.all_objects.get(pk=wrong.pk))
    again = stock.reverse(StockMovement.all_objects.get(pk=wrong.pk))
    assert first.pk == again.pk
    assert _fresh(variant).average_cost == Decimal("10") and stock.available(variant) == Decimal("10")


def test_entrada_ja_vendida_nao_deixa_custo_negativo(ctx):
    variant = ctx.product()
    entry = _buy(ctx, _fresh(variant), 10, 10)
    stock.move(_fresh(variant), stock.default_warehouse(ctx.store), Decimal("-8"), StockMovement.Kind.SALE)
    _buy(ctx, _fresh(variant), 5, 2)
    stock.reverse(StockMovement.all_objects.get(pk=entry.pk))
    assert _fresh(variant).average_cost > 0


def test_venda_cancelada_volta_pelo_custo_com_que_saiu(ctx):
    variant = ctx.product(price="50.00")
    _buy(ctx, _fresh(variant), 10, 10)
    sale = _paid(ctx, _open_sale(ctx, (_fresh(variant), "10")))
    _buy(ctx, _fresh(variant), 10, 20)
    assert _fresh(variant).average_cost == Decimal("20")

    checkout.cancel(sale, ctx.admin, "cliente desistiu")

    assert stock.available(variant) == Decimal("20")
    assert _fresh(variant).average_cost == Decimal("15")
