"""Autorização de um superior no próprio PDV (desconto, cancelamento, sangria).

O operador pode ter a permissão; se não tiver, o corpo da requisição traz
`approval: {"username": ..., "password": ...}` de quem autoriza, ou
`approval: {"cash_password": ...}` com a senha de ações do caixa da loja.
"""
from decimal import Decimal

from django.contrib.auth.hashers import check_password, make_password

from starrp.core.errors import ApprovalRequired
from starrp.core.permissions import has_permission_code, is_account_admin
from starrp.models import UserProfile
from starrp.services import attempts

INVALID = "Usuário ou senha de autorização inválidos."
# Conferir uma senha leva o mesmo tempo achando ou não o usuário (o tempo não diz se o login existe).
_DUMMY_HASH = make_password("starrp-sem-usuario")


def _actor(user):
    return getattr(user, "pk", None) or "anon"


def _approver_from_credentials(account, credentials, code, actor=None):
    """Só quem é DESTA conta autoriza (S-04): o superusuário não, e usuário de outra conta recebe a mesma
    resposta de senha errada. Tentativas limitadas por autorizador e por quem pede."""
    username, password = credentials.get("username"), credentials.get("password")
    if not (username and password):
        return None
    target = ("approver", getattr(account, "pk", account), username)
    attempts.check(_actor(actor), target)
    profile = (UserProfile.all_objects.select_related("user")
               .filter(account=account, user__username=username, is_active=True, user__is_active=True,
                       user__is_superuser=False, deleted_at__isnull=True).first())
    if profile is None:
        check_password(password, _DUMMY_HASH)
        attempts.failed(_actor(actor), target)
        raise ApprovalRequired(INVALID, code="approval_invalid")
    user = profile.user
    if not user.check_password(password):
        attempts.failed(_actor(actor), target)
        raise ApprovalRequired(INVALID, code="approval_invalid")
    attempts.succeeded(target, _actor(actor))
    user.profile = profile
    if not has_permission_code(user, code):
        # A MESMA resposta da senha errada (rodada 1, P-11): "não tem permissão" confirmaria que a senha do
        # colega está certa.
        raise ApprovalRequired(INVALID, code="approval_invalid")
    return user


def check_cash_password(store, password, actor=None):
    """Senha de ações do caixa da loja, com limite de tentativas (S-04)."""
    if store is None or not password:
        return False
    target = ("cash", store.pk)
    attempts.check(_actor(actor), target)
    if store.check_cash_action_password(password):
        attempts.succeeded(target, _actor(actor))
        return True
    attempts.failed(_actor(actor), target)
    return False


def authorize(user, account, store, code, approval=None):
    """Devolve quem autorizou (o próprio usuário, um superior ou None quando foi
    a senha do caixa). Levanta `ApprovalRequired` se ninguém autorizou."""
    if has_permission_code(user, code):
        return user
    approval = approval or {}
    approver = _approver_from_credentials(account, approval, code, actor=user)
    if approver is not None:
        return approver
    cash_password = approval.get("cash_password")
    if cash_password and check_cash_password(store, cash_password, actor=user):
        return None
    raise ApprovalRequired(code="approval_required")


def max_discount_percent(user):
    if is_account_admin(user):
        return Decimal("100")
    profile = getattr(user, "profile", None)
    return Decimal(profile.max_discount_percent) if profile else Decimal("0")


def authorize_discount(user, account, store, percent, approval=None):
    """Desconto até o limite do cargo passa; acima, exige quem tenha limite maior."""
    if percent <= max_discount_percent(user):
        return user
    approver = _approver_from_credentials(account, approval or {}, "sales.discount", actor=user)
    if approver is not None and percent <= max_discount_percent(approver):
        return approver
    raise ApprovalRequired(
        f"Desconto de {percent:.2f}% acima do seu limite ({max_discount_percent(user):.2f}%).",
        code="discount_approval_required",
    )
