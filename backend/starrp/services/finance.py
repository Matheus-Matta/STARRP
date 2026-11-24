"""Financeiro: títulos a pagar/receber, parcelas e baixas.

Status de título e parcela são DERIVADOS do pago; só este módulo os grava.

Crédito de cliente/fornecedor: o que ele pagou além do devido (baixa acima do saldo, ou um
lançamento avulso com a parte) fica como crédito; a baixa seguinte pode usá-lo (`use_credit`),
sem dinheiro novo em conta nenhuma. `party_credit` diz quanto há.
"""
import calendar
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import FinancialTitle, FinancialTransaction, Installment, PaymentMethod, TitleStatus

ZERO = Decimal("0")

CENTS = Decimal("0.01")


def add_months(day, months):
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def due_dates(start, *, frequency="monthly", due_day=None, due_weekday=None):
    """Vencimentos a partir de `start` (inclusive), sem fim: todo mês no `due_day` (31 = último dia;
    vazio = o dia de `start`), toda semana no `due_weekday` (vazio = o de `start`) ou todo dia.
    Passa de um ano para o outro sozinho (10/11, 10/12, 10/01...)."""
    if frequency == "daily":
        day = start
        while True:
            yield day
            day += timedelta(days=1)
    if frequency == "weekly":
        weekday = start.weekday() if due_weekday is None else int(due_weekday)
        day = start + timedelta(days=(weekday - start.weekday()) % 7)
        while True:
            yield day
            day += timedelta(days=7)
    wanted = int(due_day or start.day)
    month = start.replace(day=1)
    while True:
        day = month.replace(day=min(wanted, calendar.monthrange(month.year, month.month)[1]))
        if day >= start:
            yield day
        month = add_months(month, 1)


def late_charges(part, on=None):
    """Multa (uma vez) e juros (% ao mês ÷ 30 por dia de atraso, sobre o principal em aberto) de uma
    parcela vencida, pelos percentuais do título. O que já foi lançado na parcela não se repete."""
    on = on or timezone.localdate()
    title = part.title
    open_principal = max(part.amount - part.discount - (part.paid_amount - part.interest - part.fine), ZERO)
    late = (on - part.due_date).days
    if late <= 0 or open_principal <= 0 or part.status in (TitleStatus.PAID, TitleStatus.CANCELLED):
        return {"days_late": max(late, 0), "fine": ZERO, "interest": ZERO}
    fine = ZERO if part.fine > 0 else (open_principal * title.fine_percent / 100).quantize(CENTS)
    interest = (open_principal * title.interest_percent / 100 / 30 * late).quantize(CENTS) - part.interest
    return {"days_late": late, "fine": fine, "interest": max(interest, ZERO)}


def split(total, count):
    """Parcelas que somam exatamente o total (o centavo que sobra vai na 1ª)."""
    base = (Decimal(total) / count).quantize(CENTS, rounding=ROUND_DOWN)  # p/ cima, R$ 0,15 em 10x dava parcela negativa
    parts = [base] * count
    parts[0] += Decimal(total) - base * count
    return parts


@transaction.atomic
def create_title(*, store, kind, description, total, installments=1, first_due=None, interval_days=None,
                 customer=None, supplier=None, user=None, category_key=None, issue_date=None, frequency=None,
                 due_day=None, due_weekday=None, **origin):
    """Título com as parcelas. Vencimentos: `interval_days` (a cada N dias, legado), ou a frequência
    (todo mês no `due_day`, toda semana no `due_weekday`, todo dia) a partir de `first_due`."""
    today = timezone.localdate()
    if category_key and "category" not in origin:
        from starrp.services.ledger import category

        origin["category"] = category(store.account_id, category_key)
    first_due = first_due or today
    title = FinancialTitle.all_objects.create(
        account_id=store.account_id, store=store, kind=kind, description=description, total=total,
        issue_date=issue_date or today, customer=customer, supplier=supplier, created_by=user,
        frequency=frequency or "monthly", due_day=due_day, due_weekday=due_weekday, **origin,
    )
    dates = due_dates(first_due, frequency=frequency, due_day=due_day, due_weekday=due_weekday) if frequency else None
    for number, amount in enumerate(split(total, installments), start=1):
        if dates is not None:
            due = next(dates)
        elif interval_days:
            due = first_due + timedelta(days=interval_days * (number - 1))
        else:
            due = add_months(first_due, number - 1)
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


def _party(title):
    return {"customer": title.customer} if title.customer_id else {"supplier": title.supplier} if title.supplier_id else None


def party_credit(*, customer=None, supplier=None):
    """Crédito da parte: o que ela pagou (cliente) ou recebeu adiantado (fornecedor) sem título,
    menos o que já foi usado em baixas. Cliente: entradas avulsas; fornecedor: saídas avulsas."""
    if customer is None and supplier is None:
        return ZERO
    if customer is not None:
        txs, kind, parts = Q(customer=customer), FinancialTransaction.Kind.IN, Q(title__customer=customer)
    else:
        txs, kind, parts = Q(supplier=supplier), FinancialTransaction.Kind.OUT, Q(title__supplier=supplier)
    moved = FinancialTransaction.all_objects.filter(txs, installment__isnull=True, deleted_at__isnull=True).aggregate(
        given=Coalesce(Sum("amount", filter=Q(kind=kind)), ZERO),
        back=Coalesce(Sum("amount", filter=~Q(kind=kind)), ZERO))
    used = Installment.all_objects.filter(parts, deleted_at__isnull=True).aggregate(t=Coalesce(Sum("credit_used"), ZERO))["t"]
    return moved["given"] - moved["back"] - used


