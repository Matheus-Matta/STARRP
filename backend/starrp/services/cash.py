"""Turno de caixa: abertura, sangria/suprimento, fechamento e aprovação.

Esperado em gaveta = abertura + movimentos APROVADOS (com sinal por tipo).
Diferença dentro de `Store.cash_closing_tolerance` fecha direto; fora dela, o
turno fica aguardando um gerente (rank maior) aprovar.
"""
from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from starrp.core.errors import ApprovalRequired, BusinessError, StateConflict
from starrp.core.permissions import has_permission_code
from starrp.models import CashMovement, CashSession, Payment, PaymentMethod
from starrp.services import ledger


def current_session(register):
    return CashSession.all_objects.filter(
        register=register, deleted_at__isnull=True, status=CashSession.Status.OPEN
    ).first()


def session_for_user(store, user):
    return (
        CashSession.all_objects.filter(store=store, opened_by=user, status=CashSession.Status.OPEN,
                                       deleted_at__isnull=True)
        .order_by("-opened_at")
        .first()
    )


def sees_drawer(user):
    """Fechamento CEGO: o operador não vê quanto deveria haver na gaveta (conta e informa);
    o esperado e a diferença são de quem aprova o fechamento (`cash.approve`)."""
    return has_permission_code(user, "cash.approve")


def can_operate(register, user):
    """Abre, movimenta e fecha o caixa quem está vinculado a ele (`operators`); quem aprova
    (gerente, supervisor) assume qualquer caixa da loja."""
    return sees_drawer(user) or register.operators.filter(pk=user.pk).exists()


def _require_operator(register, user, session=None):
    if session is not None and session.opened_by_id == user.pk:
        return
    if not can_operate(register, user):
        raise PermissionDenied(f"Você não está vinculado ao {register.name}. Peça ao gerente para vincular "
                               "em Financeiro → Caixas.")


def blind(data):
    """Tira da resposta (relatório/extrato do turno) o que revela a gaveta: só fica o troco
    inicial e o contado; a venda em dinheiro e a diferença também saem."""
    drawer = data.get("drawer")
    if isinstance(drawer, dict):
        data["drawer"] = {k: v for k, v in drawer.items() if k in ("opening", "counted")}
    if isinstance(data.get("by_payment_method"), list):
        data["by_payment_method"] = [r for r in data["by_payment_method"] if r.get("method__kind") != "cash"]
    if isinstance(data.get("occurrences"), list):
        data["occurrences"] = [o for o in data["occurrences"] if o.get("kind") != "Diferença de caixa"]
    data["blind"] = True
    return data


@transaction.atomic
def open_session(register, user, opening_amount=Decimal("0"), terminal=None):
    if not register.is_active:
        raise BusinessError("Caixa inativo.")
    _require_operator(register, user)
    try:
        with transaction.atomic():
            session = CashSession.all_objects.create(
                account_id=register.account_id,
                store_id=register.store_id,
                register=register,
                terminal=terminal,
                terminal_label=terminal.label if terminal else "",
                opened_by=user,
                created_by=user,
                opening_amount=Decimal(opening_amount),
            )
    except IntegrityError:
        busy = (CashSession.all_objects.filter(register=register, status=CashSession.Status.OPEN, deleted_at__isnull=True)
                .select_related("opened_by").first())
        who = busy.opened_by.get_full_name() or busy.opened_by.username if busy and busy.opened_by else "outro operador"
        since = timezone.localtime(busy.opened_at).strftime("%d/%m %H:%M") if busy else ""
        raise StateConflict(
            f"{register.name} já está com um turno aberto por {who}{f' desde {since}' if since else ''}. "
            "Escolha outro caixa ou peça para fechar esse turno.", code="register_busy",
        ) from None
    ledger.session_opened(session)
    return session


def _locked(session):
    session = CashSession.all_objects.select_for_update().get(pk=session.pk)
    if session.status != CashSession.Status.OPEN:
        raise StateConflict("O turno de caixa não está aberto.")
    return session


