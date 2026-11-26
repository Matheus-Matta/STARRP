"""Troca e devolução.

Regras:
- só venda concluída; não se devolve mais do que foi vendido menos o que já
  voltou em devoluções anteriores;
- o valor devolvido por unidade é o PAGO (descontos do cabeçalho rateados);
- estoque volta para o depósito padrão (ou não, quando `restock=False`);
- a comissão do vendedor é estornada proporcionalmente (linha negativa).
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import (
    CashMovement, CashSession, Commission, CustomerCredit, Sale, SaleItem, SaleReturn, SaleReturnItem, StockMovement,
)
from starrp.services import cash, ledger, numbering, stock
from starrp.services.approvals import authorize
from starrp.services.sales import cents, header_discount, net_total, net_unit_price

Refund = SaleReturn.Refund
WALLET = (Refund.STORE_CREDIT, Refund.EXCHANGE)  # os dois viram crédito na carteira do cliente


def returned_quantity(sale_item, exclude_return=None):
    qs = SaleReturnItem.all_objects.filter(
        sale_item=sale_item, sale_return__status=SaleReturn.Status.COMPLETED, deleted_at__isnull=True
    )
    if exclude_return is not None:
        qs = qs.exclude(sale_return=exclude_return)
    return qs.aggregate(q=Sum("quantity"))["q"] or Decimal("0")


@transaction.atomic
def create(sale, user, items, *, refund_method=Refund.STORE_CREDIT, reason, approval=None):
    """`items`: [{"sale_item": SaleItem, "quantity": Decimal, "restock": bool}]."""
    if sale.status != Sale.Status.COMPLETED:
        raise StateConflict("Só venda concluída aceita devolução.")
    authorize(user, sale.account, sale.store, "sales.return", approval)
    _check_store_credit_refund(sale.store, refund_method)
    # Troca também vira crédito na carteira (`_refund`): as mesmas exigências do vale (R2-13).
    if refund_method in WALLET and sale.customer_id is None:
        raise BusinessError("Vale-troca exige cliente identificado na venda.", code="customer_required")
    sale_return = SaleReturn.all_objects.create(
        account_id=sale.account_id, store_id=sale.store_id, number=numbering.next_number(sale.store, "return"),
        sale=sale, customer=sale.customer, refund_method=refund_method, reason=reason, processed_by=user,
        created_by=user,
    )
    total, asked = Decimal("0"), {}
    given = SaleReturn.all_objects.filter(sale=sale, status=SaleReturn.Status.COMPLETED, deleted_at__isnull=True).aggregate(
        t=Sum("total"))["t"] or Decimal("0")
    room = max(sale.subtotal - header_discount(sale), Decimal("0")) - given
    for data in items:
        item = data["sale_item"]
        quantity = Decimal(data["quantity"])
        if item.sale_id != sale.pk or item.status != SaleItem.Status.ACTIVE:
            raise BusinessError("Item não pertence a esta venda.")
        # O MESMO item em duas linhas soma (R2-02): cada linha sozinha passava e reembolsava em dobro.
        asked[item.pk] = asked.get(item.pk, Decimal("0")) + max(quantity, Decimal("0"))
        if quantity <= 0 or asked[item.pk] > item.quantity - returned_quantity(item):
            raise BusinessError(f"Quantidade inválida para {item.description}.")
        unit = net_unit_price(item)
        # O que foi pago até aqui menos o que já voltou: a última devolução leva o centavo que sobrar.
        already = returned_quantity(item) + asked[item.pk] - quantity
        line = net_total(item, already + quantity) - net_total(item, already)
        line = max(min(line, room - total), Decimal("0"))  # nunca além do que a venda ainda tem a devolver
        SaleReturnItem.all_objects.create(
            account_id=sale.account_id, sale_return=sale_return, sale_item=item, quantity=quantity,
            unit_price=unit, total=line, restock=data.get("restock", True),
        )
        total += line
    if not asked:
        raise BusinessError("Informe ao menos um item para devolver.")
    sale_return.total = total
    sale_return.save(update_fields=["total"])
    return sale_return


@transaction.atomic
def complete(sale_return, user):
    from starrp.models import Sale

    # A VENDA primeiro (mesma ordem do cancelamento): duas devoluções da mesma venda concluídas ao mesmo
    # tempo travavam só a própria devolução e as duas passavam na conferência do "já devolvido".
    sale = Sale.all_objects.select_for_update().get(pk=sale_return.sale_id)
    sale_return = SaleReturn.all_objects.select_for_update().get(pk=sale_return.pk)
    if sale_return.status != SaleReturn.Status.DRAFT:
        raise StateConflict("Devolução já processada.")
    if sale.status != Sale.Status.COMPLETED:
        raise StateConflict("A venda não está mais concluída; cancele esta devolução em rascunho.")
    # A regra pode ter sido desligada depois da criação do rascunho. Revalida ao efetivar,
    # que é o momento em que a carteira do cliente realmente recebe o valor.
    _check_store_credit_refund(sale_return.store, sale_return.refund_method)
    warehouse = stock.default_warehouse(sale_return.store)
    rows = list(sale_return.items.select_related("sale_item__variant__product"))
    _fit(sale, sale_return, rows)
    totals = {}
    for row in rows:  # a soma da devolução inteira por item (rascunho antigo pode ter linha repetida, R2-02)
        totals[row.sale_item_id] = totals.get(row.sale_item_id, Decimal("0")) + row.quantity
    for row in rows:
        if totals[row.sale_item_id] > row.sale_item.quantity - returned_quantity(row.sale_item,
                                                                                exclude_return=sale_return):
            raise StateConflict(f"{row.sale_item.description} já foi devolvido em outra operação.")
        if row.restock and warehouse is not None:
            _restock(row, warehouse, user)
        _reverse_commission(row, sale_return)
    _refund(sale_return, user)
    sale_return.status, sale_return.completed_at = SaleReturn.Status.COMPLETED, timezone.now()
    sale_return.save(update_fields=["status", "completed_at", "cash_session", "updated_at"])
    _mark_sale(sale_return.sale, sale_return, user)
    return sale_return


def _fit(sale, sale_return, rows):
    """Outros rascunhos podem ter concluído depois deste: o total nunca passa do que a venda ainda tem a devolver."""
    given = SaleReturn.all_objects.filter(sale=sale, status=SaleReturn.Status.COMPLETED, deleted_at__isnull=True).aggregate(
        t=Sum("total"))["t"] or Decimal("0")
    extra = sale_return.total - (max(sale.subtotal - header_discount(sale), Decimal("0")) - given)
    for row in reversed(rows):
        if extra <= 0:
            return
        cut = min(extra, row.total)
        row.total, sale_return.total, extra = row.total - cut, sale_return.total - cut, extra - cut
        row.save(update_fields=["total"])
        sale_return.save(update_fields=["total"])


def _gone(move):
    """O lugar de onde saiu não existe mais (a volta dele foi para outro)."""
    return bool(move.warehouse.deleted_at or (move.lot_id and move.lot.deleted_at)
                or (move.bin_id and (move.bin.deleted_at or not move.bin.is_active)))


def _restock(row, warehouse, user):
    """Volta o que SAIU na venda, para o lote e o endereço de onde saiu: produto com lote devolvido sem lote nunca
    mais se vendia, e o kit pode ter mudado de composição depois."""
    item, key = row.sale_item, f"return_item:{row.pk}"
    sold, back = {}, {}
    for move in StockMovement.all_objects.filter(sale_item=item, kind=StockMovement.Kind.SALE).select_related(
            "variant__product", "warehouse", "lot", "bin").order_by("created_at"):
        sold.setdefault(move.variant_id, []).append(move)
    if not sold:
        stock.move_with_components(item.variant, warehouse, row.quantity, StockMovement.Kind.SALE_RETURN,
                                   source_key=key, return_item=row, operator=user)
        return
    for move in StockMovement.all_objects.filter(return_item__sale_item=item, kind=StockMovement.Kind.SALE_RETURN):
        place = (move.variant_id, move.warehouse_id, move.lot_id, move.bin_id)
        back[place] = back.get(place, Decimal("0")) + move.quantity
    # Quanto de cada saída já voltou: primeiro no lugar exato; o que voltou noutro (endereço desativado, lote ou
    # depósito excluído) desconta das saídas que sobraram, na ordem.
    used, every = {}, [m for moves in sold.values() for m in moves]
    for move in every:
        place = (move.variant_id, move.warehouse_id, move.lot_id, move.bin_id)
        used[move.pk] = min(back.get(place, Decimal("0")), -move.quantity)
        back[place] = back.get(place, Decimal("0")) - used[move.pk]
    moved = {}
    for place, quantity in back.items():
        moved[place[0]] = moved.get(place[0], Decimal("0")) + quantity
    for move in sorted(every, key=lambda m: not _gone(m)):
        extra = min(moved.get(move.variant_id, Decimal("0")), -move.quantity - used[move.pk])
        if extra > 0:
            used[move.pk] += extra
            moved[move.variant_id] -= extra
    step = 0
    for moves in sold.values():
        total = -sum((m.quantity for m in moves), Decimal("0"))
        left = (total * row.quantity / item.quantity).quantize(Decimal("0.001"))
        for index, move in enumerate(moves):
            take = min(-move.quantity - used[move.pk], left)
            if index == len(moves) - 1:
                take = left  # arredondamento: o que sobrar volta no último
            if take <= 0:
                continue
            gone = move.warehouse.deleted_at is not None  # depósito excluído: volta no padrão da filial
            lot = move.lot if not gone and move.lot_id and move.lot.deleted_at is None else None
            bin = move.bin if not gone and move.bin_id and move.bin.is_active and move.bin.deleted_at is None else None
            stock.move(move.variant, warehouse if gone else move.warehouse, take, StockMovement.Kind.SALE_RETURN, lot=lot, bin=bin,
                       source_key=f"{key}:{step}", return_item=row, operator=user)
            left -= take
            step += 1


@transaction.atomic
def cancel(sale_return, user):
    """Rascunho cancelado com as mesmas travas da conclusão (R4-07): lido sem trava, o cancelamento gravava por
    cima de uma devolução concluída no meio, e o que já voltou cabia de novo."""
    Sale.all_objects.select_for_update().get(pk=sale_return.sale_id)
    sale_return = SaleReturn.all_objects.select_for_update().get(pk=sale_return.pk)
    if sale_return.status != SaleReturn.Status.DRAFT:
        raise StateConflict("Só devolução em rascunho pode ser cancelada.")
    sale_return.status = SaleReturn.Status.CANCELLED
    sale_return.save(update_fields=["status", "updated_at"])
    return sale_return


def _check_store_credit_refund(store, refund_method):
    if refund_method in WALLET and not store.rule.allow_store_credit_refund:
        raise BusinessError(
            "Esta filial não permite reembolso em crédito na carteira do cliente.",
            code="store_credit_refund_disabled",
        )


def _mark_sale(sale, sale_return, user):
    """O pedido mostra a devolução: o valor estornado e, devolvido tudo, a entrega "Devolvido"."""
    from starrp.models import FulfillmentStatus, Sale, SaleItem

    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    sale.refunded_amount += sale_return.total
    items = sale.items.filter(status=SaleItem.Status.ACTIVE)
    if all(returned_quantity(item) >= item.quantity for item in items):
        sale.fulfillment_status = FulfillmentStatus.RETURNED
    sale.updated_by = user
    sale.save(update_fields=["refunded_amount", "fulfillment_status", "updated_by", "updated_at"])


def _reverse_commission(row, sale_return):
    original = Commission.all_objects.filter(sale_item=row.sale_item, sale_return__isnull=True).exclude(
        status=Commission.Status.CANCELLED
    ).first()
    if original is None or not row.sale_item.quantity:
        return
    share = row.quantity / row.sale_item.quantity
    Commission.all_objects.create(
        account_id=original.account_id, store_id=original.store_id, seller=original.seller, sale=original.sale,
        sale_item=row.sale_item, sale_return=sale_return, base_amount=-cents(original.base_amount * share),
        rate=original.rate, amount=-cents(original.amount * share),
    )


def cash_refundable(sale, exclude=None):
    """Quanto desta venda pode voltar em dinheiro (A-08): o que entrou de dinheiro de verdade (tudo menos vale-troca
    e crediário, mais as parcelas de crediário já recebidas), menos o que já voltou fora da carteira."""
    from django.db.models import Sum

    from starrp.models import Installment, Payment, PaymentMethod

    kinds = PaymentMethod.Kind
    approved = sale.payments.filter(status=Payment.Status.APPROVED)
    later = (kinds.INSTALLMENT_PLAN, kinds.BANK_SLIP)  # só o que já foi recebido é dinheiro (R6-B1: boleto em aberto)
    received = approved.exclude(method__kind__in=(kinds.STORE_CREDIT, *later)).aggregate(
        t=Sum("amount"))["t"] or Decimal("0")
    received += Installment.all_objects.filter(
        title__payment__in=approved.filter(method__kind__in=later), deleted_at__isnull=True,
        title__deleted_at__isnull=True).aggregate(t=Sum("paid_amount"))["t"] or Decimal("0")
    given = SaleReturn.all_objects.filter(sale=sale, status=SaleReturn.Status.COMPLETED, deleted_at__isnull=True)
    if exclude is not None:
        given = given.exclude(pk=exclude.pk)
    return received - (given.exclude(refund_method__in=WALLET).aggregate(t=Sum("total"))["t"] or Decimal("0"))


def _refund(sale_return, user):
    if sale_return.refund_method in (Refund.STORE_CREDIT, Refund.EXCHANGE):
        CustomerCredit.all_objects.create(
            account_id=sale_return.account_id, customer=sale_return.customer, kind=CustomerCredit.Kind.RETURN,
            amount=sale_return.total, sale_return=sale_return, notes=f"Devolução {sale_return.number}",
        )
    elif sale_return.refund_method == Refund.CASH:
        if sale_return.total > cash_refundable(sale_return.sale, exclude=sale_return):
            raise BusinessError("A devolução em dinheiro passa do que o cliente pagou em dinheiro/cartão/PIX nesta "
                                "venda: o que foi pago com vale volta em vale, e o crediário se abate nas parcelas.",
                                code="cash_refund_limit")
        session = cash.session_for_user(sale_return.store, user)
        if session is None:
            raise StateConflict("Abra o caixa para devolver em dinheiro.", code="cash_session_required")
        # Trava o turno: duas devoluções ao mesmo tempo liam a mesma gaveta, e o turno podia fechar no meio.
        session = CashSession.all_objects.select_for_update().get(pk=session.pk)
        if session.status != CashSession.Status.OPEN:
            raise StateConflict("O turno fechou. Abra o caixa para devolver em dinheiro.", code="cash_session_required")
        if cash.expected_cash(session) < sale_return.total:
            raise BusinessError("Dinheiro em gaveta insuficiente para a devolução.")
        CashMovement.all_objects.create(
            account_id=sale_return.account_id, store_id=sale_return.store_id, session=session,
            kind=CashMovement.Kind.REFUND, amount=sale_return.total, sale_return=sale_return, operator=user,
            approved_by=user, approved_at=timezone.now(), reason=f"Devolução {sale_return.number}",
        )
        sale_return.cash_session = session
    elif sale_return.refund_method == Refund.ORIGINAL_PAYMENT:
        # O estorno acontece na adquirente/PIX; no financeiro, sai da conta de origem.
        ledger.refund_to_original(sale_return, user)
