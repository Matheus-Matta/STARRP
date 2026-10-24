"""Etiquetas livres ("tags") de produto e cliente, como no StarHub.

Servem para agrupar sem criar cadastro: produto "lançamento", "volta às aulas";
cliente "atacado", "vip". Uma tabela por conta, separada por assunto (`scope`):
a tag "vip" de cliente não aparece nas sugestões de produto.
"""
from django.db import models

from starrp.models.base import TenantModel, alive


class Tag(TenantModel):
    class Scope(models.TextChoices):
        PRODUCT = "product", "Produto"
        CUSTOMER = "customer", "Cliente"

    scope = models.CharField(max_length=10, choices=Scope.choices)
    name = models.CharField(max_length=40)
    # "Vip", "vip " e "VIP" são a mesma tag.
    normalized = models.CharField(max_length=40, editable=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "scope", "normalized"], condition=alive(), name="uniq_tag"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split())
        self.normalized = self.name.casefold()
        super().save(*args, **kwargs)