@transaction.atomic
def add_movement(session, user, kind, amount, reason="", destination=""):
    """Sangria e suprimento. Sangria sem permissão `cash.approve` fica pendente."""
    if kind not in (CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY, CashMovement.Kind.ADJUSTMENT):
        raise BusinessError("Tipo de movimento manual inválido.")
    amount = Decimal(amount)
    if amount <= 0:
        raise BusinessError("Informe um valor maior que zero.")
    session = _locked(session)
    _require_operator(session.register, user, session)
    if kind == CashMovement.Kind.WITHDRAWAL and amount > expected_cash(session):
        raise BusinessError("Sangria maior que o dinheiro em gaveta.")
    approved = kind != CashMovement.Kind.WITHDRAWAL or has_permission_code(user, "cash.approve")
    movement = CashMovement.all_objects.create(
        account_id=session.account_id,
        store_id=session.store_id,
        session=session,
        kind=kind,
        amount=amount,
        operator=user,
        reason=reason,
        destination=destination,
        status=CashMovement.Status.APPROVED if approved else CashMovement.Status.PENDING,
        approved_by=user if approved else None,
        approved_at=timezone.now() if approved else None,
    )
    ledger.session_movement(movement)
    return movement


def record_cash_payment(session, payment, user):
    """Entrada de dinheiro da venda na gaveta (líquido de troco)."""
    return CashMovement.all_objects.create(
        account_id=session.account_id, store_id=session.store_id, session=session, kind=CashMovement.Kind.SALE,
        amount=payment.amount, payment=payment, operator=user, approved_by=user, approved_at=timezone.now(),
    )


def expected_cash(session):
    total = Decimal(session.opening_amount)
    movements = session.movements.filter(status=CashMovement.Status.APPROVED)
    for kind, sign in CashMovement.SIGN.items():
        value = movements.filter(kind=kind).aggregate(total=Sum("amount"))["total"] or 0
        total += sign * Decimal(value)
    # Soma de agregados no SQLite volta com casas sobrando: arredonda onde nasce.
    return total.quantize(Decimal("0.01"))


def totals_by_method(session):
    rows = (
        Payment.all_objects.filter(cash_session=session, status=Payment.Status.APPROVED)
        .values("method__name", "method__kind")
        .annotate(total=Sum("amount"))
    )
    report = defaultdict(Decimal)
    for row in rows:
        report[row["method__name"]] += row["total"]
    return {name: str(value) for name, value in report.items()}


@transaction.atomic
def close_session(session, user, counted_amount, notes=""):
    session = _locked(session)
    _require_operator(session.register, user, session)
    if session.movements.filter(status=CashMovement.Status.PENDING).exists():
        raise StateConflict("Há sangrias aguardando aprovação neste turno.")
    expected = expected_cash(session)
    counted = Decimal(counted_amount)
    session.expected_amount = expected
    session.counted_amount = counted
    session.difference = counted - expected
    session.closing_report = {"by_method": totals_by_method(session), "cash_expected": str(expected)}
    session.closed_by, session.closed_at, session.notes = user, timezone.now(), notes
    within = abs(session.difference) <= session.store.cash_closing_tolerance
    session.status = CashSession.Status.CLOSED if within else CashSession.Status.PENDING_APPROVAL
    session.save()
    if session.status == CashSession.Status.CLOSED:
        ledger.session_closed(session)
    return session


@transaction.atomic
def approve_closing(session, approver, reason):
    session = CashSession.all_objects.select_for_update().get(pk=session.pk)
    if session.status != CashSession.Status.PENDING_APPROVAL:
        raise StateConflict("Este turno não está aguardando aprovação.")
    if not has_permission_code(approver, "cash.approve"):
        raise ApprovalRequired("Somente um gerente pode aprovar o fechamento com diferença.")
    session.status = CashSession.Status.CLOSED
    session.approved_by, session.approved_at, session.approval_reason = approver, timezone.now(), reason
    session.save(update_fields=["status", "approved_by", "approved_at", "approval_reason", "updated_at"])
    ledger.session_closed(session)
    return session


@transaction.atomic
def approve_movement(movement, approver):
    if not has_permission_code(approver, "cash.approve"):
        raise ApprovalRequired()
    movement = CashMovement.all_objects.select_for_update().get(pk=movement.pk)
    if movement.status != CashMovement.Status.PENDING:
        raise StateConflict("Movimento não está pendente.")
    movement.status, movement.approved_by, movement.approved_at = (
        CashMovement.Status.APPROVED, approver, timezone.now()
    )
    movement.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    ledger.session_movement(movement)
    return movement


def is_cash(method):
    return method.kind == PaymentMethod.Kind.CASH
