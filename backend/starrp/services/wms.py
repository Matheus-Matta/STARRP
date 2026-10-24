"""WMS simples: saldo por endereço, endereço de recebimento e plano de separação.

Quem chama é `services.stock` (o único que grava estoque): todo movimento num
depósito endereçado passa por aqui, e por isso a soma dos endereços é sempre
o saldo do depósito — inclusive na venda do PDV e no estorno.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

from starrp.core.errors import BusinessError, InsufficientStock
from starrp.models import BinBalance, StockSettings, StorageBin

FAR_FUTURE = timezone.datetime(9999, 12, 31).date()


@dataclass
class Pick:
    bin: StorageBin
    lot: object  # StockLot | None
    quantity: Decimal


def default_bin(warehouse):
    """Para onde vai o que entra sem endereço: a doca de recebimento, senão o primeiro."""
    bins = StorageBin.all_objects.filter(warehouse=warehouse, is_active=True, deleted_at__isnull=True)
    found = bins.filter(kind=StorageBin.Kind.RECEIVING).order_by("sequence", "code").first()
    found = found or bins.order_by("sequence", "code").first()
    if found is None:
        raise BusinessError(f"O depósito {warehouse} controla endereços mas não tem nenhum cadastrado.",
                            code="bin_required")
    return found


def adjust(bin, variant, lot, quantity, *, allow_negative=False):
    """Soma `quantity` (com sinal) ao saldo do endereço, travando a linha."""
    row, _ = BinBalance.all_objects.select_for_update().get_or_create(
        bin=bin, variant=variant, lot=lot, defaults={"account_id": variant.account_id}
    )
    if row.quantity + quantity < 0 and not allow_negative:
        raise InsufficientStock(f"Endereço {bin.code} tem só {row.quantity} de {variant.display_name}.")
    row.quantity = F("quantity") + quantity
    row.save(update_fields=["quantity", "updated_at"])
    return row


def plan(variant, warehouse, quantity, settings, *, bin=None, lot=None):
    """De quais endereços (e lotes) tirar `quantity`. Não grava nada.

    Ordem: produto com lote → o que vence primeiro (FEFO), depois a rota;
    sem lote → a rota do depósito (`sequence`), para a coleta andar em linha.
    Devolve (picks, faltando).
    """
    rows = (
        BinBalance.all_objects.select_related("bin", "lot")
        .filter(variant=variant, bin__warehouse=warehouse, bin__is_active=True, quantity__gt=0)
    )
    if bin is not None:
        rows = rows.filter(bin=bin)
    if lot is not None:
        rows = rows.filter(lot=lot)
    today = timezone.localdate()
    if settings.block_expired:
        rows = [r for r in rows if r.lot is None or not r.lot.expires_at or r.lot.expires_at >= today]

    fefo = variant.track_lots and settings.picking_strategy == StockSettings.Picking.FEFO

    def order(row):
        expiry = (row.lot.expires_at or FAR_FUTURE) if (fefo and row.lot) else FAR_FUTURE
        return (expiry, row.bin.sequence, row.bin.code)

    picks, needed = [], Decimal(quantity)
    for row in sorted(rows, key=order):
        if needed <= 0:
            break
        take = min(row.quantity, needed)
        picks.append(Pick(row.bin, row.lot, take))
        needed -= take
    return picks, needed


def bin_total(warehouse, variant):
    return BinBalance.all_objects.filter(bin__warehouse=warehouse, variant=variant).aggregate(
        t=Sum("quantity"))["t"] or Decimal("0")
