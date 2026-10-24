"""Campos decimais padronizados. Dinheiro nunca é float."""
from decimal import Decimal

from django.db import models


class MoneyField(models.DecimalField):
    """Valor monetário. Nunca float: Decimal com 2 casas."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("default", Decimal("0.00"))
        super().__init__(*args, **kwargs)


class QuantityField(models.DecimalField):
    """Quantidade física (unidade, kg, litro): 3 casas cobrem grama e mililitro."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 3)
        kwargs.setdefault("default", Decimal("0.000"))
        super().__init__(*args, **kwargs)


class UnitCostField(models.DecimalField):
    """Custo unitário: 4 casas, porque o custo de 1 g sai de um pacote de 5 kg."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 16)
        kwargs.setdefault("decimal_places", 4)
        kwargs.setdefault("default", Decimal("0.0000"))
        super().__init__(*args, **kwargs)


class PercentField(models.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 6)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("default", Decimal("0.00"))
        super().__init__(*args, **kwargs)
