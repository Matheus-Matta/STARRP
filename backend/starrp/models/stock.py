"""Estoque: depósitos, saldo, lotes, documentos e o razão de movimentos.

O StarChef tinha dois sistemas paralelos (`StockLot` × `InventoryLot`,
`StockEntry`/`StockExit` × `GoodsReceipt`) e um movimento com FK para
`ingredient` E `product`, mais seis tipos "legado". Aqui:

- `StockDocument` é o único documento (entrada, saída, transferência, ajuste,
  inventário, devolução ao fornecedor), com rascunho → confirmado → cancelado;
- `StockLot` é o único lote; `StockBalance` é o saldo materializado;
- `StockMovement` é o razão imutável: fonte de verdade do saldo, quantidade
  com sinal, `source_key` única para a mesma baixa nunca acontecer duas vezes.
"""
from django.db import models
from django.db.models import Q

from starrp.models.base import MoneyField, QuantityField, StoreModel, TenantModel, UnitCostField, alive, user_fk


class StockSettings(TenantModel):
    """Política de estoque da conta (uma por conta)."""

    class Picking(models.TextChoices):
        FIFO = "fifo", "FIFO - primeiro a entrar"
        FEFO = "fefo", "FEFO - primeiro a vencer"

    picking_strategy = models.CharField(max_length=4, choices=Picking.choices, default=Picking.FEFO)
    expiry_warning_days = models.PositiveSmallIntegerField(default=7)
    block_expired = models.BooleanField(default=True)
    allow_negative_stock = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account"], condition=alive(), name="uniq_stock_settings")]


class Warehouse(StoreModel):
    class Kind(models.TextChoices):
        SALES_FLOOR = "sales_floor", "Loja / área de venda"
        STORAGE = "storage", "Depósito"
        DAMAGED = "damaged", "Avariados"
        MAINTENANCE = "maintenance", "Manutenção"
        DISPOSAL = "disposal", "Descarte"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.STORAGE)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.SET_NULL)
    # O PDV baixa a venda deste depósito.
    is_default = models.BooleanField(default=False)
    # WMS: estoque controlado por endereço (rua/prateleira/nível).
    uses_bins = models.BooleanField(default=False, help_text="Controla o estoque por endereço (WMS).")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["store", "name"], condition=alive(), name="uniq_warehouse_name"),
            models.UniqueConstraint(
                fields=["store"], condition=alive(is_default=True), name="uniq_default_warehouse"
            ),
        ]

    def __str__(self):
        return self.name


class StockBalance(TenantModel):
    """Saldo materializado por produto e depósito, atualizado na MESMA
    transação do movimento. Consultar o razão inteiro a cada venda não escala."""

    store_lookup = "warehouse__store"

    variant = models.ForeignKey("starrp.ProductVariant", related_name="balances", on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, related_name="balances", on_delete=models.CASCADE)
    quantity = QuantityField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["variant", "warehouse"], name="uniq_stock_balance")]


class StockLot(TenantModel):
    store_lookup = "warehouse__store"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponível"
        DEPLETED = "depleted", "Esgotado"
        BLOCKED = "blocked", "Bloqueado"
        EXPIRED = "expired", "Vencido"
        DISCARDED = "discarded", "Descartado"

    variant = models.ForeignKey("starrp.ProductVariant", related_name="lots", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, related_name="lots", on_delete=models.PROTECT)
    # Código da etiqueta interna: imutável e nunca reaproveitado.
    code = models.CharField(max_length=40)
    lot_number = models.CharField(max_length=60, blank=True, help_text="Lote do fabricante.")
    manufactured_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True, db_index=True)
    initial_quantity = QuantityField()
    quantity = QuantityField()
    unit_cost = UnitCostField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE, db_index=True)

    class Meta:
        ordering = ["expires_at", "created_at"]
        constraints = [models.UniqueConstraint(fields=["account", "code"], condition=alive(), name="uniq_lot_code")]
        indexes = [models.Index(fields=["variant", "warehouse", "status"])]

    def __str__(self):
        return f"{self.code} ({self.variant})"


class StockMovement(TenantModel):
    store_lookup = "warehouse__store"

    class Kind(models.TextChoices):
        INITIAL = "initial", "Implantação de saldo"
        PURCHASE = "purchase", "Entrada por compra"
        SALE = "sale", "Saída por venda"
        SALE_RETURN = "sale_return", "Devolução de cliente"
        TRANSFER_IN = "transfer_in", "Transferência (entrada)"
        TRANSFER_OUT = "transfer_out", "Transferência (saída)"
        ADJUSTMENT = "adjustment", "Ajuste / inventário"
        CONSUMPTION = "consumption", "Consumo interno"
        LOSS = "loss", "Perda / avaria"
        EXPIRATION = "expiration", "Vencimento"
        SUPPLIER_RETURN = "supplier_return", "Devolução ao fornecedor"
        ASSET_DISPOSAL = "asset_disposal", "Baixa patrimonial"
        RELOCATION = "relocation", "Movimentação entre endereços"
        REVERSAL = "reversal", "Estorno"

    variant = models.ForeignKey("starrp.ProductVariant", related_name="stock_movements", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, related_name="movements", on_delete=models.PROTECT)
    lot = models.ForeignKey(StockLot, null=True, blank=True, related_name="movements", on_delete=models.PROTECT)
    # Endereço afetado (depósito com WMS). O estorno devolve para o mesmo endereço.
    bin = models.ForeignKey("starrp.StorageBin", null=True, blank=True, related_name="movements",
                            on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    quantity = QuantityField(help_text="Com sinal: positivo entra, negativo sai.")
    balance_after = QuantityField(help_text="Saldo do depósito depois deste movimento (kardex).")
    unit_cost = UnitCostField()
    total_cost = MoneyField()
    document_item = models.ForeignKey(
        "starrp.StockDocumentItem", null=True, blank=True, related_name="movements", on_delete=models.SET_NULL
    )
    sale_item = models.ForeignKey(
        "starrp.SaleItem", null=True, blank=True, related_name="stock_movements", on_delete=models.SET_NULL
    )
    return_item = models.ForeignKey(
        "starrp.SaleReturnItem", null=True, blank=True, related_name="stock_movements", on_delete=models.SET_NULL
    )
    reversal_of = models.ForeignKey(
        "self", null=True, blank=True, related_name="reversals", on_delete=models.PROTECT
    )
    # Identidade da ORIGEM ("sale_item:<id>:<componente>"): a segunda chamada
    # da mesma baixa bate na constraint em vez de baixar de novo.
    source_key = models.CharField(max_length=200, blank=True)
    reason = models.TextField(blank=True)
    operator = user_fk("stock_movements")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "source_key"], condition=~Q(source_key="") & alive(), name="uniq_stock_source_key"
            ),
        ]
        indexes = [
            models.Index(fields=["variant", "warehouse", "created_at"]),
            models.Index(fields=["account", "kind", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.variant}"
