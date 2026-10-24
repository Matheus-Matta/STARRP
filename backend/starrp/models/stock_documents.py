"""Documentos de estoque: o único documento (entrada, saída, transferência,
ajuste, inventário, devolução ao fornecedor) e suas linhas.
"""
from django.db import models

from starrp.models.base import MoneyField, QuantityField, StoreModel, TenantModel, UnitCostField, user_fk
from starrp.models.stock import StockLot, Warehouse

class StockDocument(StoreModel):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada / recebimento"
        EXIT = "exit", "Saída (consumo, perda)"
        TRANSFER = "transfer", "Transferência"
        ADJUSTMENT = "adjustment", "Ajuste"
        INVENTORY = "inventory", "Inventário (contagem)"
        SUPPLIER_RETURN = "supplier_return", "Devolução ao fornecedor"
        RELOCATION = "relocation", "Movimentação entre endereços (WMS)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        POSTED = "posted", "Confirmado"
        CANCELLED = "cancelled", "Cancelado"

    class ExitReason(models.TextChoices):
        CONSUMPTION = "consumption", "Consumo interno"
        LOSS = "loss", "Perda / avaria"
        EXPIRATION = "expiration", "Vencimento"

    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    exit_reason = models.CharField(max_length=12, choices=ExitReason.choices, blank=True, help_text="Só em saída.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    number = models.PositiveIntegerField()
    warehouse = models.ForeignKey(Warehouse, related_name="documents", on_delete=models.PROTECT)
    destination = models.ForeignKey(
        Warehouse, null=True, blank=True, related_name="incoming_documents", on_delete=models.PROTECT
    )
    supplier = models.ForeignKey(
        "starrp.Supplier", null=True, blank=True, related_name="stock_documents", on_delete=models.PROTECT
    )
    inbound_nfe = models.ForeignKey(
        "starrp.InboundNFe", null=True, blank=True, related_name="stock_documents", on_delete=models.PROTECT
    )
    external_number = models.CharField(max_length=60, blank=True, help_text="Número da nota/documento externo.")
    effective_date = models.DateField()
    reason = models.TextField(blank=True)
    # Conferência física (contagem). Entrada de NF-e só é aprovada depois dela.
    checked_at = models.DateTimeField(null=True, blank=True)
    checked_by = user_fk("+")
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = user_fk("+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = user_fk("+")

    class Meta:
        ordering = ["-effective_date", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["store", "number"], name="uniq_stock_document_number")]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.number}"

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT


class StockDocumentItem(TenantModel):
    """Linha do documento. No recebimento/inventário, `expected_quantity` é o
    que a nota/sistema diz e `quantity` o que foi conferido e vai mover."""

    store_lookup = "document__store"

    document = models.ForeignKey(StockDocument, related_name="items", on_delete=models.CASCADE)
    variant = models.ForeignKey("starrp.ProductVariant", related_name="+", on_delete=models.PROTECT)
    expected_quantity = QuantityField(null=True, blank=True, default=None)
    quantity = QuantityField()
    unit_cost = UnitCostField()
    total_cost = MoneyField()
    lot = models.ForeignKey(StockLot, null=True, blank=True, related_name="+", on_delete=models.PROTECT)
    # WMS: endereço de origem (saída/movimentação) ou de guarda (entrada);
    # `destination_bin` é o destino na movimentação entre endereços.
    bin = models.ForeignKey("starrp.StorageBin", null=True, blank=True, related_name="+", on_delete=models.PROTECT)
    destination_bin = models.ForeignKey("starrp.StorageBin", null=True, blank=True, related_name="+",
                                        on_delete=models.PROTECT)
    lot_number = models.CharField(max_length=60, blank=True)
    manufactured_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    serials = models.JSONField(default=list, blank=True)
    nfe_item = models.ForeignKey(
        "starrp.InboundNFeItem", null=True, blank=True, related_name="stock_items", on_delete=models.SET_NULL
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]

    @property
    def difference(self):
        if self.expected_quantity is None:
            return None
        return self.quantity - self.expected_quantity
