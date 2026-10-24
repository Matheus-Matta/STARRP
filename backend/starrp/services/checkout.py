"""Pagamento, conclusão e cancelamento da venda.

`checkout` faz tudo numa transação só (pagamentos + conclusão): é o que o PDV
chama com `Idempotency-Key`, e um reenvio nunca cobra nem baixa duas vezes.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import (
    Commission, CouponRedemption, CustomerCredit, Payment, PaymentMethod, Sale, SaleItem, StockMovement,
)
from starrp.services import cash, coupons, finance, ledger, stock
from starrp.services.approvals import authorize
from starrp.services.sales import cents, lock_open, net_unit_price

Kind = PaymentMethod.Kind


def _session_for(sale, user, method):
    session = sale.cash_session or cash.session_for_user(sale.store, user)
    if session is None and method.kind == Kind.CASH and sale.store.require_open_cash_session:
        raise StateConflict("Abra o caixa antes de receber em dinheiro.", code="cash_session_required")
    return session


def credit_balance(customer):
    total = CustomerCredit.all_objects.filter(customer=customer, deleted_at__isnull=True).aggregate(
        t=Sum("amount"))["t"]
    return cents(total or 0)


def _check_method(sale, method, amount, installments):
    if installments > method.max_installments:
        raise BusinessError(f"{method.name} aceita no máximo {method.max_installments} parcelas.")
    if method.kind == Kind.STORE_CREDIT:
        if sale.customer_id is None:
            raise BusinessError("Vale-troca exige o cliente na venda.", code="customer_required")
        if credit_balance(sale.customer) < amount:
            raise BusinessError("Saldo de vale-troca insuficiente.", code="insufficient_credit")
    if method.kind == Kind.INSTALLMENT_PLAN:
        customer = sale.customer
        if customer is None:
            raise BusinessError("Crediário exige o cliente na venda.", code="customer_required")
        if finance.open_receivables(customer) + amount > customer.credit_limit:
            raise BusinessError("Limite de crediário do cliente excedido.", code="credit_limit_exceeded")


@transaction.atomic
def add_payment(sale, method, amount, user, *, tendered=None, installments=1, idempotency_key=None, **details):
    sale = lock_open(sale)
    amount = cents(amount)
    if amount <= 0:
        raise BusinessError("Valor do pagamento precisa ser maior que zero.")
    change = Decimal("0")
    if method.allows_change:
        tendered = cents(tendered if tendered is not None else amount)
        amount = min(tendered, sale.balance_due)
        change = tendered - amount
    elif amount > sale.balance_due:
        raise BusinessError("Pagamento maior que o saldo da venda (troco só em dinheiro).")
    _check_method(sale, method, amount, installments)
    if method.requires_reference and not (details.get("nsu") or details.get("authorization_code")):
        raise BusinessError(f"{method.name}: informe o NSU/autorização do comprovante.", code="reference_required")
    session = _session_for(sale, user, method)
    payment = Payment.all_objects.create(
        account_id=sale.account_id, store_id=sale.store_id, sale=sale, method=method, cash_session=session,
        amount=amount, tendered_amount=tendered or amount, change_amount=change, installments=installments,
        idempotency_key=idempotency_key, created_by=user, **details,
    )
    if method.kind == Kind.STORE_CREDIT:
        CustomerCredit.all_objects.create(account_id=sale.account_id, customer=sale.customer,
                                          kind=CustomerCredit.Kind.USAGE, amount=-amount, payment=payment)
    if method.kind == Kind.CASH and session is not None:
        cash.record_cash_payment(session, payment, user)
    sale.paid_amount += amount
    sale.change_amount += change
    sale.cash_session = sale.cash_session or session
    sale.save(update_fields=["paid_amount", "change_amount", "cash_session", "updated_at"])
    return payment


@transaction.atomic
def remove_payment(payment, user):
    sale = lock_open(payment.sale)
    payment = Payment.all_objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.APPROVED:
        raise StateConflict("Pagamento já cancelado.")
    _undo_payment(payment, Payment.Status.CANCELLED)
    sale.paid_amount -= payment.amount
    sale.change_amount -= payment.change_amount
    sale.save(update_fields=["paid_amount", "change_amount", "updated_at"])
    return payment


def _undo_payment(payment, status, user=None):
    """Venda aberta: cancela o movimento de gaveta do mesmo turno. Venda já
    concluída: o turno original pode estar fechado, então o dinheiro sai do
    turno ATUAL como devolução — o histórico fechado nunca é reescrito."""
    from starrp.models import CashMovement

    payment.status = status
    payment.save(update_fields=["status", "updated_at"])
    payment.credits.update(deleted_at=timezone.now())
    if status == Payment.Status.CANCELLED:
        CashMovement.all_objects.filter(payment=payment).update(status=CashMovement.Status.CANCELLED)
    elif payment.method.kind == Kind.CASH:
        session = cash.session_for_user(payment.sale.store, user)
        if session is None:
            raise StateConflict("Abra o caixa para devolver o dinheiro.", code="cash_session_required")
        CashMovement.all_objects.create(
            account_id=payment.account_id, store_id=payment.store_id, session=session,
            kind=CashMovement.Kind.REFUND, amount=payment.amount, payment=payment, operator=user,
            approved_by=user, approved_at=timezone.now(), reason=f"Cancelamento da venda {payment.sale.number}",
        )


def _commissions(sale):
    for item in sale.items.filter(status=SaleItem.Status.ACTIVE).select_related("variant__product", "seller__profile"):
        seller = item.seller or sale.seller
        if seller is None:
            continue
        profile = getattr(seller, "profile", None)
        rate = item.variant.product.commission_percent
        if rate is None:
            rate = profile.commission_percent if profile else Decimal("0")
        base = cents(net_unit_price(item) * item.quantity)
        if rate > 0:
            Commission.all_objects.create(account_id=sale.account_id, store_id=sale.store_id, seller=seller, sale=sale,
                                          sale_item=item, base_amount=base, rate=rate, amount=cents(base * rate / 100))


@transaction.atomic
def complete(sale, user):
    sale = lock_open(sale)
    items = list(sale.items.filter(status=SaleItem.Status.ACTIVE).select_related("variant__product"))
    if not items:
        raise BusinessError("A venda não tem itens.")
    if sale.paid_amount < sale.total:
        raise BusinessError(f"Falta receber R$ {sale.balance_due}.", code="payment_pending")
    if sale.store.require_seller and sale.seller_id is None:
        raise BusinessError("Informe o vendedor da venda.", code="seller_required")
    warehouse = stock.default_warehouse(sale.store)
    for item in items:
        if warehouse is not None:
            stock.move_with_components(item.variant, warehouse, -item.quantity, StockMovement.Kind.SALE,
                                       source_key=f"sale_item:{item.pk}", sale_item=item, operator=user)
    _commissions(sale)
    coupons.redeem(sale)
    for payment in sale.payments.filter(status=Payment.Status.APPROVED).select_related("method"):
        if payment.method.generates_receivable:
            finance.receivable_from_payment(payment, user)
    sale.status, sale.completed_at, sale.updated_by = Sale.Status.COMPLETED, timezone.now(), user
    sale.save(update_fields=["status", "completed_at", "updated_by", "updated_at"])
    ledger.sale_completed(sale, user)
    return sale


@transaction.atomic
def checkout(sale, user, payments):
    """`payments`: lista de dicts com method, amount e os campos opcionais."""
    for data in payments:
        data = dict(data)
        add_payment(sale, data.pop("method"), data.pop("amount"), user, **data)
    return complete(sale, user)


@transaction.atomic
def cancel(sale, user, reason, approval=None):
    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    if sale.status == Sale.Status.CANCELLED:
        raise StateConflict("Venda já cancelada.")
    if not reason:
        raise BusinessError("Informe o motivo do cancelamento.")
    if sale.returns.filter(status="completed").exists():
        raise StateConflict("Venda com devolução não pode ser cancelada.")
    if sale.invoices.filter(status="authorized").exists():
        raise StateConflict("Cancele a nota fiscal autorizada antes de cancelar a venda.", code="invoice_authorized")
    approver = authorize(user, sale.account, sale.store, "sales.cancel", approval)
    completed = sale.status == Sale.Status.COMPLETED
    if completed:
        for movement in StockMovement.all_objects.filter(sale_item__sale=sale, reversal_of__isnull=True).exclude(
            kind=StockMovement.Kind.REVERSAL
        ):
            stock.reverse(movement, operator=user, reason=f"Cancelamento da venda {sale.number}")
        sale.commissions.update(status=Commission.Status.CANCELLED)
        CouponRedemption.all_objects.filter(sale=sale).update(deleted_at=timezone.now())
        finance.cancel_titles_of_sale(sale)
        ledger.sale_cancelled(sale, user)
    for payment in sale.payments.filter(status=Payment.Status.APPROVED).select_related("method", "sale__store"):
        _undo_payment(payment, Payment.Status.REFUNDED if completed else Payment.Status.CANCELLED, user)
    sale.status, sale.cancelled_at, sale.cancelled_by = Sale.Status.CANCELLED, timezone.now(), user
    sale.cancel_approved_by, sale.cancel_reason = approver, reason
    sale.save()
    return sale
