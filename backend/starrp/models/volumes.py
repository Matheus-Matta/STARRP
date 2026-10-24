"""Volumes: as caixas em que UMA unidade da variante é guardada e entregue.

Exemplo: o guarda-roupa "Casal 6 portas" vem em 3 volumes — Vol 1/3 (laterais),
Vol 2/3 (portas), Vol 3/3 (ferragens). O saldo continua em UNIDADES (1 guarda-
roupa); os volumes servem para:

- etiquetar cada caixa com o código dela ("Vol 2/3") e achá-la no depósito;
- conferir o recebimento/separação: a unidade só está completa com as 3 caixas;
- calcular frete: peso e cubagem (m³) somam as caixas, não o móvel montado.

Embalagem de compra ("CX com 12") NÃO é volume: é a conversão do fornecedor
(`SupplierProduct.conversion_factor`).
"""
from decimal import Decimal

from django.db import models

from starrp.models.base import QuantityField, TenantModel, alive


class ProductVolume(TenantModel):
    variant = models.ForeignKey("starrp.ProductVariant", related_name="volumes", on_delete=models.CASCADE)
    number = models.PositiveSmallIntegerField(help_text="Ordem da caixa: 1, 2, 3...")
    description = models.CharField(max_length=120, blank=True, help_text='O que vai na caixa ("Portas").')
    barcode = models.CharField(max_length=32, blank=True, help_text="Código da etiqueta desta caixa.")
    gross_weight = QuantityField(null=True, blank=True, default=None, help_text="Peso bruto em kg.")
    height_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    length_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)

    class Meta:
        ordering = ["variant", "number"]
        constraints = [
            models.UniqueConstraint(fields=["variant", "number"], condition=alive(), name="uniq_volume_number"),
            models.UniqueConstraint(
                fields=["account", "barcode"], condition=alive() & ~models.Q(barcode=""), name="uniq_volume_barcode"
            ),
        ]

    def __str__(self):
        return f"{self.variant} - Vol {self.number}"

    @property
    def cubic_meters(self):
        """Cubagem da caixa em m³ (cm × cm × cm / 1.000.000). Sem medida = 0."""
        if None in (self.height_cm, self.width_cm, self.length_cm):
            return Decimal("0")
        return (self.height_cm * self.width_cm * self.length_cm / Decimal(1_000_000)).quantize(Decimal("0.000001"))
