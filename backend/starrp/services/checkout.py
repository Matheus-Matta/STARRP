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
    Commission, CouponRedemption, CustomerCredit, Payment, PaymentMethod, Sale, SaleChannel, SaleItem,
    StockMovement,
)
from starrp.services import cash, coupons, finance, ledger, stock
from starrp.services.approvals import authorize
from starrp.services.sales import cents, check_discounts, lock_open, net_total

Kind = PaymentMethod.Kind


def _session_for(sale, user, method):
    """Turno que recebe o pagamento. Com "exige caixa aberto", venda do PDV só é cobrada num
    turno ABERTO do operador (qualquer forma); fora do PDV, só o dinheiro exige o turno."""
    session = sale.cash_session or cash.session_for_user(sale.store, user)
    at_counter = sale.channel in (SaleChannel.POS, SaleChannel.MOBILE)
    if session is None and sale.store.rule.require_open_cash_session and (at_counter or method.kind == Kind.CASH):
        raise StateConflict("Abra o caixa antes de receber (o turno também pode estar esperando o gerente conferir "
                            "a abertura).", code="cash_session_required")
    return session


def check_method_store(method, sale):
    """Forma de pagamento da filial da venda, ou da rede (M-03)."""
    if method.account_id != sale.account_id or method.store_id not in (None, sale.store_id):
        raise BusinessError("Esta forma de pagamento é de outra filial.", code="payment_method_other_store")


def credit_balance(customer):
    """Saldo do vale-troca. O crédito com validade vencida não vale (M-06): cada uso consome primeiro o crédito que
    vence antes (entre os que ainda valiam no dia), e o que sobrou do vencido sai do saldo."""
    rows = CustomerCredit.all_objects.filter(customer=customer, deleted_at__isnull=True)
    if not rows.filter(expires_at__isnull=False).exists():
        return cents(rows.aggregate(t=Sum("amount"))["t"] or 0)
    lots, debt = [], Decimal("0")
    for row in rows.order_by("created_at", "pk"):
        if row.amount >= 0:
            lots.append([row.expires_at, row.amount])
            continue
        left, day = -row.amount, timezone.localdate(row.created_at)
        for lot in sorted((x for x in lots if x[0] is None or x[0] >= day), key=lambda x: (x[0] is None, x[0] or day)):
            used = min(left, lot[1])
            lot[1] -= used
            left -= used
        debt += left
    today = timezone.localdate()
    return cents(sum((v for expires, v in lots if expires is None or expires >= today), Decimal("0")) - debt)


def _lock_customer(sale):
    """Trava o cliente até o fim da transação: dois caixas usando o MESMO vale-troca/limite de crediário
    ao mesmo tempo liam o mesmo saldo e os dois passavam (o saldo ficava negativo)."""
    from starrp.models import Customer

    return Customer.all_objects.select_for_update().get(pk=sale.customer_id)


def _check_method(sale, method, amount, installments):
    if installments > method.max_installments:
        raise BusinessError(f"{method.name} aceita no máximo {method.max_installments} parcelas.",
                            code="installments_exceeded")
    if method.kind == Kind.STORE_CREDIT:
        if sale.customer_id is None:
            raise BusinessError("Vale-troca exige o cliente na venda.", code="customer_required")
        _lock_customer(sale)
        if credit_balance(sale.customer) < amount:
            raise BusinessError("Saldo de vale-troca insuficiente.", code="insufficient_credit")
    if method.kind == Kind.INSTALLMENT_PLAN:
        if sale.customer_id is None:
            raise BusinessError("Crediário exige o cliente na venda.", code="customer_required")
        customer = _lock_customer(sale)
        if finance.open_receivables(customer) + amount > customer.credit_limit:
            raise BusinessError("Limite de crediário do cliente excedido.", code="credit_limit_exceeded")


@transaction.atomic
def add_payment(sale, method, amount, user, *, tendered=None, installments=1, idempotency_key=None, **details):
    sale = lock_open(sale)
    amount = cents(amount)
    if amount <= 0:
        raise BusinessError("Valor do pagamento precisa ser maior que zero.", code="amount_invalid")
    check_method_store(method, sale)
    if not method.is_active and not (sale.metafields or {}).get("_offline_id"):
        raise BusinessError(f"{method.name} está desativada.", code="payment_method_inactive")
    change = Decimal("0")
    if method.allows_change:
        tendered = cents(tendered if tendered is not None else amount)
        amount = min(tendered, sale.balance_due)
        change = tendered - amount
        if amount <= 0:
            # Venda já quitada: sem isto nascia um pagamento de R$ 0 com o valor entregue inteiro como "troco".
            raise BusinessError("A venda já está paga.", code="payment_exceeds_balance")
    elif amount > sale.balance_due:
        raise BusinessError("Pagamento maior que o saldo da venda (troco só em dinheiro).", code="payment_exceeds_balance")
    _check_method(sale, method, amount, installments)
    if (method.requires_reference and sale.store.rule.require_payment_reference
            and not (details.get("nsu") or details.get("authorization_code"))):
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
        base = net_total(item, item.quantity)
        if rate > 0:
            Commission.all_objects.create(account_id=sale.account_id, store_id=sale.store_id, seller=seller, sale=sale,
                                          sale_item=item, base_amount=base, rate=rate, amount=cents(base * rate / 100))


