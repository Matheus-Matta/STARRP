"""Relatório de fechamento de caixa (o "Z" do turno).

Responde, num lugar só, as perguntas do fechamento: quanto vendeu e em quê,
o que saiu e entrou na gaveta, quanto deveria ter, quanto tinha, quem abriu,
quem fechou e quem aprovou a diferença — e quanto o turno rendeu de margem.
"""
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce

from starrp.models import CashMovement, CashSession, Payment, Sale, SaleItem
from starrp.services.cash import expected_cash

ZERO = Decimal("0")


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def summary(session):
    sales = Sale.all_objects.filter(cash_session=session)
    completed = sales.filter(status=Sale.Status.COMPLETED)
    cancelled = sales.filter(status=Sale.Status.CANCELLED)
    payments = Payment.all_objects.filter(cash_session=session, status=Payment.Status.APPROVED)
    movements = session.movements.filter(status=CashMovement.Status.APPROVED)
    cost = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18, decimal_places=4))
    items = SaleItem.all_objects.filter(sale__in=completed, status=SaleItem.Status.ACTIVE).aggregate(
        revenue=Coalesce(Sum("total"), ZERO), cost=Coalesce(Sum(cost), ZERO))
    totals = completed.aggregate(count=Count("id"), total=Coalesce(Sum("total"), ZERO),
                                 discounts=Coalesce(Sum("discount"), ZERO), coupons=Coalesce(Sum("coupon_discount"), ZERO))
    open_now = session.status == CashSession.Status.OPEN
    expected = expected_cash(session) if open_now else session.expected_amount
    return {
        "session": {
            "id": str(session.pk), "register": session.register.name, "terminal": session.terminal_label,
            "status": session.status, "opened_at": session.opened_at, "closed_at": session.closed_at,
            "opened_by": _name(session.opened_by), "closed_by": _name(session.closed_by),
            "approved_by": _name(session.approved_by), "approval_reason": session.approval_reason,
        },
        "sales": {
            "count": totals["count"], "total": totals["total"],
            "average_ticket": (totals["total"] / totals["count"]).quantize(Decimal("0.01")) if totals["count"] else ZERO,
            "discounts": totals["discounts"] + totals["coupons"],
            "cancelled_count": cancelled.count(), "cancelled_total": cancelled.aggregate(
                t=Coalesce(Sum("total"), ZERO))["t"],
            "cost": items["cost"], "gross_margin": items["revenue"] - items["cost"],
        },
        "by_payment_method": list(payments.values("method__name", "method__kind").annotate(
            count=Count("id"), total=Sum("amount"), change=Sum("change_amount")).order_by("-total")),
        "drawer": {
            "opening": session.opening_amount,
            **{kind: movements.filter(kind=kind).aggregate(t=Coalesce(Sum("amount"), ZERO))["t"]
               for kind in (CashMovement.Kind.SALE, CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY,
                            CashMovement.Kind.REFUND)},
            "pending_withdrawals": session.movements.filter(status=CashMovement.Status.PENDING).count(),
            "expected": expected,
            "counted": session.counted_amount,
            "difference": None if open_now else session.difference,
        },
    }
