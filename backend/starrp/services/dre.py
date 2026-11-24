"""DRE gerencial (regime de competência) do período.

    Receita bruta de vendas         (soma dos itens, já com promoção)
  + Frete cobrado
  − Descontos e cupons
  − Devoluções
  + Serviços e outras receitas      (títulos a receber lançados à mão, emitidos no período,
                                     e entradas avulsas com categoria de receita)
  = Receita líquida
  − CMV (custo médio no momento da venda; devolução que volta ao estoque estorna)
  = Lucro bruto
  − Taxas de meios de pagamento     (forma de pagamento × % da adquirente)
  − Comissões
  ± Diferenças de caixa (quebra/sobra nos fechamentos)
  − Despesas por categoria          (títulos a pagar emitidos no período + saídas
                                     avulsas sem título, exceto as automáticas)
  = Resultado operacional

Parte do MESMO recorte de vendas do painel (`reports.completed_sales`): os
números de telas diferentes não podem discordar.
"""
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value

from starrp.models import (
    CashSession, Commission, FinancialCategory, FinancialTitle, FinancialTransaction, Payment, SaleItem, SaleReturn,
    SaleReturnItem, TitleStatus,
)
from starrp.services.reports import completed_sales, period
from starrp.core.tenant import get_allowed_store_ids
from starrp.services.store_access import scope_to_allowed

ZERO = Decimal("0")
AUTOMATIC = {"sales", "card_fees", "commissions", "suppliers"}


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def _scoped(qs, store, field="store"):
    return qs.filter(**{field: store}) if store is not None else scope_to_allowed(qs, field)


def _cost(prefix=""):
    return ExpressionWrapper(F(f"{prefix}unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18,
                                                                                                 decimal_places=4))


def _direct(account, store, kind, start, end):
    """Lançamentos avulsos do período (sem título, venda, caixa, transferência ou estorno). Avulso de
    cliente/fornecedor SEM categoria é crédito/adiantamento: não é receita nem despesa."""
    qs = FinancialTransaction.all_objects.filter(
        account=account, kind=kind, date__range=(start.date(), end.date()),
        deleted_at__isnull=True, installment__isnull=True, sale__isnull=True, cash_session__isnull=True,
        transfer_pair__isnull=True, reversal_of__isnull=True,
    ).exclude(category__system_key__in=AUTOMATIC).exclude(
        Q(category__isnull=True) & (Q(customer__isnull=False) | Q(supplier__isnull=False)))
    if store is not None:  # contas da rede (sem filial) valem para todas as filiais
        return qs.filter(Q(financial_account__store=store) | Q(financial_account__store__isnull=True))
    allowed = get_allowed_store_ids()
    return qs if allowed is None else qs.filter(Q(financial_account__store__in=allowed) | Q(financial_account__store__isnull=True))


def _other_revenue(account, store, start, end):
    """Receita que não é venda do PDV: serviços cobrados por título/boleto e entradas avulsas de receita."""
    titles = _scoped(FinancialTitle.all_objects.filter(
        account=account, kind=FinancialTitle.Kind.RECEIVABLE, issue_date__range=(start.date(), end.date()),
        deleted_at__isnull=True, sale__isnull=True, payment__isnull=True).exclude(status=TitleStatus.CANCELLED), store)
    direct = _direct(account, store, FinancialTransaction.Kind.IN, start, end).filter(
        category__kind=FinancialCategory.Kind.INCOME)
    lines = {}
    for qs, field in ((titles, "total"), (direct, "amount")):
        for row in qs.values("category__name").annotate(total=Sum(field)):
            name = row["category__name"] or "Sem categoria"
            lines[name] = lines.get(name, ZERO) + row["total"]
    return sorted(({"category": k, "amount": v} for k, v in lines.items()), key=lambda r: -r["amount"])


def _expenses(account, store, start, end):
    titles = _scoped(FinancialTitle.all_objects.filter(
        account=account, kind=FinancialTitle.Kind.PAYABLE, issue_date__range=(start.date(), end.date()),
        deleted_at__isnull=True).exclude(status=TitleStatus.CANCELLED), store)
    direct = _direct(account, store, FinancialTransaction.Kind.OUT, start, end)
    lines = {}
    for qs, field in ((titles, "total"), (direct, "amount")):
        for row in qs.values("category__name").annotate(total=Sum(field)):
            name = row["category__name"] or "Sem categoria"
            lines[name] = lines.get(name, ZERO) + row["total"]
    return sorted(({"category": k, "amount": v} for k, v in lines.items()), key=lambda r: -r["amount"])


def build(account, store, params):
    start, end = period(params)
    sales = completed_sales(account, store, params)
    items = SaleItem.all_objects.filter(sale__in=sales, status=SaleItem.Status.ACTIVE)
    returns = _scoped(SaleReturn.all_objects.filter(account=account, status=SaleReturn.Status.COMPLETED,
                                                    completed_at__range=(start, end)), store)
    restocked = SaleReturnItem.all_objects.filter(sale_return__in=returns, restock=True)

    gross = _sum(sales, "subtotal")
    freight = _sum(sales, "freight")
    discounts = _sum(sales, "discount") + _sum(sales, "coupon_discount")
    returned = _sum(returns, "total")
    other = _other_revenue(account, store, start, end)
    other_total = sum((line["amount"] for line in other), ZERO)
    net_revenue = gross + freight - discounts - returned + other_total
    cmv = _sum(items, _cost()) - _sum(restocked, _cost("sale_item__"))
    gross_profit = net_revenue - cmv

    payments = Payment.all_objects.filter(sale__in=sales, status=Payment.Status.APPROVED)
    # × 0,01 e não ÷ 100: no SQLite, valor inteiro (180.00 gravado como 180) faria divisão inteira.
    card_fees = _sum(payments, ExpressionWrapper(F("amount") * F("method__fee_percent") * Value(Decimal("0.01")),
                                                 output_field=DecimalField(max_digits=18, decimal_places=4)))
    commissions = _sum(_scoped(Commission.all_objects.filter(account=account, created_at__range=(start, end))
                               .exclude(status=Commission.Status.CANCELLED), store), "amount")
    cash_diff = _sum(_scoped(CashSession.all_objects.filter(account=account, status=CashSession.Status.CLOSED,
                                                            closed_at__range=(start, end)), store), "difference")
    expenses = _expenses(account, store, start, end)
    expenses_total = sum((line["amount"] for line in expenses), ZERO)
    result = gross_profit - card_fees - commissions + cash_diff - expenses_total

    def pct(value):
        return (value / net_revenue * 100).quantize(Decimal("0.01")) if net_revenue else ZERO

    return {
        "period": {"from": start.date(), "to": end.date()},
        "gross_revenue": gross, "freight": freight, "discounts": discounts, "returns": returned,
        "other_revenue": other, "other_revenue_total": other_total,
        "net_revenue": net_revenue, "cmv": cmv, "gross_profit": gross_profit, "gross_margin_percent": pct(gross_profit),
        "card_fees": card_fees, "commissions": commissions, "cash_differences": cash_diff,
        "expenses": expenses, "expenses_total": expenses_total,
        "operating_result": result, "operating_margin_percent": pct(result),
    }
