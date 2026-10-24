"""Variantes: a unidade que se vende e se estoca, e a grade que a descreve.

Grade em tabelas (era JSON no produto), como no StarHub:

    Attribute "Cor"   ->  AttributeValue "Azul", "Preto"   (cadastrados UMA vez na conta)
    Attribute "Tamanho" -> AttributeValue "P", "M", "G"
    ProductVariant "Camiseta M / Azul"  =  valores {Tamanho: M, Cor: Azul}

Com tabela, "todas as camisetas azuis" é um filtro, a "Azul" escrita de dois
jeitos não vira duas cores e renomear um valor corrige todas as variantes.
"""
from django.db import models

from starrp.models.base import MoneyField, QuantityField, TenantModel, UnitCostField, alive


class Attribute(TenantModel):
    """Eixo da grade (Cor, Tamanho, Voltagem), usado por qualquer produto da conta."""

    name = models.CharField(max_length=60)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]
        constraints = [models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_attribute")]

    def __str__(self):
        return self.name


class AttributeValue(TenantModel):
    attribute = models.ForeignKey(Attribute, related_name="values", on_delete=models.CASCADE)
    value = models.CharField(max_length=60)
    # "azul", "Azul " e "AZUL" são a mesma cor: a unicidade olha o texto normalizado.
    normalized = models.CharField(max_length=60, editable=False)
    code = models.CharField(max_length=10, blank=True, help_text="Sufixo do SKU (AZ, P, 110V). Vazio = início do valor.")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["attribute__position", "position", "value"]
        constraints = [
            models.UniqueConstraint(
                fields=["attribute", "normalized"], condition=alive(), name="uniq_attribute_value"
            ),
        ]

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

    def save(self, *args, **kwargs):
        self.value = self.value.strip()
        self.normalized = self.value.casefold()
        super().save(*args, **kwargs)


class ProductVariant(TenantModel):
    product = models.ForeignKey("starrp.Product", related_name="variants", on_delete=models.CASCADE)
    name = models.CharField(max_length=120, blank=True, help_text='Nome da combinação ("M / Azul"). Vazio na padrão.')
    sku = models.CharField(max_length=60, help_text="Código interno, único na conta.")
    values = models.ManyToManyField(AttributeValue, through="starrp.VariantValue", related_name="variants", blank=True)
    is_default = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    # Preço cadastrado. O preço COBRADO sai de `services.pricing` (tabelas de desconto vigentes).
    price = MoneyField(help_text="Preço de venda. Por kg quando vendido na balança.")
    promotional_price = MoneyField(null=True, blank=True, default=None, help_text="Promocional fixo, sem data.")
    scale_code = models.CharField(max_length=6, blank=True, help_text="PLU na balança etiquetadora.")
    last_cost = UnitCostField()
    average_cost = UnitCostField(help_text="Custo médio ponderado, recalculado nas entradas.")
    min_stock = QuantityField(null=True, blank=True, default=None)
    max_stock = QuantityField(null=True, blank=True, default=None)

    # Logística da unidade montada. Quem chega em várias caixas tem `volumes`.
    gross_weight = QuantityField(null=True, blank=True, default=None, help_text="Peso bruto em kg.")
    net_weight = QuantityField(null=True, blank=True, default=None, help_text="Peso líquido em kg.")
    height_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    length_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["product__name", "position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "sku"], condition=alive(), name="uniq_variant_sku"),
            models.UniqueConstraint(
                fields=["product"], condition=alive() & models.Q(is_default=True), name="uniq_default_variant"
            ),
        ]
        indexes = [models.Index(fields=["account", "is_active"])]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        """Nome com a variação: "Camiseta Básica - M / Azul"."""
        return f"{self.product.name} - {self.name}" if self.name else self.product.name

    # O que é do produto, lido pela variante (estoque, venda e preço só conhecem a variante).
    unit = property(lambda self: self.product.unit)
    track_stock = property(lambda self: self.product.keeps_stock)
    track_lots = property(lambda self: self.product.track_lots)
    is_kit = property(lambda self: self.product.type == self.product.Type.KIT)
    sold_by_weight = property(lambda self: self.product.sale_method == self.product.SaleMethod.WEIGHT)


class VariantValue(TenantModel):
    """O valor que a variante tem em cada eixo: no máximo um por eixo."""

    variant = models.ForeignKey(ProductVariant, related_name="variant_values", on_delete=models.CASCADE)
    value = models.ForeignKey(AttributeValue, related_name="variant_links", on_delete=models.PROTECT)
    attribute = models.ForeignKey(Attribute, related_name="+", on_delete=models.PROTECT, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["variant", "attribute"], condition=alive(), name="uniq_variant_axis"),
        ]

    def save(self, *args, **kwargs):
        # Cópia do eixo do valor: é ela que deixa o banco barrar "duas cores na mesma variante".
        self.attribute_id = self.value.attribute_id
        super().save(*args, **kwargs)


class ProductBarcode(TenantModel):
    """Código de barras (EAN/GTIN ou etiqueta própria) da variante. Texto, nunca
    número: zeros à esquerda fazem parte do código."""

    variant = models.ForeignKey(ProductVariant, related_name="barcodes", on_delete=models.CASCADE)
    code = models.CharField(max_length=32)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "code"], condition=alive(), name="uniq_barcode")]

    def __str__(self):
        return self.code
