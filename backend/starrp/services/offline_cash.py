"""Turno de caixa feito no PDV desktop SEM o servidor (como no caixa de mercado).

O terminal é quem manda no turno dele: abre, lança sangria/suprimento e fecha mesmo sem rede,
e manda cada evento, EM ORDEM, quando o servidor volta (`POST /pdv/offline-cash/`). As vendas
do turno vão na mesma fila, entre a abertura e o fechamento, então o fechamento chega aqui com
todas as vendas já gravadas e o esperado em gaveta é calculado como sempre.

- A conferência cega continua: o operador informou o contado; quem compara com o esperado é
  o servidor. Abertura ou fechamento feitos sem servidor NÃO travam o caixa (a loja já vendeu
  nesse turno / precisa abrir o próximo): a diferença fica registrada no turno
  (`opening_difference` / `difference` + `approval_reason`) para o gerente conferir. Se o
  gerente (ou a senha de ações do caixa) aprovou no terminal, vem `approved_by`/`by_password`.
- Sangria/suprimento offline é FATO (o dinheiro já saiu/entrou): não passa pelo "maior que a
  gaveta"; sem aprovação no terminal, fica pendente para o gerente.
- Cada evento tem `offline_id`: reenviar devolve o já gravado.
- O turno do terminal é chamado de "off:<id>" nas vendas e nos eventos seguintes.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.permissions import has_permission_code
from starrp.core.values import moment, money, user_pk
from starrp.models import CashMovement, CashRegister, CashSession, Terminal, UserProfile
from starrp.services import cash, ledger

User = get_user_model()
PREFIX = "off:"


def actor_for(account, sender, operator_id):
    """Quem fez a operação no terminal (a fila pode ser enviada depois, por outro login)."""
    if not operator_id or str(operator_id) == str(sender.pk):
        return sender
    user = User.objects.filter(pk=user_pk(operator_id), is_active=True, is_superuser=False).first()
    # Só quem é DESTA conta e está ativo (S-06): nada de atribuir a operação a outra conta ou ao suporte.
    if user is None or not UserProfile.all_objects.filter(user=user, account=account, is_active=True,
                                                           deleted_at__isnull=True).exists():
        raise BusinessError("O operador da operação offline não pertence a esta conta.", code="offline_operator_unknown")
    return user


def resolve_session(store, ref):
    if not ref:
        return None
    ref = str(ref)
    if ref.startswith(PREFIX):
        return CashSession.all_objects.filter(store=store, offline_id=ref[len(PREFIX):], deleted_at__isnull=True).first()
    return CashSession.all_objects.filter(store=store, pk=ref, deleted_at__isnull=True).first()


MAX_OFFLINE_DAYS = 30


def _check_owner(session, sender):
    """O turno é de quem envia, ou quem envia aprova caixa (R2-11): o caixa A não mexe na gaveta do B."""
    if session.opened_by_id != sender.pk and not has_permission_code(sender, "cash.approve"):
        raise BusinessError("Este turno de caixa é de outro operador.", code="offline_session_other")


def _when(value):
    return moment(value) or timezone.now()


def _approver(store, actor, data):
    """`(aprovou, quem)`; quem = None quando foi a senha de ações do caixa.

    Só vale com o COMPROVANTE que o servidor deu em `/pdv/authorize/` (uso único, rodada 1 P-3): sem ele o PDV
    escreveria qualquer `approved_by` (até de outra conta) ou `by_password: true` sem senha nenhuma. Sem
    comprovante: não aprova (sangria fica pendente, turno fica "confira") e a gerência é avisada."""
    from starrp.services import approval_proof

    approver, target = None, None
    if data.get("approved_by"):
        approver = User.objects.filter(pk=user_pk(data["approved_by"]), is_active=True, is_superuser=False).first()
        if approver is None or not UserProfile.all_objects.filter(user=approver, account=store.account,
                                                                 deleted_at__isnull=True).exists():
            raise BusinessError("Quem aprovou a operação offline não pertence a esta conta.", code="offline_user_unknown")
        target = approver.pk
    elif data.get("by_password"):
        target = approval_proof.CASH_PASSWORD
    else:
        return False, None
    proofs = approval_proof.decode(data.get("approval_proofs"))
    proof = approval_proof.find(proofs, account=store.account, store=store, operator=actor, approver_id=target,
                                codes={"cash.approve"}, what=approval_proof.scope_of("cash.approve", data))
    if proof is None or not approval_proof.spend(proof):
        _alert(store, actor, data)
        return False, approver
    return True, approver


def _alert(store, actor, data):
    from starrp.models import Notification
    from starrp.services import notifications

    what = {"open": "abertura", "movement": "sangria/suprimento", "close": "fechamento"}.get(str(data.get("event")), "operação")
    notifications.send(
        account=store.account, store=store, category=Notification.Category.CASH, level=Notification.Level.WARNING,
        permission="cash.approve", title=f"Caixa offline: {what} com autorização a conferir",
        body=f"{actor.get_full_name() or actor.username} informou uma autorização feita sem o servidor em "
             f"{store.name}: confira.", entity="cashsession", object_id=str(data.get("session") or ""))


def _auto_approves(actor, sender):
    """Quem fez E quem enviou podem aprovar (o operador vem do PDV: sozinho, não basta)."""
    return has_permission_code(actor, "cash.approve") and has_permission_code(sender, "cash.approve")


def _in_session(value, session):
    """Hora informada pelo PDV, mas dentro do turno e nunca no futuro."""
    when, now = _when(value), timezone.now()
    floor = getattr(session, "opened_at", None) or now - timedelta(days=30)
    return when if floor - timedelta(minutes=5) <= when <= now + timedelta(minutes=5) else now


def _session_or_fail(store, ref):
    session = resolve_session(store, ref)
    if session is None:
        raise BusinessError("Turno de caixa da operação offline não encontrado (a abertura ainda não chegou?).",
                            code="offline_session_missing")
    return session


@transaction.atomic
def open_session(store, actor, data, offline_id, sender=None):
    existing = CashSession.all_objects.filter(store=store, offline_id=offline_id).first()
    if existing is not None:
        return existing, False
    register = CashRegister.all_objects.filter(store=store, pk=data.get("register")).first()
    if register is None:
        raise BusinessError("Caixa da abertura offline não existe nesta filial.", code="offline_register_missing")
    terminal = Terminal.all_objects.filter(account=store.account, installation_id=data.get("installation_id")).first()
    if sender is not None and sender.pk != actor.pk and not has_permission_code(sender, "cash.approve"):
        # R4-03: o caixa A abria turno em nome do B. A fila de outro operador vai com o login dele (ou do gerente).
        raise BusinessError("Este turno de caixa é de outro operador.", code="offline_session_other")
    session = cash.open_session(register, actor, money(data.get("opening_amount")), terminal,
                                str(data.get("notes") or ""))
    session.offline_id = offline_id
    session.save(update_fields=["offline_id"])
    # Abertura informada pelo PC: no máximo 30 dias atrás (fila parada, o mesmo da venda) e nunca no futuro (R2-12 — `opened_at` antigo
    # reabria a janela para retroagir a hora das vendas).
    opened = _when(data.get("opened_at"))
    if not timezone.now() - timedelta(days=MAX_OFFLINE_DAYS) <= opened <= timezone.now() + timedelta(minutes=5):
        opened = timezone.now()
    CashSession.all_objects.filter(pk=session.pk).update(opened_at=opened)
    approved, approver = _approver(store, actor, data)
    if session.status == CashSession.Status.PENDING_OPENING:
        # O terminal já vendeu nesse turno: ele não pode ficar travado. Abre, e a diferença fica
        # registrada (opening_difference) para o gerente conferir.
        session.status = CashSession.Status.OPEN
        if approved:
            session.opening_approved_by, session.opening_approved_at = approver or actor, _when(data.get("approved_at"))
            session.approval_reason = str(data.get("reason") or "Aprovada no PDV sem servidor.")
        else:
            session.approval_reason = (f"Aberta no PDV sem servidor com diferença de R$ {session.opening_difference} "
                                       "na conferência: confira.")
            _alert(store, actor, data)  # diferença sem aprovação sempre chega à gerência (R2-10)
        session.save(update_fields=["status", "opening_approved_by", "opening_approved_at", "approval_reason"])
        ledger.session_opened(session)
    session.refresh_from_db()
    return session, True


@transaction.atomic
def movement(store, actor, data, offline_id, sender=None):
    existing = CashMovement.all_objects.filter(store=store, offline_id=offline_id).first()
    if existing is not None:
        return existing, False
    kind = data.get("kind")
    if kind not in (CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY):
        raise BusinessError("Movimento offline inválido.", code="offline_movement_kind")
    amount = money(data.get("amount"))
    if amount <= 0:
        raise BusinessError("Movimento offline sem valor.")
    session = CashSession.all_objects.select_for_update().get(pk=_session_or_fail(store, data.get("session")).pk)
    if session.status != CashSession.Status.OPEN:
        raise StateConflict("O turno deste movimento não está aberto no servidor.", code="offline_session_closed")
    _check_owner(session, sender or actor)
    row = CashMovement(account_id=session.account_id, store_id=session.store_id, session=session, kind=kind,
                       amount=amount, operator=actor, reason=str(data.get("reason") or ""),
                       destination=str(data.get("destination") or "")[:255], status=CashMovement.Status.PENDING,
                       offline_id=offline_id)
    if _auto_approves(actor, sender or actor):
        cash._decide(row, actor, "")
    else:
        approved, approver = _approver(store, actor, data)
        if approved:
            cash._decide(row, approver, "Aprovada no PDV sem servidor.")
    row.save()
    CashMovement.all_objects.filter(pk=row.pk).update(created_at=_in_session(data.get("at"), session))
    ledger.session_movement(row)
    return row, True


@transaction.atomic
def close(store, actor, data, offline_id, sender=None):
    session = _session_or_fail(store, data.get("session"))
    if session.closed_at is not None:
        return session, False  # já fechado (reenvio)
    _check_owner(session, sender or actor)
    session = cash.close_session(session, actor, money(data.get("counted_amount")), str(data.get("notes") or ""),
                                 allow_pending=True)
    CashSession.all_objects.filter(pk=session.pk).update(closed_at=_in_session(data.get("closed_at"), session))
    approved, approver = _approver(store, actor, data)
    if session.status == CashSession.Status.PENDING_APPROVAL:
        # Fechado no terminal sem servidor: o turno ENCERROU (o caixa precisa abrir o próximo, e
        # um turno "aguardando" seguraria o caixa). A diferença fica registrada para o gerente.
        session.status = CashSession.Status.CLOSED
        if approved and str(data.get("reason") or "").strip():
            session.approved_by, session.approved_at = approver or actor, _in_session(data.get("closed_at"), session)
            session.approval_reason = str(data["reason"])
        else:
            session.approval_reason = (f"Fechado no PDV sem servidor com diferença de R$ {session.difference}: "
                                       "confira com o operador.")
            _alert(store, actor, data)
        session.save(update_fields=["status", "approved_by", "approved_at", "approval_reason"])
        ledger.session_closed(session)
    session.refresh_from_db()
    return session, True


@transaction.atomic
def late_sale(session):
    """Venda que chegou depois do turno fechado (R4-02): é fato e entra nele, mas a conferência já feita não pode
    continuar dizendo que bateu. O esperado e a diferença são refeitos; quem conferiu e o contado não mudam."""
    session = CashSession.all_objects.select_for_update().get(pk=session.pk)
    if session.status == CashSession.Status.OPEN or session.counted_amount is None:
        return session
    session.expected_amount = cash.expected_cash(session)
    session.difference = session.counted_amount - session.expected_amount
    session.closing_report = {**(session.closing_report or {}), "by_method": cash.totals_by_method(session),
                              "cash_expected": str(session.expected_amount)}
    note = f"Venda recebida depois do fechamento: diferença agora R$ {session.difference}, confira."
    session.approval_reason = f"{session.approval_reason} {note}".strip()
    session.save(update_fields=["expected_amount", "difference", "closing_report", "approval_reason", "updated_at"])
    return session


HANDLERS = {"open": open_session, "movement": movement, "close": close}


def apply(store, sender, data):
    kind = str(data.get("event") or "")
    offline_id = str(data.get("offline_id") or "").strip()
    if kind not in HANDLERS or not offline_id:
        raise BusinessError("Evento de caixa offline inválido.", code="offline_cash_invalid")
    actor = actor_for(store.account, sender, data.get("operator"))
    return kind, *HANDLERS[kind](store, actor, data, offline_id, sender=sender)
