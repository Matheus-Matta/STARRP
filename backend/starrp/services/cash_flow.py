"""Fluxo de caixa (regime de caixa): o que entrou e saiu das contas, e o que vai vencer.

- realizado: lançamentos (`FinancialTransaction`) do período, por dia, com
  saldo inicial e final das contas visíveis;
- previsto: parcelas em aberto por vencimento (a receber e a pagar);
- saldos por conta e vencimentos (atrasado, 7, 30 e mais de 30 dias).
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from starrp.core.tenant import get_allowed_store_ids
from starrp.models import FinancialAccount, FinancialTitle, FinancialTransaction, Installment, TitleStatus
from starrp.services.reports import period

ZERO = Decimal("0")
IN, OUT = FinancialTransaction.Kind.IN, FinancialTransaction.Kind.OUT
OPEN = [TitleStatus.OPEN, TitleStatus.PARTIAL]


def visible_accounts(account, store):
    """Contas da loja + as da rede (sem loja). Sem loja ativa: as das lojas permitidas.
    Conta explícita (e não o contexto), para funcionar também fora de requisição."""
    qs = FinancialAccount.all_objects.filter(account=account, deleted_at__isnull=True)
    if store is not None:
        return qs.filter(Q(store=store) | Q(store__isnull=True))
    allowed = get_allowed_store_ids()
    return qs if allowed is None else qs.filter(Q(store__in=allowed) | Q(store__isnull=True))


def _net(qs):
    agg = qs.aggregate(i=Coalesce(Sum("amount", filter=Q(kind=IN)), ZERO),
                       o=Coalesce(Sum("amount", filter=Q(kind=OUT)), ZERO))
    return agg["i"] - agg["o"]


def balances(account, store, params=None):
    rows = []
    for acc in visible_accounts(account, store):
        txs = FinancialTransaction.all_objects.filter(financial_account=acc, deleted_at__isnull=True)
        rows.append({"id": str(acc.pk), "name": acc.name, "kind": acc.kind,
                     "balance": acc.opening_balance + _net(txs)})
    return {"accounts": rows, "total": sum((r["balance"] for r in rows), ZERO)}


def statement(financial_account, params):
    """Extrato de uma conta com saldo corrido."""
    start, end = period(params)
    txs = FinancialTransaction.all_objects.filter(financial_account=financial_account, deleted_at__isnull=True)
    running = financial_account.opening_balance + _net(txs.filter(date__lt=start.date()))
    opening, lines = running, []
    for tx in txs.filter(date__range=(start.date(), end.date())).select_related("category").order_by("date",
                                                                                                    "created_at"):
        running += tx.amount if tx.kind == IN else -tx.amount
        lines.append({"date": tx.date, "description": tx.description, "kind": tx.kind, "amount": tx.amount,
                      "category": tx.category.name if tx.category else "", "balance": running})
    return {"account": financial_account.name, "opening_balance": opening, "closing_balance": running,
            "lines": lines}


def _installments(account, store):
    qs = Installment.all_objects.filter(account=account, status__in=OPEN, deleted_at__isnull=True,
                                        title__deleted_at__isnull=True)
    return qs.filter(title__store=store) if store is not None else qs


def build(account, store, params):
    start, end = period(params)
    accounts = visible_accounts(account, store)
    txs = FinancialTransaction.all_objects.filter(financial_account__in=accounts, deleted_at__isnull=True)
    opening = sum((a.opening_balance for a in accounts), ZERO) + _net(txs.filter(date__lt=start.date()))
    in_period = txs.filter(date__range=(start.date(), end.date()))
    days = (in_period.values("date").annotate(inflow=Coalesce(Sum("amount", filter=Q(kind=IN)), ZERO),
                                              outflow=Coalesce(Sum("amount", filter=Q(kind=OUT)), ZERO))
            .order_by("date"))
    by_category = (in_period.values("kind", "category__name").annotate(total=Sum("amount")).order_by("kind",
                                                                                                   "-total"))
    forecast = (_installments(account, store).filter(due_date__range=(start.date(), end.date()))
                .values("title__kind").annotate(total=Sum("amount"), paid=Sum("paid_amount")))
    return {
        "period": {"from": start.date(), "to": end.date()},
        "opening_balance": opening,
        "inflow": sum((d["inflow"] for d in days), ZERO),
        "outflow": sum((d["outflow"] for d in days), ZERO),
        "closing_balance": opening + _net(in_period),
        "by_day": list(days),
        "by_category": [{**row, "category__name": row["category__name"] or "Sem categoria"} for row in by_category],
        "forecast": {row["title__kind"]: row["total"] - row["paid"] for row in forecast},
    }


def aging(account, store, params=None):
    """Vencimentos em aberto por faixa, a receber e a pagar."""
    today = timezone.localdate()
    buckets = {"overdue": Q(due_date__lt=today), "next_7_days": Q(due_date__range=(today, today + timedelta(days=7))),
               "next_30_days": Q(due_date__range=(today + timedelta(days=8), today + timedelta(days=30))),
               "later": Q(due_date__gt=today + timedelta(days=30))}
    result = {}
    for kind in (FinancialTitle.Kind.RECEIVABLE, FinancialTitle.Kind.PAYABLE):
        qs = _installments(account, store).filter(title__kind=kind)
        result[kind] = {name: (qs.filter(q).aggregate(t=Coalesce(Sum("amount"), ZERO), p=Coalesce(
            Sum("paid_amount"), ZERO)) or {}) for name, q in buckets.items()}
        result[kind] = {name: v["t"] - v["p"] for name, v in result[kind].items()}
    return result
