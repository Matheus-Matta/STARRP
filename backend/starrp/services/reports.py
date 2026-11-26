"""Agregações de relatório. Todas partem de UM recorte de vendas concluídas
(`completed_sales`), para os números de telas diferentes nunca discordarem.

Sem loja ativa, o recorte é a REDE PERMITIDA ao usuário — nunca a conta
inteira para quem é de filial (`scope_to_allowed`)."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, FloatField, Q, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, NullIf, TruncDate
from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.models import Commission, Payment, Sale, SaleItem, SaleReturn
from starrp.services.store_access import scope_own_sales, scope_to_allowed


def period(params):
    today = timezone.localdate()
    start = params.get("date_from") or str(today - timedelta(days=29))
    end = params.get("date_to") or str(today)
    tz = timezone.get_current_timezone()
    try:
        first, last = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
        start_dt = timezone.make_aware(datetime.combine(first, time.min), tz)
        end_dt = timezone.make_aware(datetime.combine(last, time.max), tz)
        if first.year < 1970 or last.year > 2200 or last < first:
            raise ValueError
    except (ValueError, OverflowError):
        raise BusinessError("Período inválido.", code="period_invalid") from None
    return start_dt, end_dt


def int_or_zero(value):
    """Id numérico vindo da URL; lixo não acha nada (em vez de erro 500, B-07)."""
    return int(value) if str(value).isascii() and str(value).isdigit() and len(str(value)) < 15 else 0


def completed_sales(account, store, params):
    start, end = period(params)
    qs = Sale.all_objects.filter(account=account, status=Sale.Status.COMPLETED, completed_at__range=(start, end))
    qs = qs.filter(store=store) if store is not None else scope_to_allowed(qs)
    qs = scope_own_sales(qs)  # vendedor (sem `sales.view_all`): só as vendas dele
    if params.get("seller"):
        qs = qs.filter(seller_id=int_or_zero(params["seller"]))
    return qs


def summary(account, store, params):
    sales = completed_sales(account, store, params)
    totals = sales.aggregate(count=Count("id"), revenue=Sum("total"), discounts=Sum("discount"),
                             coupons=Sum("coupon_discount"))
    count, revenue = totals["count"] or 0, totals["revenue"] or Decimal("0")
    start, end = period(params)
    returns = SaleReturn.all_objects.filter(account=account, status=SaleReturn.Status.COMPLETED,
                                            completed_at__range=(start, end))
    cancelled = Sale.all_objects.filter(account=account, status=Sale.Status.CANCELLED,
                                        cancelled_at__range=(start, end))
    if store is not None:
        returns, cancelled = returns.filter(store=store), cancelled.filter(store=store)
    else:
        returns, cancelled = scope_to_allowed(returns), scope_to_allowed(cancelled)
    returns, cancelled = scope_own_sales(returns), scope_own_sales(cancelled)
    if params.get("seller"):
        seller = int_or_zero(params["seller"])
        returns, cancelled = returns.filter(sale__seller_id=seller), cancelled.filter(seller_id=seller)
    return {
        "sales_count": count,
        "revenue": revenue,
        "average_ticket": (revenue / count).quantize(Decimal("0.01")) if count else Decimal("0"),
        "discounts": (totals["discounts"] or 0) + (totals["coupons"] or 0),
        "returns_total": returns.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "cancelled_count": cancelled.count(),
        "gross_margin": _margin(sales),
    }


def _items(sales):
    return SaleItem.all_objects.filter(sale__in=sales, status=SaleItem.Status.ACTIVE)


#: Taxa da adquirente de cada pagamento, pela taxa do DIA dele (R5-14). × 0,01: no SQLite, ÷ 100 seria divisão inteira.
FEE = ExpressionWrapper(F("amount") * Coalesce(F("fee_percent"), F("method__fee_percent")) * Value(Decimal("0.01")),
                        output_field=DecimalField(max_digits=18, decimal_places=4))
#: Desconto do cabeçalho que pesa nos produtos (cupom de frete grátis abate o frete).
_HEADER = F("sale__discount") + Case(When(sale__coupon__kind="free_shipping", then=Value(Decimal("0"))),
                                     default=F("sale__coupon_discount"), output_field=DecimalField())
#: O total do item já com a parte dele no desconto da venda: a mesma receita da DRE.
NET_ITEM = ExpressionWrapper(
    Cast(F("total"), FloatField()) * (Value(1.0) - Cast(_HEADER, FloatField()) / NullIf(Cast(F("sale__subtotal"), FloatField()),
                                                                                       Value(0.0))),
    output_field=FloatField())


#: Receita líquida somada dos itens (agregado). Sai em float: `money` arredonda.
NET = Sum(Coalesce(NET_ITEM, Value(0.0)))
ITEM_COST = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18, decimal_places=4))


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def net_revenue(items):
    return money(items.aggregate(t=NET)["t"])


def net_by(items, *keys):
    """{chave: (receita líquida, custo)} dos itens agrupados (a MESMA receita em toda tela, R6-01)."""
    out = {}
    for row in items.order_by().values(*keys).annotate(_net=NET, _cost=Sum(ITEM_COST)):
        key = tuple(row[k] for k in keys)
        out[key[0] if len(key) == 1 else key] = (money(row["_net"]), row["_cost"] or Decimal("0"))
    return out


def margin_of(items):
    return net_revenue(items) - (items.aggregate(t=Sum(ITEM_COST))["t"] or Decimal("0"))


def _margin(sales):
    return margin_of(_items(sales))


def by_day(account, store, params):
    rows = (completed_sales(account, store, params).annotate(day=TruncDate("completed_at")).values("day")
            .annotate(count=Count("id"), revenue=Sum("total")).order_by("day"))
    return list(rows)


def top_products(account, store, params, limit=50):
    rows = (_items(completed_sales(account, store, params)).values("variant_id", "description", "sku")
            # `sold_quantity`, e não `quantity`: o nome do campo seria sombreado e o custo
            # passaria a multiplicar por uma soma (agregado dentro de agregado).
            .annotate(sold_quantity=Sum("quantity"), revenue=NET, cost=Sum(ITEM_COST)).order_by("-revenue")[:limit])
    return [{**row, "revenue": money(row["revenue"]), "margin": money(row["revenue"]) - (row["cost"] or 0)} for row in rows]


def by_payment_method(account, store, params):
    payments = Payment.all_objects.filter(sale__in=completed_sales(account, store, params),
                                          status=Payment.Status.APPROVED)
    return list(payments.values("method__name", "method__kind").annotate(count=Count("id"), total=Sum("amount"))
                .order_by("-total"))


def by_seller(account, store, params):
    sales = completed_sales(account, store, params)
    rows = (sales.filter(seller__isnull=False).values("seller_id", "seller__first_name", "seller__username")
            .annotate(count=Count("id"), revenue=Sum("total")).order_by("-revenue"))
    commission = {
        row["seller_id"]: row["total"] for row in Commission.all_objects.filter(sale__in=sales).exclude(
            status=Commission.Status.CANCELLED).values("seller_id").annotate(total=Sum("amount"))
    }
    return [{**row, "commission": commission.get(row["seller_id"], Decimal("0"))} for row in rows]


def dashboard(account, store, params):
    return {
        "summary": summary(account, store, params),
        "by_day": by_day(account, store, params),
        "by_payment_method": by_payment_method(account, store, params),
        "top_products": top_products(account, store, params, limit=10),
        "by_seller": by_seller(account, store, params),
        "open_sales": scope_own_sales(scope_to_allowed(Sale.all_objects.filter(account=account, status=Sale.Status.OPEN)
                                                       .filter(Q(store=store) if store else Q()))).count(),
    }
