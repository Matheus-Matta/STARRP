"""Agregações de relatório. Todas partem de UM recorte de vendas concluídas
(`completed_sales`), para os números de telas diferentes nunca discordarem.

Sem loja ativa, o recorte é a REDE PERMITIDA ao usuário — nunca a conta
inteira para quem é de filial (`scope_to_allowed`)."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from starrp.models import Commission, Payment, Sale, SaleItem, SaleReturn
from starrp.services.store_access import scope_to_allowed


def period(params):
    today = timezone.localdate()
    start = params.get("date_from") or str(today - timedelta(days=29))
    end = params.get("date_to") or str(today)
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(datetime.fromisoformat(start).date(), time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(datetime.fromisoformat(end).date(), time.max), tz)
    return start_dt, end_dt


def completed_sales(account, store, params):
    start, end = period(params)
    qs = Sale.all_objects.filter(account=account, status=Sale.Status.COMPLETED, completed_at__range=(start, end))
    qs = qs.filter(store=store) if store is not None else scope_to_allowed(qs)
    if params.get("seller"):
        qs = qs.filter(seller_id=params["seller"])
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


def _margin(sales):
    cost = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18, decimal_places=4))
    agg = _items(sales).aggregate(revenue=Sum("total"), cost=Sum(cost))
    return (agg["revenue"] or 0) - (agg["cost"] or 0)


def by_day(account, store, params):
    rows = (completed_sales(account, store, params).annotate(day=TruncDate("completed_at")).values("day")
            .annotate(count=Count("id"), revenue=Sum("total")).order_by("day"))
    return list(rows)


def top_products(account, store, params, limit=50):
    cost = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18, decimal_places=4))
    rows = (_items(completed_sales(account, store, params)).values("variant_id", "description", "sku")
            # `sold_quantity`, e não `quantity`: o nome do campo seria sombreado e o custo
            # passaria a multiplicar por uma soma (agregado dentro de agregado).
            .annotate(sold_quantity=Sum("quantity"), revenue=Sum("total"), cost=Sum(cost)).order_by("-revenue")[:limit])
    return [{**row, "margin": (row["revenue"] or 0) - (row["cost"] or 0)} for row in rows]


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
        "open_sales": scope_to_allowed(Sale.all_objects.filter(account=account, status=Sale.Status.OPEN).filter(
            Q(store=store) if store else Q())).count(),
    }
