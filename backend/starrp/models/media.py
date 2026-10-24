"""Acervo de imagens da conta e o vínculo ordenado imagem ↔ produto (ou variante)."""

from django.db import models

from starrp.models.base import TenantModel, alive

class Image(TenantModel):
    file = models.ImageField(upload_to="images/%Y/%m/", max_length=400)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, db_index=True)
    alt_text = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.original_name


class ProductImage(TenantModel):
    product = models.ForeignKey("starrp.Product", related_name="images", on_delete=models.CASCADE)
    # Vazio = foto do produto; preenchido = foto daquela variante (a camiseta azul).
    variant = models.ForeignKey("starrp.ProductVariant", null=True, blank=True, related_name="images",
                                on_delete=models.CASCADE)
    image = models.ForeignKey(Image, related_name="product_links", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["product", "image"], condition=alive(), name="uniq_product_image"),
        ]
