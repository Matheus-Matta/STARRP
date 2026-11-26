"""Movimentação de estoque. O ÚNICO lugar que grava `StockMovement`/`StockBalance`.

- saldo travado com `select_for_update` e relido depois do lock;
- `source_key` torna a baixa idempotente (a mesma venda nunca baixa duas vezes);
- variante com lote consome os lotes por FEFO/FIFO;
- kit baixa os componentes, não o kit;
- entrada com custo recalcula o custo médio ponderado da variante.
"""
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from starrp.core.errors import BusinessError, InsufficientStock
from starrp.models import ProductVariant, StockBalance, StockLot, StockMovement, StockRule, Warehouse
from starrp.services import wms

ENTRY_KINDS_WITH_COST = {StockMovement.Kind.PURCHASE, StockMovement.Kind.INITIAL}


# Estorno e contagem acertam o lote mesmo que ele fique devendo; o resto não tira do lote mais do que ele tem.
LOT_MAY_OWE = {StockMovement.Kind.REVERSAL, StockMovement.Kind.ADJUSTMENT}


def settings_for(account_id, store_id=None):
    """A regra de estoque da filial (`Store.stock_rule`); sem filial, a padrão da conta."""
    from starrp.services import rules

    return rules.of_store("stock_rule", store_id, account_id)


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


def _lock_costs(variant):
    """Trava a variante e relê os custos: o objeto do chamador pode estar velho (o mesmo produto em duas linhas
    do documento, ou duas entradas ao mesmo tempo em depósitos diferentes)."""
    fresh = ProductVariant.all_objects.select_for_update(of=("self",)).only("average_cost", "last_cost").get(
        pk=variant.pk)
    variant.average_cost, variant.last_cost = fresh.average_cost, fresh.last_cost


def _total_quantity(variant):
    total = StockBalance.all_objects.filter(variant=variant).aggregate(total=Sum("quantity"))["total"]
    return Decimal(total or 0)


def _update_average_cost(variant, quantity, cost):
    _lock_costs(variant)
    previous_qty = max(_total_quantity(variant), Decimal(0))
    total_qty = previous_qty + quantity
    if total_qty > 0:
        variant.average_cost = (previous_qty * variant.average_cost + quantity * cost) / total_qty
    variant.last_cost = cost
    variant.save(update_fields=["average_cost", "last_cost", "updated_at"])


def _restore_average_cost(movement):
    """Estorno: a quantidade sai (entrada cancelada) ou volta (venda cancelada) pelo custo com que se moveu.

    Antes de gravar o estorno. Sem base para a conta (custo zero, saldo que zera ou resultado negativo), o custo
    médio fica como está."""
    entry = movement.kind in ENTRY_KINDS_WITH_COST
    if movement.unit_cost <= 0 or not (entry or movement.kind == StockMovement.Kind.SALE):
        return
    variant = movement.variant
    _lock_costs(variant)
    previous_qty = max(_total_quantity(variant), Decimal(0))
    total_qty = previous_qty - movement.quantity
    value = previous_qty * variant.average_cost - movement.quantity * movement.unit_cost
    if total_qty > 0 and value > 0:
        variant.average_cost = value / total_qty
    if entry and variant.last_cost == movement.unit_cost:
        previous = StockMovement.all_objects.filter(
            variant=variant, kind__in=ENTRY_KINDS_WITH_COST, unit_cost__gt=0, reversals__isnull=True,
        ).exclude(pk=movement.pk).order_by("-created_at").values_list("unit_cost", flat=True).first()
        if previous is not None:
            variant.last_cost = previous
    variant.save(update_fields=["average_cost", "last_cost", "updated_at"])


def _record(variant, warehouse, quantity, kind, *, lot, unit_cost, source_key, allow_negative, bin=None,
            checked=False, **links):
    # `checked`: quem chama (`move`) já conferiu esta chave e as derivadas dela numa consulta só.
    if source_key and not checked:
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
        # Relido com trava (R4-16): o mesmo lote em duas linhas, cada uma com a sua cópia, baixava uma vez só.
        lot.quantity = StockLot.all_objects.select_for_update(of=("self",)).only("quantity").get(pk=lot.pk).quantity
        lot.quantity += quantity
        if lot.quantity < 0 and quantity < 0 and kind not in LOT_MAY_OWE:
            raise InsufficientStock(f"O lote {lot.lot_number or lot.code} de {variant.display_name} não tem essa quantidade.")
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


