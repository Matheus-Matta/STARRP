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


@transaction.atomic
def reverse(tx, *, description="", user=None):
    # Travado: dois estornos ao mesmo tempo passavam os dois na conferência.
    tx = FinancialTransaction.all_objects.select_for_update().get(pk=tx.pk)
    if tx.transfer_pair:  # as DUAS pernas (R2-19): estornar uma só cria ou some com dinheiro
        others = FinancialTransaction.all_objects.select_for_update().filter(
            account_id=tx.account_id, transfer_pair=tx.transfer_pair, reversal_of__isnull=True,
            deleted_at__isnull=True).exclude(pk=tx.pk)
        for other in others:
            _reverse_one(other, description=description, user=user)
    reversal = _reverse_one(tx, description=description, user=user)
    _check_credit(tx)
    if tx.source_key.startswith("commission_payout:"):
        _reopen_commissions(tx)
    return reversal


def _reopen_commissions(tx):
    """Estornou o pagamento da comissão: ela volta a ficar a pagar (R7-N7)."""
    from starrp.models import Commission

    reopened = Commission.all_objects.filter(payout=tx, status=Commission.Status.PAID).update(
        status=Commission.Status.PENDING, paid_at=None, payout=None)
    if not reopened:
        raise BusinessError("Este pagamento de comissão é anterior ao vínculo com as comissões: não dá para reabri-las. "
                            "Faça o acerto por um lançamento avulso.", code="commission_payout_old")


def _check_credit(tx):
    """Estornar a entrada que virou crédito JÁ USADO deixava a parcela paga sem dinheiro nenhum (R5-03)."""
    from starrp.services import finance

    party = {"customer": tx.customer} if tx.customer_id else {"supplier": tx.supplier} if tx.supplier_id else None
    if party is None or tx.installment_id or tx.category_id:
        return
    if tx.kind != (IN if tx.customer_id else OUT):
        return  # só a entrada que DEU crédito; estornar uma saída devolve crédito
    (owner,) = party.values()
    type(owner).all_objects.select_for_update().filter(pk=owner.pk).first()
    if finance.party_credit(**party) < 0:
        raise BusinessError("O crédito deste lançamento já foi usado numa baixa: desfaça a baixa antes de estornar.",
                            code="credit_used")


def legs(tx):
    """As duas pernas de uma transferência (ou só o lançamento)."""
    if not tx.transfer_pair:
        return [tx]
    return list(FinancialTransaction.all_objects.filter(account_id=tx.account_id, transfer_pair=tx.transfer_pair,
                                                        deleted_at__isnull=True).select_related("financial_account"))


def _reverse_one(tx, *, description="", user=None):
    if tx.reversals.exists():
        return tx.reversals.first()
    return FinancialTransaction.all_objects.create(
        account_id=tx.account_id, financial_account=tx.financial_account, kind=OUT if tx.kind == IN else IN,
        amount=tx.amount, date=timezone.localdate(), description=(description or f"Estorno: {tx.description}")[:255],
        category=tx.category, reversal_of=tx, transfer_pair=tx.transfer_pair, installment=tx.installment, sale=tx.sale,
        payment=tx.payment, cash_session=tx.cash_session,
        customer=tx.customer, supplier=tx.supplier, operator=user, created_by=user,
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
    post(vault_for(session.store), OUT, session.opening_amount, date=timezone.localdate(session.opened_at),
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
    post(vault_for(session.store), IN, session.counted_amount or 0, date=timezone.localdate(session.closed_at),
         description=f"Fechamento - {session.register.name}", source_key=f"cash_close:{session.pk}",
         cash_session=session, user=session.closed_by)


# ── Venda ─────────────────────────────────────────────────────────────────────

NO_LEDGER = {PaymentMethod.Kind.CASH, PaymentMethod.Kind.STORE_CREDIT}


def sale_completed(sale, user=None):
    for payment in sale.payments.filter(status="approved").select_related("method__financial_account"):
        payment_received(payment, user)


def payment_received(payment, user=None):
    """Entrada do pagamento na conta da forma (e a taxa dela). Dinheiro/vale-troca e o que vira
    título a receber não lançam aqui."""
    method, sale = payment.method, payment.sale
    if method.kind in NO_LEDGER or method.generates_receivable or method.financial_account is None:
        return
    account = method.financial_account
    post(account, IN, payment.amount, description=f"Venda {sale.number} - {method.name}", category_key="sales",
         source_key=f"payment:{payment.pk}", sale=sale, payment=payment, user=user)
    fee = payment.amount * payment.fee_rate / 100
    post(account, OUT, fee, description=f"Taxa {method.name} - venda {sale.number}", category_key="card_fees",
         source_key=f"payment_fee:{payment.pk}", sale=sale, payment=payment, user=user)


def payment_undone(payment, description, user=None):
    """Estorna o que `payment_received` lançou para este pagamento."""
    # O reembolso de uma devolução também é ligado ao pagamento, mas não é dele: estorná-lo inflaria o saldo.
    own = FinancialTransaction.all_objects.filter(payment=payment, reversal_of__isnull=True, deleted_at__isnull=True)
    for tx in own.exclude(source_key__startswith="return_refund:"):
        reverse(tx, description=f"{description}: {tx.description}", user=user)


def sale_cancelled(sale, user=None):
    for tx in FinancialTransaction.all_objects.filter(sale=sale, reversal_of__isnull=True, deleted_at__isnull=True):
        reverse(tx, description=f"Cancelamento da venda {sale.number}: {tx.description}", user=user)


def refund_to_original(sale_return, user=None):
    """Devolução "na forma original": sai da conta onde o pagamento entrou."""
    payments = list(sale_return.sale.payments.filter(status="approved").select_related("method__financial_account"))
    # Só há "forma original" quando UM pagamento à vista cobre a devolução. Dinheiro sai pela gaveta, crediário e
    # cartão a prazo se abatem no título, e misto precisa de escolha: antes concluía sem registrar reembolso, ou
    # tirava tudo do primeiro com o título ainda cobrando.
    payment = payments[0] if len(payments) == 1 else next(
        (p for p in payments if p.amount >= sale_return.total and p.method.kind not in NO_LEDGER
         and not p.method.generates_receivable and len({q.method_id for q in payments}) == 1), None)
    if payment is None or payment.method.kind in NO_LEDGER or payment.method.generates_receivable:
        raise BusinessError("Esta venda não tem uma forma única à vista para estornar: devolva em dinheiro ou em "
                            "vale-troca (crediário/cartão a prazo: ajuste as parcelas no financeiro).",
                            code="original_payment_unavailable")
    if payment.method.financial_account is None:
        return None
    return post(payment.method.financial_account, OUT, sale_return.total, category_key="sales",
                description=f"Estorno da devolução {sale_return.number} (venda {sale_return.sale.number})",
                source_key=f"return_refund:{sale_return.pk}", sale=sale_return.sale, payment=payment, user=user)
