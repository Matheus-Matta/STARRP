"""Parceiros: clientes (com grupos e endereços) e fornecedores.

Cliente e fornecedor compartilham a identificação (PF/PJ, documento, IE) e o
formato de endereço da NF-e. São cadastros da CONTA: o cliente da loja A é o
mesmo na loja B, e o crediário dele é um só.
"""
from django.db import models

from starrp.models.base import MoneyField, TenantModel, alive
from starrp.models.company import AddressFields


class PersonType(models.TextChoices):
    INDIVIDUAL = "F", "Pessoa física"
    COMPANY = "J", "Pessoa jurídica"


class PartyFields(models.Model):
    person_type = models.CharField(max_length=1, choices=PersonType.choices, default=PersonType.INDIVIDUAL)
    name = models.CharField(max_length=180, help_text="Nome ou nome fantasia.")
    legal_name = models.CharField(max_length=180, blank=True)
    document = models.CharField(max_length=18, blank=True, db_index=True, help_text="CPF ou CNPJ, só dígitos.")
    state_registration = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class CustomerGroup(TenantModel):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=20, default="#64748b")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_customer_group"),
        ]

    def __str__(self):
        return self.name


class Customer(PartyFields, TenantModel):
    birth_date = models.DateField(null=True, blank=True)
    groups = models.ManyToManyField(CustomerGroup, related_name="customers", blank=True)
    tags = models.ManyToManyField("starrp.Tag", related_name="customers", blank=True)
    credit_limit = MoneyField(help_text="Limite do crediário. 0 = não vende a prazo.")
    metafields = models.JSONField(default=dict, blank=True, help_text="Metacampos {chave: valor}.")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "document"], condition=alive() & ~models.Q(document=""), name="uniq_customer_doc"
            ),
        ]


class CustomerAddress(AddressFields, TenantModel):
    customer = models.ForeignKey(Customer, related_name="addresses", on_delete=models.CASCADE)
    label = models.CharField(max_length=80, default="Principal")
    reference = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "label"]

    def __str__(self):
        return f"{self.customer} - {self.label}"


class Supplier(PartyFields, AddressFields, TenantModel):
    contact_name = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "document"], condition=alive() & ~models.Q(document=""), name="uniq_supplier_doc"
            ),
        ]
