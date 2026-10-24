"""Troca e devolução, e o vale-troca (crédito do cliente).

A devolução não muda o estado da venda original: ela é um documento próprio,
que aponta os itens devolvidos. Assim uma venda pode ter várias devoluções
parciais e o histórico continua legível.
"""
from django.db import models

from starrp.models.base import MoneyField, QuantityField, StoreModel, TenantModel, user_fk


class SaleReturn(StoreModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        COMPLETED = "completed", "Concluída"
        CANCELLED = "cancelled", "Cancelada"

    class Refund(models.TextChoices):
        STORE_CREDIT = "store_credit", "Vale-troca (crédito do cliente)"
        CASH = "cash", "Dinheiro do caixa"
        ORIGINAL_PAYMENT = "original_payment", "Estorno na forma original"
        EXCHANGE = "exchange", "Troca na mesma hora (abate na nova venda)"

    number = models.PositiveIntegerField()
    sale = models.ForeignKey("starrp.Sale", related_name="returns", on_delete=models.PROTECT)
    customer = models.ForeignKey(
        "starrp.Customer", null=True, blank=True, related_name="returns", on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    refund_method = models.CharField(max_length=20, choices=Refund.choices, default=Refund.STORE_CREDIT)
    cash_session = models.ForeignKey(
        "starrp.CashSession", null=True, blank=True, related_name="returns", on_delete=models.PROTECT
    )
    # Venda nova que recebeu esta troca (Refund.EXCHANGE).
    exchange_sale = models.ForeignKey(
        "starrp.Sale", null=True, blank=True, related_name="exchanges_received", on_delete=models.SET_NULL
    )
    reason = models.TextField()
    total = MoneyField()
    processed_by = user_fk("+")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["store", "number"], name="uniq_return_number")]

    def __str__(self):
        return f"Devolução {self.number} (venda {self.sale_id})"


class SaleReturnItem(TenantModel):
    store_lookup = "sale_return__store"

    sale_return = models.ForeignKey(SaleReturn, related_name="items", on_delete=models.CASCADE)
    sale_item = models.ForeignKey("starrp.SaleItem", related_name="return_items", on_delete=models.PROTECT)
    quantity = QuantityField()
    unit_price = MoneyField(help_text="Preço efetivamente pago por unidade (com descontos rateados).")
    total = MoneyField()
    restock = models.BooleanField(default=True, help_text="Volta para o estoque vendável.")


class CustomerCredit(TenantModel):
    """Extrato do vale-troca: o saldo é a soma das linhas, nunca um campo."""

    class Kind(models.TextChoices):
        RETURN = "return", "Crédito por devolução"
        USAGE = "usage", "Uso em venda"
        ADJUSTMENT = "adjustment", "Ajuste manual"
        EXPIRATION = "expiration", "Expiração"

    customer = models.ForeignKey("starrp.Customer", related_name="credits", on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = MoneyField(help_text="Positivo = crédito; negativo = uso.")
    sale_return = models.ForeignKey(SaleReturn, null=True, blank=True, related_name="credits", on_delete=models.PROTECT)
    payment = models.ForeignKey("starrp.Payment", null=True, blank=True, related_name="credits", on_delete=models.PROTECT)
    expires_at = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "created_at"])]
