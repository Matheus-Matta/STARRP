"""Extrato completo do turno de caixa (a conferência linha a linha, além do "Z").

Junta o resumo do fechamento (`cash_report.summary`) com TUDO o que aconteceu:
- movimentos da gaveta (sangria, suprimento, devolução, venda em dinheiro);
- vendas do turno, com as formas de pagamento de cada uma;
- itens vendidos somados por produto (o que mais saiu e quanto rendeu);
- ocorrências: o que pede conferência (cancelamentos, sangria pendente, diferença).
"""
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce

from starrp.core.text import brl
from starrp.models import CashMovement, Sale, SaleItem
from starrp.services.cash_report import summary

ZERO = Decimal("0")


def _name(user):
    return (user.get_full_name() or user.username) if user else ""


def _movements(session):
    rows = session.movements.select_related("operator").order_by("created_at")
    return [{
        "id": str(m.pk), "created_at": m.created_at, "kind": m.kind, "kind_label": m.get_kind_display(),
        "amount": m.amount, "status": m.status, "status_label": m.get_status_display(), "reason": m.reason,
        "destination": m.destination, "operator": _name(m.operator),
    } for m in rows]


def _sales(session):
    sales = (Sale.all_objects.filter(cash_session=session).select_related("seller")
             .prefetch_related("payments__method").order_by("created_at"))
    return [{
        "id": str(sale.pk), "number": sale.number, "status": sale.status, "status_label": sale.get_status_display(),
        "created_at": sale.created_at, "completed_at": sale.completed_at, "customer": sale.customer_name or "",
        "seller": _name(sale.seller), "subtotal": sale.subtotal, "discount": sale.discount + sale.coupon_discount,
        "total": sale.total, "cancel_reason": getattr(sale, "cancel_reason", ""),
        "payments": ", ".join(f"{p.method.name} {brl(p.amount)}" for p in sale.payments.all() if p.status == "approved"),
    } for sale in sales]


def _items(session):
    cost = ExpressionWrapper(F("unit_cost") * F("quantity"), output_field=DecimalField(max_digits=18, decimal_places=4))
    rows = (SaleItem.all_objects.filter(sale__cash_session=session, sale__status=Sale.Status.COMPLETED,
                                        status=SaleItem.Status.ACTIVE)
            .values("variant", "description", "sku", "unit")
            # `sold_quantity`, não `quantity`: o nome sombrearia o campo e o custo multiplicaria por uma soma.
            .annotate(sold_quantity=Sum("quantity"), total=Coalesce(Sum("total"), ZERO), cost=Coalesce(Sum(cost), ZERO),
                      sales=Count("sale", distinct=True))
            .order_by("-total"))
    return [{**{k: v for k, v in row.items() if k != "sold_quantity"}, "quantity": row["sold_quantity"],
             "variant": str(row["variant"]), "margin": row["total"] - row["cost"]} for row in rows]


def statement(session):
    result = summary(session)
    movements = _movements(session)
    sales = _sales(session)
    cancelled_items = SaleItem.all_objects.filter(sale__cash_session=session, status=SaleItem.Status.CANCELLED)
    occurrences = (
        [{"kind": "Sangria pendente", "tone": "warning", "text": f"{m['kind_label']} de {brl(m['amount'])} — {m['reason'] or 'sem motivo'}"}
         for m in movements if m["status"] == CashMovement.Status.PENDING]
        + [{"kind": "Venda cancelada", "tone": "danger", "text": f"Venda {s['number']} ({brl(s['total'])})"}
           for s in sales if s["status"] == Sale.Status.CANCELLED]
        + [{"kind": "Venda em aberto", "tone": "warning",
            "text": f"Venda {s['number']} ({brl(s['total'])}) ficou aberta: conclua ou cancele no PDV"}
           for s in sales if s["status"] == Sale.Status.OPEN]
        + [{"kind": "Item cancelado", "tone": "danger",
            "text": f"Venda {i.sale.number}: {i.description} — {i.cancel_reason or 'sem motivo'}"}
           for i in cancelled_items.select_related("sale")]
    )
    difference = result["drawer"].get("difference")
    if difference:
        occurrences.append({"kind": "Diferença de caixa", "tone": "danger" if difference < 0 else "warning",
                            "text": f"Contado menos esperado: {brl(difference)}"})
    return {**result, "movements": movements, "sales_list": sales, "items": _items(session), "occurrences": occurrences}