def _check_credit_limit(sale):
    """O limite de novo, com o cliente travado (R2-06): o título só nasce na conclusão, então duas vendas abertas,
    cada uma dentro do limite, concluíam as duas."""
    total = sum((p.amount for p in sale.payments.filter(status=Payment.Status.APPROVED).select_related("method")
                 if p.method.kind == Kind.INSTALLMENT_PLAN), Decimal("0"))
    if not total:
        return
    if sale.customer_id is None:
        raise BusinessError("Crediário exige o cliente na venda.", code="customer_required")
    customer = _lock_customer(sale)
    if finance.open_receivables(customer) + total > customer.credit_limit:
        raise BusinessError("Limite de crediário do cliente excedido.", code="credit_limit_exceeded")


@transaction.atomic
def complete(sale, user):
    sale = lock_open(sale)
    items = list(sale.items.filter(status=SaleItem.Status.ACTIVE).select_related("variant__product"))
    if not items:
        raise BusinessError("A venda não tem itens.", code="sale_empty")
    if sale.paid_amount < sale.total:
        raise BusinessError(f"Falta receber R$ {sale.balance_due}.", code="payment_pending")
    if sale.paid_amount > sale.total:
        # Pagou e depois tirou item/ganhou cupom: concluir sumiria com a diferença (nem troco, nem crédito).
        raise StateConflict(f"O recebido (R$ {sale.paid_amount}) passou do total (R$ {sale.total}): refaça o "
                            "pagamento.", code="payment_exceeds_total")
    check_discounts(sale, user, items)
    _check_credit_limit(sale)
    # Sem vendedor: com a regra da filial "exige vendedor" ligada, não conclui; com ela desligada
    # (vendedor opcional), a venda fica com quem concluiu — o caixa — e toda venda tem um responsável.
    if sale.seller_id is None:
        if sale.store.rule.require_seller:
            raise BusinessError("Informe o vendedor da venda.", code="seller_required")
        sale.seller = user
    warehouse = stock.default_warehouse(sale.store)
    rule = stock.settings_for(sale.account_id, warehouse.store_id) if warehouse is not None else None
    for item in items:
        if warehouse is not None:
            stock.move_with_components(item.variant, warehouse, -item.quantity, StockMovement.Kind.SALE,
                                       source_key=f"sale_item:{item.pk}", sale_item=item, operator=user, rule=rule)
    _commissions(sale)
    coupons.redeem(sale)
    for payment in sale.payments.filter(status=Payment.Status.APPROVED).select_related("method"):
        if payment.method.generates_receivable:
            finance.receivable_from_payment(payment, user)
    sale.status, sale.completed_at, sale.updated_by = Sale.Status.COMPLETED, timezone.now(), user
    sale.save(update_fields=["status", "seller", "completed_at", "updated_by", "updated_at"])
    ledger.sale_completed(sale, user)
    return sale


@transaction.atomic
def checkout(sale, user, payments):
    """`payments`: lista de dicts com method, amount e os campos opcionais."""
    for data in payments:
        data = dict(data)
        add_payment(sale, data.pop("method"), data.pop("amount"), user, **data)
    return complete(sale, user)


def _cancel_commissions(sale):
    """A pendente cancela; a já PAGA vira estorno pendente (linha negativa) para descontar no próximo acerto —
    cancelar a linha paga deixava o dinheiro com o vendedor."""
    for paid in sale.commissions.filter(status=Commission.Status.PAID):
        Commission.all_objects.create(
            account_id=paid.account_id, store_id=paid.store_id, seller=paid.seller, sale=sale, sale_item=paid.sale_item,
            base_amount=-paid.base_amount, rate=paid.rate, amount=-paid.amount)
    sale.commissions.filter(status=Commission.Status.PENDING, amount__gt=0).update(status=Commission.Status.CANCELLED)


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
        _cancel_commissions(sale)
        CouponRedemption.all_objects.filter(sale=sale).update(deleted_at=timezone.now())
        finance.cancel_titles_of_sale(sale)
        ledger.sale_cancelled(sale, user)
    for payment in sale.payments.filter(status=Payment.Status.APPROVED).select_related("method", "sale__store"):
        _undo_payment(payment, Payment.Status.REFUNDED if completed else Payment.Status.CANCELLED, user)
    sale.status, sale.cancelled_at, sale.cancelled_by = Sale.Status.CANCELLED, timezone.now(), user
    sale.cancel_approved_by, sale.cancel_reason = approver, reason
    sale.save()
    return sale