FAR_FUTURE = date(9999, 12, 31)


def _age(lot):
    """Mais antigo primeiro: a data de ENTRADA (transferência leva a data junto), depois a criação."""
    return (lot.received_at or lot.created_at.date(), lot.created_at)


def uses_lots(variant, settings):
    """Com lote: o produto exige lote/validade, ou a regra guarda a data de entrada (FIFO)."""
    return variant.track_lots or settings.fifo_by_entry


def _unlotted(variant, warehouse):
    """Saldo sem lote: o que entrou ANTES de a regra passar a guardar a data de entrada."""
    balance = StockBalance.all_objects.filter(variant=variant, warehouse=warehouse).values_list(
        "quantity", flat=True).first() or Decimal("0")
    in_lots = StockLot.all_objects.filter(variant=variant, warehouse=warehouse, quantity__gt=0,
                                          deleted_at__isnull=True).aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    return max(balance - in_lots, Decimal("0"))


def _pick_lots(variant, warehouse, needed, settings):
    lots = StockLot.all_objects.select_for_update().filter(
        variant=variant, warehouse=warehouse, status=StockLot.Status.AVAILABLE, quantity__gt=0, deleted_at__isnull=True
    )
    if settings.block_expired:
        today = timezone.localdate()
        lots = [lot for lot in lots if not lot.expires_at or lot.expires_at >= today]
    order = (lambda lot: (lot.expires_at or FAR_FUTURE, *_age(lot))) if (
        settings.picking_strategy == StockRule.Picking.FEFO
    ) else _age
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
         allow_negative=None, rule=None, **links):
    """Movimenta `quantity` (com sinal). Devolve a lista de movimentos gerados.

    `rule`: a regra de estoque da filial do depósito, quando o chamador já tem (venda/documento com
    vários itens buscam uma vez em vez de uma por item).

    Depósito com WMS (`uses_bins`): `bin` escolhe o endereço; sem ele, a entrada
    vai para a doca de recebimento e a saída segue o plano de separação.
    """
    # Última barreira do isolamento (R2-03): produto, depósito, lote e endereço da mesma conta/depósito.
    if variant.account_id != warehouse.account_id:
        raise BusinessError("Produto e depósito são de contas diferentes.", code="stock_scope")
    if lot is not None and (lot.variant_id != variant.pk or lot.warehouse_id != warehouse.pk):
        raise BusinessError("O lote não é deste produto neste depósito.", code="stock_lot_mismatch")
    if bin is not None and bin.warehouse_id != warehouse.pk:
        raise BusinessError("O endereço não é deste depósito.", code="stock_bin_mismatch")
    if unit_cost is not None and Decimal(unit_cost) < 0:
        raise BusinessError("Custo não pode ser negativo.", code="stock_negative_cost")
    if not variant.track_stock:  # serviço, kit e "não controla estoque"
        return []
    quantity = Decimal(quantity)
    if source_key:
        # Reenvio (fila do PDV, clique duplo): a baixa já feita — inteira ou dividida em lotes — não repete.
        done = list(StockMovement.all_objects.filter(
            Q(source_key=source_key) | Q(source_key__startswith=f"{source_key}:"),
            account_id=variant.account_id, variant=variant, warehouse=warehouse).order_by("created_at"))
        if done:
            return done
    settings = rule or settings_for(variant.account_id, warehouse.store_id)
    if allow_negative is None:
        allow_negative = settings.allow_negative_stock
    common = {"unit_cost": unit_cost, "allow_negative": allow_negative, "checked": True, **links}
    if warehouse.uses_bins:
        return _move_binned(variant, warehouse, quantity, kind, settings, bin=bin, lot=lot, source_key=source_key,
                            common=common)
    if quantity >= 0 or not uses_lots(variant, settings) or lot is not None:
        return [_record(variant, warehouse, quantity, kind, lot=lot, source_key=source_key, **common)]
    needed, movements = -quantity, []
    if not variant.track_lots:
        # Sem validade (FIFO pela entrada): o saldo antigo, sem lote, é o mais velho; sai primeiro.
        old = min(_unlotted(variant, warehouse), needed)
        if old > 0:
            key = f"{source_key}:old" if source_key else ""
            movements.append(_record(variant, warehouse, -old, kind, lot=None, source_key=key, **common))
            needed -= old
    picked, missing = _pick_lots(variant, warehouse, needed, settings)
    if missing > 0 and not allow_negative and variant.track_lots:
        raise InsufficientStock(f"Lotes disponíveis insuficientes de {variant.display_name}.")
    for index, (picked_lot, take) in enumerate(picked):
        key = f"{source_key}:lot{index}" if source_key else ""
        movements.append(_record(variant, warehouse, -take, kind, lot=picked_lot, source_key=key, **common))
    if missing > 0:
        key = f"{source_key}:nolot" if source_key else ""
        movements.append(_record(variant, warehouse, -missing, kind, lot=None, source_key=key, **common))
    return movements


