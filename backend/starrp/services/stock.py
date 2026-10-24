"""Movimentação de estoque. O ÚNICO lugar que grava `StockMovement`/`StockBalance`.

- saldo travado com `select_for_update` e relido depois do lock;
- `source_key` torna a baixa idempotente (a mesma venda nunca baixa duas vezes);
- variante com lote consome os lotes por FEFO/FIFO;
- kit baixa os componentes, não o kit;
- entrada com custo recalcula o custo médio ponderado da variante.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from starrp.core.errors import InsufficientStock
from starrp.models import StockBalance, StockLot, StockMovement, StockSettings, Warehouse
from starrp.services import wms

ENTRY_KINDS_WITH_COST = {StockMovement.Kind.PURCHASE, StockMovement.Kind.INITIAL}


def settings_for(account_id):
    found = StockSettings.all_objects.filter(account_id=account_id, deleted_at__isnull=True).first()
    return found or StockSettings(account_id=account_id)


def default_warehouse(store):
    warehouse = Warehouse.all_objects.filter(store=store, is_default=True, deleted_at__isnull=True).first()
    if warehouse is None:
        warehouse = Warehouse.all_objects.filter(store=store, deleted_at__isnull=True).order_by("created_at").first()
    return warehouse


def _locked_balance(variant, warehouse):
    balance, _ = StockBalance.all_objects.select_for_update().get_or_create(
        variant=variant, warehouse=warehouse, defaults={"account_id": variant.account_id}
    )
    return balance


def _update_average_cost(variant, quantity, cost):
    current = StockBalance.all_objects.filter(variant=variant).aggregate(total=Sum("quantity"))["total"] or 0
    previous_qty = max(Decimal(current), Decimal(0))
    total_qty = previous_qty + quantity
    if total_qty > 0:
        variant.average_cost = (previous_qty * variant.average_cost + quantity * cost) / total_qty
    variant.last_cost = cost
    variant.save(update_fields=["average_cost", "last_cost", "updated_at"])


def _record(variant, warehouse, quantity, kind, *, lot, unit_cost, source_key, allow_negative, bin=None, **links):
    if source_key:
        existing = StockMovement.all_objects.filter(account_id=variant.account_id, source_key=source_key).first()
        if existing is not None:
            return existing
    balance = _locked_balance(variant, warehouse)
    new_balance = balance.quantity + quantity
    if new_balance < 0 and quantity < 0 and not allow_negative:
        raise InsufficientStock(f"Estoque insuficiente de {variant.display_name}: saldo {balance.quantity}.")
    if quantity > 0 and kind in ENTRY_KINDS_WITH_COST and unit_cost:
        _update_average_cost(variant, quantity, Decimal(unit_cost))
    cost = Decimal(unit_cost if unit_cost is not None else variant.average_cost)
    if lot is not None:
        lot.quantity += quantity
        lot.status = StockLot.Status.DEPLETED if lot.quantity <= 0 else StockLot.Status.AVAILABLE
        lot.save(update_fields=["quantity", "status", "updated_at"])
    balance.quantity = new_balance
    balance.save(update_fields=["quantity", "updated_at"])
    if bin is not None:
        wms.adjust(bin, variant, lot, quantity, allow_negative=allow_negative)
    return StockMovement.all_objects.create(
        account_id=variant.account_id,
        variant=variant,
        warehouse=warehouse,
        lot=lot,
        bin=bin,
        kind=kind,
        quantity=quantity,
        balance_after=new_balance,
        unit_cost=cost,
        total_cost=(abs(quantity) * cost).quantize(Decimal("0.01")),
        source_key=source_key,
        **links,
    )


def _pick_lots(variant, warehouse, needed, settings):
    lots = StockLot.all_objects.select_for_update().filter(
        variant=variant, warehouse=warehouse, status=StockLot.Status.AVAILABLE, quantity__gt=0, deleted_at__isnull=True
    )
    if settings.block_expired:
        today = timezone.localdate()
        lots = [lot for lot in lots if not lot.expires_at or lot.expires_at >= today]
    order = (lambda lot: (lot.expires_at or timezone.localdate().replace(year=9999), lot.created_at)) if (
        settings.picking_strategy == StockSettings.Picking.FEFO
    ) else (lambda lot: lot.created_at)
    picked = []
    for lot in sorted(lots, key=order):
        if needed <= 0:
            break
        take = min(lot.quantity, needed)
        picked.append((lot, take))
        needed -= take
    return picked, needed


def _move_binned(variant, warehouse, quantity, kind, settings, *, bin, lot, source_key, common):
    """Depósito com WMS: entrada vai para um endereço; saída segue o plano de separação."""
    if quantity >= 0:
        target = bin or wms.default_bin(warehouse)
        return [_record(variant, warehouse, quantity, kind, lot=lot, bin=target, source_key=source_key, **common)]
    picks, missing = wms.plan(variant, warehouse, -quantity, settings, bin=bin, lot=lot)
    if missing > 0 and not common["allow_negative"]:
        where = f" no endereço {bin.code}" if bin else ""
        raise InsufficientStock(f"Estoque endereçado insuficiente de {variant.display_name}{where}.")
    movements = []
    for index, pick in enumerate(picks):
        key = f"{source_key}:p{index}" if source_key else ""
        movements.append(_record(variant, warehouse, -pick.quantity, kind, lot=pick.lot, bin=pick.bin,
                                 source_key=key, **common))
    if missing > 0:
        key = f"{source_key}:short" if source_key else ""
        movements.append(_record(variant, warehouse, -missing, kind, lot=lot, bin=bin or wms.default_bin(warehouse),
                                 source_key=key, **common))
    return movements


@transaction.atomic
def move(variant, warehouse, quantity, kind, *, lot=None, bin=None, unit_cost=None, source_key="",
         allow_negative=None, **links):
    """Movimenta `quantity` (com sinal). Devolve a lista de movimentos gerados.

    Depósito com WMS (`uses_bins`): `bin` escolhe o endereço; sem ele, a entrada
    vai para a doca de recebimento e a saída segue o plano de separação.
    """
    if not variant.track_stock:  # serviço, kit e "não controla estoque"
        return []
    quantity = Decimal(quantity)
    settings = settings_for(variant.account_id)
    if allow_negative is None:
        allow_negative = settings.allow_negative_stock
    common = {"unit_cost": unit_cost, "allow_negative": allow_negative, **links}
    if warehouse.uses_bins:
        return _move_binned(variant, warehouse, quantity, kind, settings, bin=bin, lot=lot, source_key=source_key,
                            common=common)
    if quantity >= 0 or not variant.track_lots or lot is not None:
        return [_record(variant, warehouse, quantity, kind, lot=lot, source_key=source_key, **common)]
    picked, missing = _pick_lots(variant, warehouse, -quantity, settings)
    if missing > 0 and not allow_negative:
        raise InsufficientStock(f"Lotes disponíveis insuficientes de {variant.display_name}.")
    movements = []
    for index, (picked_lot, take) in enumerate(picked):
        key = f"{source_key}:lot{index}" if source_key else ""
        movements.append(_record(variant, warehouse, -take, kind, lot=picked_lot, source_key=key, **common))
    if missing > 0:
        key = f"{source_key}:nolot" if source_key else ""
        movements.append(_record(variant, warehouse, -missing, kind, lot=None, source_key=key, **common))
    return movements


@transaction.atomic
def move_with_components(variant, warehouse, quantity, kind, *, source_key, **links):
    """Kit movimenta as variantes que o compõem; o resto movimenta a si mesmo."""
    if not variant.is_kit:
        return move(variant, warehouse, quantity, kind, source_key=source_key, **links)
    movements = []
    for comp in variant.product.components.filter(deleted_at__isnull=True).select_related("component__product"):
        key = f"{source_key}:{comp.component_id}"
        movements += move(comp.component, warehouse, Decimal(quantity) * comp.quantity, kind, source_key=key, **links)
    return movements


@transaction.atomic
def reverse(movement, *, operator=None, reason=""):
    """Estorno: movimento inverso, ligado ao original. Nunca apaga o razão."""
    return _record(
        movement.variant,
        movement.warehouse,
        -movement.quantity,
        StockMovement.Kind.REVERSAL,
        lot=movement.lot,
        bin=movement.bin,
        unit_cost=movement.unit_cost,
        source_key=f"reversal:{movement.pk}",
        allow_negative=True,
        reversal_of=movement,
        operator=operator,
        reason=reason,
    )


def available(variant, warehouse=None):
    qs = StockBalance.all_objects.filter(variant=variant)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    return qs.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
