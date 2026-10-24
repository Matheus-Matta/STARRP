"""Autorização de um superior no próprio PDV (desconto, cancelamento, sangria).

O operador pode ter a permissão; se não tiver, o corpo da requisição traz
`approval: {"username": ..., "password": ...}` de quem autoriza, ou
`approval: {"cash_password": ...}` com a senha de ações do caixa da loja.
"""
from decimal import Decimal

from django.contrib.auth import authenticate

from starrp.core.errors import ApprovalRequired
from starrp.core.permissions import has_permission_code, is_account_admin
from starrp.models import UserProfile


def _approver_from_credentials(account, credentials, code):
    username, password = credentials.get("username"), credentials.get("password")
    if not (username and password):
        return None
    user = authenticate(username=username, password=password)
    if user is None:
        raise ApprovalRequired("Usuário ou senha de autorização inválidos.", code="approval_invalid")
    profile = UserProfile.all_objects.filter(user=user, account=account, is_active=True).first()
    if not user.is_superuser and profile is None:
        raise ApprovalRequired("O autorizador não pertence a esta conta.", code="approval_invalid")
    if not has_permission_code(user, code):
        raise ApprovalRequired("O autorizador não tem permissão para esta ação.", code="approval_invalid")
    return user


def authorize(user, account, store, code, approval=None):
    """Devolve quem autorizou (o próprio usuário, um superior ou None quando foi
    a senha do caixa). Levanta `ApprovalRequired` se ninguém autorizou."""
    if has_permission_code(user, code):
        return user
    approval = approval or {}
    approver = _approver_from_credentials(account, approval, code)
    if approver is not None:
        return approver
    cash_password = approval.get("cash_password")
    if cash_password and store is not None and store.check_cash_action_password(cash_password):
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
    approver = _approver_from_credentials(account, approval or {}, "sales.discount")
    if approver is not None and percent <= max_discount_percent(approver):
        return approver
    raise ApprovalRequired(
        f"Desconto de {percent:.2f}% acima do seu limite ({max_discount_percent(user):.2f}%).",
        code="discount_approval_required",
    )
