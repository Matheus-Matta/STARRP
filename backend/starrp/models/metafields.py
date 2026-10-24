"""Metacampos (padrão do StarHub): informação extra guardada no próprio registro, em
`metafields` ({chave: valor}), no produto, no cliente e no pedido.

Chave livre continua valendo (integração, anotação); a DEFINIÇÃO dá nome, tipo e
unidade a uma chave — é o que vira campo no formulário e linha na ficha técnica
("Tempo de montagem: 2 h", "Garantia: 12 meses"). Validação em `services/metafields.py`.
"""
from django.db import models

from starrp.models.base import TenantModel, alive


class MetafieldDefinition(TenantModel):
    class Owner(models.TextChoices):
        PRODUCT = "product", "Produto"
        CUSTOMER = "customer", "Cliente"
        SALE = "sale", "Pedido"

    class Type(models.TextChoices):
        TEXT = "text", "Texto"
        NUMBER = "number", "Número"
        BOOLEAN = "boolean", "Sim/Não"
        SELECT = "select", "Lista de opções"
        DATE = "date", "Data"

    owner = models.CharField(max_length=10, choices=Owner.choices, default=Owner.PRODUCT)
    key = models.SlugField(max_length=60, help_text='Chave em `metafields` (ex.: "tempo_montagem").')
    name = models.CharField(max_length=80, help_text='Rótulo na tela (ex.: "Tempo de montagem").')
    type = models.CharField(max_length=10, choices=Type.choices, default=Type.TEXT)
    unit = models.CharField(max_length=20, blank=True, help_text='Depois do valor: "h", "meses", "kg".')
    options = models.JSONField(default=list, blank=True, help_text="Opções da lista (tipo Lista de opções).")
    help_text = models.CharField(max_length=160, blank=True)
    show_in_specs = models.BooleanField(default=True, help_text="Aparece na ficha técnica (PDV e impressão).")
    required = models.BooleanField(default=False)
    categories = models.ManyToManyField(
        "starrp.Category", related_name="metafield_definitions", blank=True,
        help_text="Só para produtos destas categorias (e das de dentro). Vazio = todos.")
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["owner", "position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "owner", "key"], condition=alive(), name="uniq_metafield_key"),
        ]

    def __str__(self):
        return self.name
