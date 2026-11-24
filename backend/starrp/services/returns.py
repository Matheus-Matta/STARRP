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
from starrp.services.sales import cents, net_total, net_unit_price

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
        SaleReturnItem.all_objects.create(
            account_id=sale.account_id, sale_return=sale_return, sale_item=item, quantity=quantity,
            unit_price=unit, total=line, restock=data.get("restock", True),
        )
        total += line
    if not total:
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
    totals = {}
    for row in rows:  # a soma da devolução inteira por item (rascunho antigo pode ter linha repetida, R2-02)
        totals[row.sale_item_id] = totals.get(row.sale_item_id, Decimal("0")) + row.quantity
    for row in rows:
        if totals[row.sale_item_id] > row.sale_item.quantity - returned_quantity(row.sale_item,
                                                                                exclude_return=sale_return):
            raise StateConflict(f"{row.sale_item.description} já foi devolvido em outra operação.")
        if row.restock and warehouse is not None:
            stock.move_with_components(row.sale_item.variant, warehouse, row.quantity, StockMovement.Kind.SALE_RETURN,
                                       source_key=f"return_item:{row.pk}", return_item=row, operator=user)
        _reverse_commission(row, sale_return)
    _refund(sale_return, user)
    sale_return.status, sale_return.completed_at = SaleReturn.Status.COMPLETED, timezone.now()
    sale_return.save(update_fields=["status", "completed_at", "cash_session", "updated_at"])
    _mark_sale(sale_return.sale, sale_return, user)
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
    received = approved.exclude(method__kind__in=(kinds.STORE_CREDIT, kinds.INSTALLMENT_PLAN)).aggregate(
        t=Sum("amount"))["t"] or Decimal("0")
    received += Installment.all_objects.filter(
        title__payment__in=approved.filter(method__kind=kinds.INSTALLMENT_PLAN), deleted_at__isnull=True,
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
