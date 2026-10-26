"""Turno de caixa: abertura, sangria/suprimento, fechamento e aprovação.

Esperado em gaveta = abertura + movimentos APROVADOS (com sinal por tipo).
Diferença dentro de `Store.cash_closing_tolerance` fecha direto; fora dela, o
turno fica aguardando um gerente aprovar. Sangria e suprimento também passam por
aprovação. Toda aprovação aceita o gerente logado, o usuário/senha dele digitado no
PDV ou a senha de ações do caixa da filial (`Store.cash_action_password`).
"""
from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from starrp.core.errors import BusinessError, StateConflict
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


def active_session_for_user(store, user):
    """O turno do operador que ainda conta (aberto ou com a abertura esperando o gerente)."""
    return (CashSession.all_objects
            .filter(store=store, opened_by=user, deleted_at__isnull=True,
                    status__in=[CashSession.Status.OPEN, CashSession.Status.PENDING_OPENING])
            .order_by("-opened_at").first())


def left_in_drawer(register):
    """O que o último fechamento deste caixa deixou na gaveta (`None` = caixa nunca aberto)."""
    last = (CashSession.all_objects.filter(register=register, status=CashSession.Status.CLOSED, deleted_at__isnull=True)
            .exclude(counted_amount=None).order_by("-closed_at").first())
    return None if last is None else last.counted_amount


@transaction.atomic
def open_session(register, user, opening_amount=Decimal("0"), terminal=None, notes=""):
    """Abertura com CONFERÊNCIA CEGA (como no StarChef): o operador conta a gaveta e informa,
    sem ver quanto deveria ter. Bate com o que o último fechamento deixou → abre. Não bate →
    a abertura espera o gerente aprovar (`approve_opening`) e o caixa não vende até lá.
    1ª abertura do caixa: o valor contado vira o saldo inicial."""
    if not register.is_active:
        raise BusinessError("Caixa inativo.")
    _require_operator(register, user)
    mine = active_session_for_user(register.store, user)
    if mine is not None:
        raise StateConflict(f"Você já está com o turno do {mine.register.name} em andamento: feche-o antes de abrir outro.",
                            code="operator_busy")
    counted = Decimal(opening_amount)
    expected = left_in_drawer(register)
    initial = expected is None
    matches = initial or counted == expected
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
                opening_amount=counted,
                opening_expected=None if initial else expected,
                opening_difference=Decimal("0") if initial else counted - expected,
                opening_is_initial=initial,
                opening_notes=notes,
                status=CashSession.Status.OPEN if matches else CashSession.Status.PENDING_OPENING,
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
    if session.status == CashSession.Status.OPEN:
        ledger.session_opened(session)
    return session


@transaction.atomic
def approve_opening(session, user, reason="", approval=None):
    """Gerente confere a abertura com diferença: com `cash.approve` aprova direto; o operador
    pode mandar `approval` (usuário/senha do gerente ou a senha de ações do caixa)."""
    from starrp.services.approvals import authorize

    session = CashSession.all_objects.select_for_update().get(pk=session.pk)
    if session.status != CashSession.Status.PENDING_OPENING:
        raise StateConflict("Esta abertura não está aguardando o gerente.", code="opening_not_pending")
    approver = authorize(user, session.account, session.store, "cash.approve", approval)
    session.status = CashSession.Status.OPEN
    session.opening_approved_by, session.opening_approved_at = approver or user, timezone.now()
    session.approval_reason = reason
    session.save(update_fields=["status", "opening_approved_by", "opening_approved_at", "approval_reason", "updated_at"])
    ledger.session_opened(session)
    return session


def _locked(session):
    session = CashSession.all_objects.select_for_update().get(pk=session.pk)
    if session.status != CashSession.Status.OPEN:
        raise StateConflict("O turno de caixa não está aberto.")
    return session


NEEDS_APPROVAL = (CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY)


def _decide(movement, approver, reason):
    """Grava quem aprovou: `approver=None` = foi a senha de ações do caixa da filial."""
    movement.status = CashMovement.Status.APPROVED
    movement.approved_by, movement.approved_at = approver, timezone.now()
    movement.authorized_by_password = approver is None
    movement.approval_reason = reason