def party_credits(customer_ids=(), supplier_ids=()):
    """`party_credit` de várias partes de uma vez: {("c", id_cliente) | ("s", id_fornecedor): crédito}.
    Duas consultas agrupadas por tipo de parte, em vez de duas por parte (relatórios com muitas)."""
    result = {}
    for tag, ids, field, kind in (("c", customer_ids, "customer", FinancialTransaction.Kind.IN),
                                  ("s", supplier_ids, "supplier", FinancialTransaction.Kind.OUT)):
        ids = [i for i in ids if i]
        if not ids:
            continue
        credit = dict.fromkeys(ids, ZERO)
        for row in (FinancialTransaction.all_objects.filter(**{f"{field}_id__in": ids}, installment__isnull=True,
                                                             deleted_at__isnull=True)
                    .order_by().values(f"{field}_id")
                    .annotate(given=Coalesce(Sum("amount", filter=Q(kind=kind)), ZERO),
                              back=Coalesce(Sum("amount", filter=~Q(kind=kind)), ZERO))):
            credit[row[f"{field}_id"]] += row["given"] - row["back"]
        for row in (Installment.all_objects.filter(**{f"title__{field}_id__in": ids}, deleted_at__isnull=True)
                    .order_by().values(f"title__{field}_id").annotate(t=Coalesce(Sum("credit_used"), ZERO))):
            credit[row[f"title__{field}_id"]] -= row["t"]
        result.update({(tag, pk): value for pk, value in credit.items()})
    return result


@transaction.atomic
def settle(installment, financial_account, amount, user, *, interest=0, fine=0, discount=0, date=None,
           use_credit=False, allow_excess=False):
    """Baixa da parcela.

    - `use_credit`: paga (até o saldo) com o crédito da parte; o resto, se houver, sai/entra na conta;
    - `allow_excess`: valor acima do saldo quita a parcela e o que passou vira crédito da parte
      (lançamento avulso com o cliente/fornecedor, sem categoria: não é receita nem despesa).
    """
    part = Installment.all_objects.select_for_update().get(pk=installment.pk)
    if part.status in (TitleStatus.PAID, TitleStatus.CANCELLED):
        raise StateConflict("Parcela já quitada ou cancelada.")
    part.interest += Decimal(interest)
    part.fine += Decimal(fine)
    part.discount += Decimal(discount)
    if part.balance < 0:
        # Desconto maior que o saldo: o saldo negativo virava lançamento de valor NEGATIVO na conta.
        raise BusinessError("O desconto não pode ser maior que o saldo da parcela.", code="discount_exceeds_balance")
    title = part.title
    party = _party(title)
    amount = Decimal(amount or 0)
    paid_at = date or timezone.localdate()
    credit = ZERO
    if use_credit:
        if not party:
            raise BusinessError("Este título não tem cliente/fornecedor: não há crédito a usar.")
        # Trava a parte: duas baixas com o MESMO crédito ao mesmo tempo liam o mesmo saldo e as duas usavam.
        (party_obj,) = party.values()
        type(party_obj).all_objects.select_for_update().filter(pk=party_obj.pk).first()
        credit = min(max(party_credit(**party), ZERO), part.balance)
        if credit <= 0:
            raise BusinessError("Não há crédito disponível para esta parte.", code="no_credit")
        part.credit_used += credit
        part.paid_amount += credit
    excess = ZERO
    if amount > part.balance:
        if not (allow_excess and party):
            raise BusinessError(f"Valor deve estar entre 0,01 e {part.balance}.")
        excess = amount - part.balance
    if amount < 0 or (amount == 0 and credit == 0):
        raise BusinessError(f"Valor deve estar entre 0,01 e {part.balance}.")
    if amount > 0 and financial_account is None:
        raise BusinessError("Escolha a conta.")
    in_out = FinancialTransaction.Kind.IN if title.kind == FinancialTitle.Kind.RECEIVABLE else FinancialTransaction.Kind.OUT
    settled = amount - excess
    part.paid_amount += settled
    part.paid_at = paid_at
    part.status = TitleStatus.PAID if part.balance <= 0 else TitleStatus.PARTIAL
    part.save()
    if settled > 0:
        FinancialTransaction.all_objects.create(
            account_id=part.account_id, financial_account=financial_account, kind=in_out,
            amount=settled, date=paid_at, description=f"Baixa: {title.description} ({part.number})",
            category=title.category, installment=part, operator=user, created_by=user,
        )
    if excess > 0:
        FinancialTransaction.all_objects.create(
            account_id=part.account_id, financial_account=financial_account, kind=in_out, amount=excess, date=paid_at,
            description=f"Pago a mais (crédito): {title.description} ({part.number})"[:255], operator=user,
            created_by=user, **party,
        )
    _refresh_title(title)
    return part


@transaction.atomic
def cancel_titles(titles, paid_message):
    """Cancela as parcelas dos títulos; com algo já pago/recebido, recusa (estorne no financeiro antes)."""
    for title in titles.filter(deleted_at__isnull=True).exclude(status=TitleStatus.CANCELLED):
        if title.installments.filter(paid_amount__gt=0).exists():
            raise StateConflict(paid_message, code="title_paid")
        title.installments.update(status=TitleStatus.CANCELLED)
        _refresh_title(title)


def cancel_titles_of_sale(sale):
    cancel_titles(FinancialTitle.all_objects.filter(sale=sale),
                  "A venda tem parcelas já recebidas; estorne-as no financeiro antes.")
