"""Lançamentos automáticos do financeiro: o dinheiro que se move por causa da operação.

Caixa (o cofre da loja é a conta):
  abertura  → SAI do cofre o troco inicial;   sangria    → ENTRA no cofre;
  suprimento → SAI do cofre;                  fechamento → ENTRA no cofre o CONTADO.
  Saldo do cofre no fim = vendas em dinheiro − devoluções + diferença do caixa.
Venda:
  PIX/débito/vale (sem prazo) → ENTRA na conta da forma de pagamento na hora,
  e a taxa da adquirente SAI como despesa. Crediário/boleto/cartão a prazo
  viram título a receber (`services.finance`), não lançamento.
Todo lançamento tem `source_key`: reenviar o mesmo evento não lança de novo.
Nada se apaga: cancelar gera lançamento inverso (`reversal_of`).
"""
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.models import CashMovement, FinancialCategory, FinancialTransaction, PaymentMethod
from starrp.services.finance_setup import vault_for

IN, OUT = FinancialTransaction.Kind.IN, FinancialTransaction.Kind.OUT
CENTS = Decimal("0.01")


def category(account_id, key):
    return FinancialCategory.all_objects.filter(account_id=account_id, system_key=key, deleted_at__isnull=True).first()


def post(financial_account, kind, amount, *, description, category_key=None, source_key="", date=None, user=None,
         **links):
    amount = Decimal(amount).quantize(CENTS)
    if amount <= 0:
        return None
    if source_key:
        existing = FinancialTransaction.all_objects.filter(account_id=financial_account.account_id,
                                                           source_key=source_key, deleted_at__isnull=True).first()
        if existing is not None:
            return existing
    return FinancialTransaction.all_objects.create(
        account_id=financial_account.account_id, financial_account=financial_account, kind=kind, amount=amount,
        date=date or timezone.localdate(), description=description[:255], source_key=source_key,
        category=category(financial_account.account_id, category_key) if category_key else None,
        operator=user, created_by=user, **links,
    )


def reverse(tx, *, description="", user=None):
    if tx.reversals.exists():
        return tx.reversals.first()
    return FinancialTransaction.all_objects.create(
        account_id=tx.account_id, financial_account=tx.financial_account, kind=OUT if tx.kind == IN else IN,
        amount=tx.amount, date=timezone.localdate(), description=(description or f"Estorno: {tx.description}")[:255],
        category=tx.category, reversal_of=tx, sale=tx.sale, payment=tx.payment, cash_session=tx.cash_session,
        operator=user, created_by=user,
    )


@transaction.atomic
def transfer(source, target, amount, *, description, user=None, date=None):
    if source.pk == target.pk:
        raise BusinessError("Escolha contas diferentes para a transferência.")
    pair = uuid.uuid4()
    out = post(source, OUT, amount, description=f"Transferência para {target.name}: {description}", user=user,
               date=date, transfer_pair=pair)
    post(target, IN, amount, description=f"Transferência de {source.name}: {description}", user=user, date=date,
         transfer_pair=pair)
    return out


# ── Caixa ─────────────────────────────────────────────────────────────────────

def session_opened(session):
    post(vault_for(session.store), OUT, session.opening_amount, date=session.opened_at.date(),
         description=f"Troco de abertura - {session.register.name}", source_key=f"cash_open:{session.pk}",
         cash_session=session, user=session.opened_by)


def session_movement(movement):
    if movement.status != CashMovement.Status.APPROVED:
        return
    kinds = {CashMovement.Kind.WITHDRAWAL: (IN, "Sangria"), CashMovement.Kind.SUPPLY: (OUT, "Suprimento")}
    if movement.kind not in kinds:
        return
    kind, label = kinds[movement.kind]
    post(vault_for(movement.session.store), kind, movement.amount, description=f"{label} - {movement.reason}",
         source_key=f"cash_movement:{movement.pk}", cash_session=movement.session, user=movement.operator)


def session_closed(session):
    post(vault_for(session.store), IN, session.counted_amount or 0, date=(session.closed_at or timezone.now()).date(),
         description=f"Fechamento - {session.register.name}", source_key=f"cash_close:{session.pk}",
         cash_session=session, user=session.closed_by)


# ── Venda ─────────────────────────────────────────────────────────────────────

NO_LEDGER = {PaymentMethod.Kind.CASH, PaymentMethod.Kind.STORE_CREDIT}


def sale_completed(sale, user=None):
    for payment in sale.payments.filter(status="approved").select_related("method__financial_account"):
        method = payment.method
        if method.kind in NO_LEDGER or method.generates_receivable or method.financial_account is None:
            continue
        account = method.financial_account
        post(account, IN, payment.amount, description=f"Venda {sale.number} - {method.name}", category_key="sales",
             source_key=f"payment:{payment.pk}", sale=sale, payment=payment, user=user)
        fee = payment.amount * method.fee_percent / 100
        post(account, OUT, fee, description=f"Taxa {method.name} - venda {sale.number}", category_key="card_fees",
             source_key=f"payment_fee:{payment.pk}", sale=sale, payment=payment, user=user)


def sale_cancelled(sale, user=None):
    for tx in FinancialTransaction.all_objects.filter(sale=sale, reversal_of__isnull=True, deleted_at__isnull=True):
        reverse(tx, description=f"Cancelamento da venda {sale.number}: {tx.description}", user=user)


def refund_to_original(sale_return, user=None):
    """Devolução "na forma original": sai da conta onde o pagamento entrou."""
    payment = sale_return.sale.payments.filter(status="approved").exclude(
        method__kind__in=NO_LEDGER).select_related("method__financial_account").first()
    if payment is None or payment.method.financial_account is None:
        return None
    return post(payment.method.financial_account, OUT, sale_return.total, category_key="sales",
                description=f"Estorno da devolução {sale_return.number} (venda {sale_return.sale.number})",
                source_key=f"return_refund:{sale_return.pk}", sale=sale_return.sale, payment=payment, user=user)