@transaction.atomic
def seed(variants, *, warehouse, quantity, unit_cost, operator):
    """O saldo com que o produto nasce: cada variante entra com `quantity` (e o custo vira o custo médio)."""
    for variant in variants:
        move(variant, warehouse, quantity, StockMovement.Kind.INITIAL, unit_cost=unit_cost, operator=operator,
             source_key=f"initial:{variant.pk}", reason="Estoque inicial no cadastro do produto.")


@transaction.atomic
def move_with_components(variant, warehouse, quantity, kind, *, source_key, **links):
    """Kit movimenta as variantes que o compõem; o resto movimenta a si mesmo. Aceita `rule` (ver `move`)."""
    if not variant.is_kit:
        return move(variant, warehouse, quantity, kind, source_key=source_key, **links)
    movements = []
    for comp in variant.product.components.filter(deleted_at__isnull=True).select_related("component__product"):
        key = f"{source_key}:{comp.component_id}"
        movements += move(comp.component, warehouse, Decimal(quantity) * comp.quantity, kind, source_key=key, **links)
    return movements


@transaction.atomic
def reverse(movement, *, operator=None, reason=""):
    """Estorno: movimento inverso, ligado ao original. Nunca apaga o razão. Repetido, devolve o já feito."""
    key = f"reversal:{movement.pk}"
    existing = StockMovement.all_objects.filter(account_id=movement.account_id, source_key=key).first()
    if existing is not None:
        return existing
    _locked_balance(movement.variant, movement.warehouse)  # mesma ordem de trava da entrada: saldo, depois custo
    _restore_average_cost(movement)
    return _record(
        movement.variant,
        movement.warehouse,
        -movement.quantity,
        StockMovement.Kind.REVERSAL,
        lot=movement.lot,
        bin=movement.bin,
        unit_cost=movement.unit_cost,
        source_key=key,
        checked=True,
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


def scoped_stock(request=None, store_ids=None, of="variant"):
    """Subquery do saldo somado da variante (`of="variant"`) ou do produto (`of="product"`, todas as
    variantes vivas dele) da linha de fora, só nos
    depósitos que a tela pode ver: a filial ATIVA; sem ela, as filiais permitidas do usuário.

    Subquery (e não `Sum("balances__quantity")` no queryset): o Sum por join somava os depósitos de
    TODAS as filiais (o PDV de uma loja mostrava o estoque da rede inteira, e quem é restrito a uma
    filial via o total das outras) e ainda se mistura com os joins de busca/filtro."""
    from django.db.models import OuterRef, Subquery

    if of == "product":
        qs = StockBalance.all_objects.filter(variant__product_id=OuterRef("pk"), variant__deleted_at__isnull=True)
        group = "variant__product_id"
    else:
        qs = StockBalance.all_objects.filter(variant_id=OuterRef("pk"))
        group = "variant_id"
    qs = qs.filter(deleted_at__isnull=True)
    if store_ids is None and request is not None:
        store = getattr(request, "store", None)
        if store is not None:
            store_ids = [store.pk]
        else:
            store_ids = getattr(request, "allowed_store_ids", None)
    if store_ids is not None:
        qs = qs.filter(warehouse__store_id__in=list(store_ids))
    total = qs.order_by().values(group).annotate(t=Sum("quantity")).values("t")
    return Subquery(total, output_field=StockBalance._meta.get_field("quantity"))
