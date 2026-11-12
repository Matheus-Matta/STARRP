"""Correções em venda JÁ CONCLUÍDA, cada uma com permissão própria e motivo no histórico.

- Entrega (`sales.edit_delivery`): troca o endereço/tabela de frete ou passa para retirada
  (e vice-versa) enquanto a mercadoria não chegou no cliente. O FRETE COBRADO NÃO MUDA: a venda
  já foi paga e o total fechado; diferença de frete se acerta à parte (devolução, novo pedido).
- Pagamento (`sales.edit_payment`): troca a FORMA de um pagamento ("lançou PIX, foi cartão"),
  com o mesmo valor. O pagamento antigo fica cancelado (com o que ele gerou estornado: conta
  financeira, título a receber, gaveta, vale-troca) e nasce outro, que gera o que a forma nova gera.

Venda aberta não passa por aqui: o PDV muda a entrega e os pagamentos dela direto.
"""
from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.permissions import has_permission_code
from starrp.models import CashMovement, CustomerCredit, FinancialTitle, Payment, PaymentMethod, Sale
from starrp.models.sales import FulfillmentStatus
from starrp.services import cash, finance, ledger, sales
from starrp.services.checkout import _check_method

Kind = PaymentMethod.Kind
LOCKED_FULFILLMENT = (FulfillmentStatus.DELIVERED, FulfillmentStatus.RETURNED, FulfillmentStatus.CANCELLED)


def _completed(sale, user, permission):
    if not has_permission_code(user, permission):
        raise StateConflict("Seu cargo não pode fazer esta alteração.", code="permission_denied")
    sale = Sale.all_objects.select_for_update().get(pk=sale.pk)
    if sale.status != Sale.Status.COMPLETED:
        raise StateConflict("Só venda concluída se corrige por aqui (a aberta muda no PDV).", code="sale_not_completed")
    return sale


def _reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise BusinessError("Diga o motivo da alteração (fica no histórico do pedido).", code="reason_required")
    return reason[:255]


@transaction.atomic
def change_delivery(sale, user, *, reason, address=None, table=None, pickup=False):
    sale = _completed(sale, user, "sales.edit_delivery")
    reason = _reason(reason)
    if sale.fulfillment_status in LOCKED_FULFILLMENT:
        raise StateConflict(f"A entrega está '{sale.get_fulfillment_status_display()}': não muda mais.",
                            code="fulfillment_locked")
    if pickup:
        sales.mark_pickup(sale)
    else:
        if address is None or table is None:
            raise BusinessError("Escolha o endereço e a tabela de frete.", code="delivery_incomplete")
        sales.apply_delivery_info(sale, user, address, table, sales.quote_delivery(sale, address, table))
    sale.updated_by = user
    sale._change_reason = f"Entrega alterada: {reason}"
    sale.save(update_fields=["shipping_address", "metafields", "updated_by", "updated_at"])
    return sale


def _undo(payment, user, label):
    """Desfaz o que o pagamento gerou. Dinheiro só volta se o turno dele ainda está aberto: turno
    fechado já foi conferido e não se reescreve."""
    if payment.method.kind == Kind.CASH:
        session = payment.cash_session
        if session is None or session.is_finished:
            raise StateConflict("Este pagamento em dinheiro é de um turno de caixa já fechado: acerte com sangria/"
                                "suprimento no caixa atual.", code="cash_session_closed")
        CashMovement.all_objects.filter(payment=payment).update(status=CashMovement.Status.CANCELLED)
    payment.credits.update(deleted_at=timezone.now())  # vale-troca usado volta ao saldo
    finance.cancel_titles(FinancialTitle.all_objects.filter(payment=payment),
                          "O título deste pagamento já tem parcela recebida; estorne no financeiro antes.")
    ledger.payment_undone(payment, label, user)


@transaction.atomic
def change_payment(payment, user, method, *, reason, installments=1, nsu="", authorization_code=""):
    sale = _completed(payment.sale, user, "sales.edit_payment")
    reason = _reason(reason)
    payment = Payment.all_objects.select_for_update().select_related("method", "cash_session").get(pk=payment.pk)
    if payment.status != Payment.Status.APPROVED:
        raise StateConflict("Só se troca a forma de um pagamento aprovado.", code="payment_not_approved")
    if method.account_id != sale.account_id or not method.is_active:
        raise BusinessError("Forma de pagamento inválida.")
    installments = max(int(installments or 1), 1)
    _check_method(sale, method, payment.amount, installments)
    session = payment.cash_session
    if method.kind == Kind.CASH:
        # O dinheiro entra AGORA, na gaveta de quem está corrigindo.
        session = cash.session_for_user(sale.store, user)
        if session is None:
            raise StateConflict("Abra o caixa para receber em dinheiro.", code="cash_session_required")

    _undo(payment, user, f"Troca de pagamento da venda {sale.number}")
    payment.status = Payment.Status.CANCELLED
    payment.save(update_fields=["status", "updated_at"])

    replacement = Payment.all_objects.create(
        account_id=sale.account_id, store_id=sale.store_id, sale=sale, method=method, cash_session=session,
        amount=payment.amount, tendered_amount=payment.amount, installments=installments, nsu=nsu or "",
        authorization_code=authorization_code or "", created_by=user,
    )
    if method.kind == Kind.STORE_CREDIT:
        CustomerCredit.all_objects.create(account_id=sale.account_id, customer=sale.customer,
                                          kind=CustomerCredit.Kind.USAGE, amount=-replacement.amount,
                                          payment=replacement)
    if method.kind == Kind.CASH:
        cash.record_cash_payment(session, replacement, user)
    if method.generates_receivable:
        finance.receivable_from_payment(replacement, user)
    else:
        ledger.payment_received(replacement, user)
    # O troco era do pagamento antigo (dinheiro); o novo é no valor exato.
    sale.change_amount = max(sale.change_amount - payment.change_amount, 0)
    sale.updated_by = user
    sale._change_reason = f"Pagamento {payment.method.name} → {method.name}: {reason}"
    sale.save(update_fields=["change_amount", "updated_by", "updated_at"])
    return replacement
