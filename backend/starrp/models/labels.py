"""Modelo de etiqueta: produto/gôndola, lote, endereço ou volume, impressa pelo navegador em mm."""
from django.db import models

from starrp.models.base import TenantModel, alive


class LabelTemplate(TenantModel):
    """Etiqueta de gôndola/produto/lote, impressa pelo navegador em mm."""

    class Subject(models.TextChoices):
        PRODUCT = "product", "Produto / gôndola"
        LOT = "lot", "Lote (validade)"
        BIN = "bin", "Endereço de armazenagem"
        VOLUME = "volume", "Volume (caixa do produto)"

    class Code(models.TextChoices):
        EAN13 = "ean13", "EAN-13"
        CODE128 = "code128", "Code 128"
        QR = "qr", "QR Code"

    name = models.CharField(max_length=120)
    subject = models.CharField(max_length=8, choices=Subject.choices, default=Subject.PRODUCT)
    width_mm = models.DecimalField(max_digits=6, decimal_places=1, default=60)
    height_mm = models.DecimalField(max_digits=6, decimal_places=1, default=40)
    margin_mm = models.DecimalField(max_digits=5, decimal_places=1, default=2)
    columns = models.PositiveSmallIntegerField(default=1)
    code_type = models.CharField(max_length=8, choices=Code.choices, default=Code.EAN13)
    font_size_pt = models.DecimalField(max_digits=4, decimal_places=1, default=8)
    # Lista de campos exibidos (no lugar de sete booleanos show_*).
    fields = models.JSONField(default=list, blank=True, help_text='Ex.: ["name", "price", "barcode"].')
    custom_text = models.CharField(max_length=200, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False, help_text="Modelo pré-pronto do sistema: ajusta, mas não exclui.")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_label")]

    def __str__(self):
        return self.name
