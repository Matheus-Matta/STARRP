"""Financeiro: títulos a pagar/receber, parcelas e baixas.

Status de título e parcela são DERIVADOS do pago; só este módulo os grava.
"""
import calendar
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import FinancialTitle, FinancialTransaction, Installment, PaymentMethod, TitleStatus

CENTS = Decimal("0.01")


def add_months(day, months):
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def split(total, count):
    """Parcelas que somam exatamente o total (o centavo que sobra vai na 1ª)."""
    base = (Decimal(total) / count).quantize(CENTS)
    parts = [base] * count
    parts[0] += Decimal(total) - base * count
    return parts


@transaction.atomic
def create_title(*, store, kind, description, total, installments=1, first_due=None, interval_days=None,
                 customer=None, supplier=None, user=None, category_key=None, **origin):
    today = timezone.localdate()
    if category_key and "category" not in origin:
        from starrp.services.ledger import category

        origin["category"] = category(store.account_id, category_key)
    first_due = first_due or today
    title = FinancialTitle.all_objects.create(
        account_id=store.account_id, store=store, kind=kind, description=description, total=total,
        issue_date=today, customer=customer, supplier=supplier, created_by=user, **origin,
    )
    for number, amount in enumerate(split(total, installments), start=1):
        due = first_due + timedelta(days=interval_days * (number - 1)) if interval_days else add_months(
            first_due, number - 1
        )
        Installment.all_objects.create(
            account_id=store.account_id, title=title, number=number, due_date=due, amount=amount, created_by=user
        )
    return title


def receivable_from_payment(payment, user=None):
    """Crediário/boleto: o cliente deve. Cartão D+N: a adquirente deve."""
    method = payment.method
    sale = payment.sale
    if method.kind in (PaymentMethod.Kind.INSTALLMENT_PLAN, PaymentMethod.Kind.BANK_SLIP):
        if sale.customer_id is None:
            raise BusinessError("Venda a prazo exige cliente identificado.", code="customer_required")
        return create_title(
            store=sale.store, kind=FinancialTitle.Kind.RECEIVABLE, description=f"Venda {sale.number} - {method.name}",
            total=payment.amount, installments=payment.installments or 1,
            first_due=add_months(timezone.localdate(), 1), customer=sale.customer, user=user,
            sale=sale, payment=payment, category_key="sales",
        )
    if method.settlement_days:
        net = (payment.amount * (100 - method.fee_percent) / 100).quantize(CENTS)
        return create_title(
            store=sale.store, kind=FinancialTitle.Kind.RECEIVABLE, description=f"Venda {sale.number} - {method.name}",
            total=net, installments=payment.installments or 1,
            first_due=timezone.localdate() + timedelta(days=method.settlement_days),
            interval_days=30, user=user, sale=sale, payment=payment, category_key="sales",
        )
    return None


def open_receivables(customer):
    total = Installment.all_objects.filter(
        title__customer=customer, title__kind=FinancialTitle.Kind.RECEIVABLE, deleted_at__isnull=True,
        status__in=[TitleStatus.OPEN, TitleStatus.PARTIAL],
    ).aggregate(t=Sum("amount"), p=Sum("paid_amount"))
    return (total["t"] or Decimal("0")) - (total["p"] or Decimal("0"))


def _refresh_title(title):
    parts = list(title.installments.filter(deleted_at__isnull=True))
    if all(p.status == TitleStatus.CANCELLED for p in parts):
        title.status = TitleStatus.CANCELLED
    elif all(p.status in (TitleStatus.PAID, TitleStatus.CANCELLED) for p in parts):
        title.status = TitleStatus.PAID
    elif any(p.paid_amount > 0 for p in parts):
        title.status = TitleStatus.PARTIAL
    else:
        title.status = TitleStatus.OPEN
    title.save(update_fields=["status", "updated_at"])


@transaction.atomic
def settle(installment, financial_account, amount, user, *, interest=0, fine=0, discount=0, date=None):
    part = Installment.all_objects.select_for_update().get(pk=installment.pk)
    if part.status in (TitleStatus.PAID, TitleStatus.CANCELLED):
        raise StateConflict("Parcela já quitada ou cancelada.")
    part.interest += Decimal(interest)
    part.fine += Decimal(fine)
    part.discount += Decimal(discount)
    amount = Decimal(amount)
    if amount <= 0 or amount > part.balance:
        raise BusinessError(f"Valor deve estar entre 0,01 e {part.balance}.")
    part.paid_amount += amount
    part.paid_at = date or timezone.localdate()
    part.status = TitleStatus.PAID if part.balance <= 0 else TitleStatus.PARTIAL
    part.save()
    title = part.title
    FinancialTransaction.all_objects.create(
        account_id=part.account_id, financial_account=financial_account,
        kind=FinancialTransaction.Kind.IN if title.kind == FinancialTitle.Kind.RECEIVABLE else FinancialTransaction.Kind.OUT,
        amount=amount, date=part.paid_at, description=f"Baixa: {title.description} ({part.number})",
        category=title.category, installment=part, operator=user, created_by=user,
    )
    _refresh_title(title)
    return part


@transaction.atomic
def cancel_titles_of_sale(sale):
    for title in FinancialTitle.all_objects.filter(sale=sale, deleted_at__isnull=True):
        if title.installments.filter(paid_amount__gt=0).exists():
            raise StateConflict("A venda tem parcelas já recebidas; estorne-as no financeiro antes.")
        title.installments.update(status=TitleStatus.CANCELLED)
        _refresh_title(title)
