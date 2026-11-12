"""WMS simples: endereços de armazenagem e o saldo em cada um.

Só vale para depósito com `Warehouse.uses_bins`. A regra que não se quebra:
num depósito endereçado, a soma dos `BinBalance` é o `StockBalance` dele —
quem garante é `services.stock`, o único que grava estoque (venda do PDV,
estorno e documento passam todos por lá).
"""
from django.db import models

from starrp.models.base import QuantityField, StoreModel, TenantModel, alive, user_fk


class StorageBin(TenantModel):
    """Um endereço: rua A, prateleira 03, nível 2 → código "A-03-2"."""

    store_lookup = "warehouse__store"

    class Kind(models.TextChoices):
        STORAGE = "storage", "Armazenagem"
        PICKING = "picking", "Separação (frente de loja)"
        RECEIVING = "receiving", "Recebimento (doca)"
        SHIPPING = "shipping", "Expedição"

    warehouse = models.ForeignKey("starrp.Warehouse", related_name="bins", on_delete=models.CASCADE)
    code = models.CharField(max_length=40)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.STORAGE)
    aisle = models.CharField(max_length=10, blank=True, help_text="Rua / corredor.")
    rack = models.CharField(max_length=10, blank=True, help_text="Prateleira / módulo.")
    level = models.CharField(max_length=10, blank=True, help_text="Nível / altura.")
    position = models.CharField(max_length=10, blank=True)
    # Ordem de visita na separação: a lista de coleta segue o caminho físico.
    sequence = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["warehouse", "sequence", "code"]
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "code"], condition=alive(), name="uniq_bin_code"),
        ]

    def __str__(self):
        return self.code


class BinBalance(TenantModel):
    """Quanto de um produto (e de qual lote) está em um endereço."""

    store_lookup = "bin__warehouse__store"

    bin = models.ForeignKey(StorageBin, related_name="balances", on_delete=models.CASCADE)
    variant = models.ForeignKey("starrp.ProductVariant", related_name="bin_balances", on_delete=models.CASCADE)
    lot = models.ForeignKey("starrp.StockLot", null=True, blank=True, related_name="bin_balances", on_delete=models.CASCADE)
    quantity = QuantityField()

    class Meta:
        ordering = ["bin__sequence", "bin__code"]
        constraints = [
            models.UniqueConstraint(fields=["bin", "variant", "lot"], name="uniq_bin_balance"),
            # Sem lote, o NULL não colide no índice único: garante um só "sem lote".
            models.UniqueConstraint(fields=["bin", "variant"], condition=models.Q(lot__isnull=True),
                                    name="uniq_bin_balance_no_lot"),
        ]


class StockAdvice(StoreModel):
    """Uma recomendação da Cosmos para organizar o armazém. Ver `services/cosmos/slotting.py`.

    Não muda nada: aceitar cria a Movimentação entre endereços em rascunho (`document`), que a equipe confirma."""

    history_hidden = ("moves", "impact", "checked_at", "fingerprint", "detail")

    class Kind(models.TextChoices):
        DOCK = "dock", "Parado na doca"
        TOGETHER = "together", "Saem juntos"
        FAST = "fast", "Sai muito"
        SCATTERED = "scattered", "Espalhado"
        IDLE = "idle", "Não sai"

    class Status(models.TextChoices):
        OPEN = "open", "Para decidir"
        APPLIED = "applied", "Aceita"
        DISMISSED = "dismissed", "Recusada"
        EXPIRED = "expired", "Não vale mais"

    warehouse = models.ForeignKey("starrp.Warehouse", related_name="advices", on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    fingerprint = models.CharField(max_length=200, help_text="O mesmo problema é a mesma linha: quem recusou não vê de novo.")
    title = models.CharField(max_length=200)
    detail = models.TextField()
    impact = models.PositiveIntegerField(default=0, help_text="Ordena a lista: quanto maior, mais urgente.")
    moves = models.JSONField(default=list, blank=True, help_text="O que mover, de onde e para onde, no momento da análise.")
    checked_at = models.DateTimeField()
    document = models.ForeignKey("starrp.StockDocument", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    decided_by = user_fk("+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-impact", "-checked_at"]
        constraints = [models.UniqueConstraint(fields=["account", "fingerprint"], condition=alive(), name="uniq_stock_advice")]

    def __str__(self):
        return self.title