@transaction.atomic
def add_movement(session, user, kind, amount, reason="", destination="", approval=None):
    """Sangria e suprimento passam por aprovação (como no StarChef): quem tem `cash.approve` lança
    aprovado; o operador pode mandar `approval` (usuário/senha do gerente ou a senha de ações do
    caixa da filial) e já sai aprovado; sem isso fica PENDENTE, fora da gaveta, até alguém aprovar."""
    from starrp.services.approvals import authorize

    if kind not in (CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY, CashMovement.Kind.ADJUSTMENT):
        raise BusinessError("Tipo de movimento manual inválido.")
    amount = Decimal(amount)
    if amount <= 0:
        raise BusinessError("Informe um valor maior que zero.")
    session = _locked(session)
    _require_operator(session.register, user, session)
    if kind == CashMovement.Kind.WITHDRAWAL and amount > available_for_withdrawal(session):
        raise BusinessError("Sangria maior que o dinheiro em gaveta (contando as sangrias que aguardam aprovação).")
    movement = CashMovement(account_id=session.account_id, store_id=session.store_id, session=session, kind=kind,
                            amount=amount, operator=user, reason=reason, destination=destination,
                            status=CashMovement.Status.PENDING)
    if kind not in NEEDS_APPROVAL or has_permission_code(user, "cash.approve"):
        _decide(movement, user, "")
    elif approval:
        _decide(movement, authorize(user, session.account, session.store, "cash.approve", approval), "")
    movement.save()
    ledger.session_movement(movement)
    return movement


def available_for_withdrawal(session):
    """Dinheiro em gaveta menos as sangrias que já aguardam aprovação (duas pendentes não
    podem somar mais do que há na gaveta)."""
    pending = (session.movements.filter(kind=CashMovement.Kind.WITHDRAWAL, status=CashMovement.Status.PENDING)
               .aggregate(total=Sum("amount"))["total"] or 0)
    return expected_cash(session) - Decimal(pending)


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
        raise StateConflict("Há sangria ou suprimento aguardando aprovação neste turno: aprove ou recuse antes de fechar.",
                            code="movements_pending")
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
def approve_closing(session, user, reason, approval=None):
    """Fechamento com diferença: com `cash.approve` aprova direto; o operador pode mandar
    `approval` (usuário/senha do gerente ou a senha de ações do caixa da filial)."""
    from starrp.services.approvals import authorize

    session = CashSession.all_objects.select_for_update().get(pk=session.pk)
    if session.status != CashSession.Status.PENDING_APPROVAL:
        raise StateConflict("Este turno não está aguardando aprovação.")
    approver = authorize(user, session.account, session.store, "cash.approve", approval)
    session.status = CashSession.Status.CLOSED
    session.approved_by, session.approved_at, session.approval_reason = approver or user, timezone.now(), reason
    session.save(update_fields=["status", "approved_by", "approved_at", "approval_reason", "updated_at"])
    ledger.session_closed(session)
    return session


def _pending(movement):
    """Relida com trava: recusada/aprovada enquanto a senha era digitada não muda de novo."""
    movement = CashMovement.all_objects.select_for_update().select_related("session").get(pk=movement.pk)
    if movement.status != CashMovement.Status.PENDING:
        raise StateConflict("Este movimento não está aguardando aprovação.", code="movement_not_pending")
    if movement.session.status != CashSession.Status.OPEN:
        raise StateConflict("O turno deste movimento não está mais aberto.")
    return movement


@transaction.atomic
def approve_movement(movement, user, reason="", approval=None):
    """Aprova sangria/suprimento pendente: gerente direto ou `approval` (gerente/senha do caixa).
    A sangria aprovada sai da gaveta e vai ao cofre; o suprimento entra."""
    from starrp.services.approvals import authorize

    movement = _pending(movement)
    approver = authorize(user, movement.account, movement.store, "cash.approve", approval)
    if movement.kind == CashMovement.Kind.WITHDRAWAL and movement.amount > expected_cash(movement.session):
        raise BusinessError("Sangria maior que o dinheiro em gaveta agora.")
    _decide(movement, approver, reason)
    movement.save(update_fields=["status", "approved_by", "approved_at", "authorized_by_password", "approval_reason",
                                 "updated_at"])
    ledger.session_movement(movement)
    return movement


@transaction.atomic
def reject_movement(movement, user, reason=""):
    """Recusa (gerente) ou desiste (o próprio operador): o movimento fica cancelado e não mexe na gaveta."""
    movement = _pending(movement)
    if movement.operator_id != user.pk and not has_permission_code(user, "cash.approve"):
        raise PermissionDenied("Só o gerente ou quem lançou pode recusar este movimento.")
    movement.status = CashMovement.Status.CANCELLED
    movement.approved_by, movement.approved_at, movement.approval_reason = user, timezone.now(), reason
    movement.save(update_fields=["status", "approved_by", "approved_at", "approval_reason", "updated_at"])
    return movement


def is_cash(method):
    return method.kind == PaymentMethod.Kind.CASH
