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
                                     avulsas sem título, exceto as automáticas e a
                                     compra de mercadoria, que já é o CMV)
  ± Juros, multas e descontos das baixas; − perdas e consumo de estoque
  = Resultado operacional

Parte do MESMO recorte de vendas do painel (`reports.completed_sales`): os
números de telas diferentes não podem discordar.
"""
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum

from starrp.models import (
    CashSession, Commission, FinancialCategory, FinancialTitle, FinancialTransaction, InstallmentSettlement, Payment, SaleItem,
    SaleReturn, SaleReturnItem, StockMovement, TitleStatus,
)
from starrp.services.reports import FEE, completed_sales, period
from starrp.core.tenant import get_allowed_store_ids, get_own_sales_user, set_own_sales_user
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
        transfer_pair__isnull=True, reversal_of__isnull=True, reversals__isnull=True,
    ).exclude(category__system_key="suppliers").exclude(
        Q(category__system_key__in=AUTOMATIC) & ~Q(source_key="")).exclude(
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
    # Mercadoria comprada vira custo quando é VENDIDA (CMV): contar a duplicata também era contar duas vezes (R5-01).
    # Comissão e taxa lançadas à mão contam (as automáticas não geram título).
    titles = titles.exclude(category__system_key="suppliers")
    direct = _direct(account, store, FinancialTransaction.Kind.OUT, start, end)
    lines = {}
    for qs, field in ((titles, "total"), (direct, "amount")):
        for row in qs.values("category__name").annotate(total=Sum(field)):
            name = row["category__name"] or "Sem categoria"
            lines[name] = lines.get(name, ZERO) + row["total"]
    return sorted(({"category": k, "amount": v} for k, v in lines.items()), key=lambda r: -r["amount"])


def _settlements(account, store, start, end):
    """Juros, multa e desconto das baixas do período, cada um na data da SUA baixa (R5-13, R6-06)."""
    parts = _scoped(InstallmentSettlement.all_objects.filter(
        account=account, deleted_at__isnull=True, installment__title__deleted_at__isnull=True,
        date__range=(start.date(), end.date())), store, "installment__title__store")
    out = {}
    for kind in (FinancialTitle.Kind.RECEIVABLE, FinancialTitle.Kind.PAYABLE):
        rows = parts.filter(installment__title__kind=kind)
        out[kind] = (_sum(rows, "interest") + _sum(rows, "fine"), _sum(rows, "discount"))
    return out


LOSS_KINDS = (StockMovement.Kind.LOSS, StockMovement.Kind.EXPIRATION, StockMovement.Kind.CONSUMPTION,
              StockMovement.Kind.ADJUSTMENT, StockMovement.Kind.ASSET_DISPOSAL)


def _stock_losses(account, store, start, end):
    """Perda, vencimento, consumo, baixa e diferença de contagem, pelo custo (a sobra da contagem e o estorno abatem)."""
    moves = _scoped(StockMovement.all_objects.filter(account=account, created_at__range=(start, end)), store,
                    "warehouse__store")
    moves = moves.filter(Q(kind__in=LOSS_KINDS) | Q(kind=StockMovement.Kind.REVERSAL, reversal_of__kind__in=LOSS_KINDS))
    return _sum(moves.filter(quantity__lt=0), "total_cost") - _sum(moves.filter(quantity__gt=0), "total_cost")


def build(account, store, params):
    """Os números da EMPRESA (quem vê o financeiro vê o resultado inteiro): o recorte "só as minhas vendas" do
    vendedor deixaria a receita pela metade com as despesas inteiras (R5-16)."""
    own = get_own_sales_user()
    set_own_sales_user(None)
    try:
        return _build(account, store, params)
    finally:
        set_own_sales_user(own)


def _build(account, store, params):
    start, end = period(params)
    # Só o período: devoluções, despesas e comissões são da empresa; filtrar a venda por vendedor misturava os dois
    # (receita de um, custo de todos) e dava faturamento negativo (R8-01).
    sales = completed_sales(account, store, {k: params.get(k) for k in ("date_from", "date_to")})
    items = SaleItem.all_objects.filter(sale__in=sales, status=SaleItem.Status.ACTIVE)
    returns = _scoped(SaleReturn.all_objects.filter(account=account, status=SaleReturn.Status.COMPLETED,
                                                    completed_at__range=(start, end)), store)
    restocked = SaleReturnItem.all_objects.filter(sale_return__in=returns, restock=True)

    gross = _sum(sales, "subtotal")
    freight = _sum(sales, "freight")
    discounts = _sum(sales, "discount") + _sum(sales, "coupon_discount")
    returned = _sum(returns, "total")
    other = _other_revenue(account, store, start, end)
    settled = _settlements(account, store, start, end)
    received, given = settled[FinancialTitle.Kind.RECEIVABLE]
    paid, obtained = settled[FinancialTitle.Kind.PAYABLE]
    other += [{"category": name, "amount": value} for name, value in (
        ("Juros e multas recebidos", received), ("Descontos obtidos", obtained)) if value]
    other_total = sum((line["amount"] for line in other), ZERO)
    net_revenue = gross + freight - discounts - returned + other_total
    cmv = _sum(items, _cost()) - _sum(restocked, _cost("sale_item__"))
    gross_profit = net_revenue - cmv

    payments = Payment.all_objects.filter(sale__in=sales, status=Payment.Status.APPROVED)
    card_fees = _sum(payments, FEE)
    commissions = _sum(_scoped(Commission.all_objects.filter(account=account, created_at__range=(start, end))
                               .exclude(status=Commission.Status.CANCELLED), store), "amount")
    cash_diff = _sum(_scoped(CashSession.all_objects.filter(account=account, status=CashSession.Status.CLOSED,
                                                            closed_at__range=(start, end)), store), "difference")
    expenses = _expenses(account, store, start, end)
    expenses += [{"category": name, "amount": value} for name, value in (
        ("Juros e multas pagos", paid), ("Descontos concedidos em baixas", given),
        ("Perdas e consumo de estoque", _stock_losses(account, store, start, end))) if value]
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
