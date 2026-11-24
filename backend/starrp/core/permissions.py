"""Permissões da API.

Um só esquema, declarado na view:

    class ProductViewSet(TenantViewSet):
        permission_code = "catalog"      # leitura: catalog.view / escrita: catalog.manage
        required_module = Module.BASE

Ações customizadas podem exigir outro código com `@action(..., permission="sales.cancel")`
(lido de `view.action_permissions`). Admin da conta e superusuário passam sempre.
No StarChef havia uma classe de permissão por caso (`CanManageCashRegister`,
`CanOperateScale`, `CanUseOrManageDevices`...), cada uma com a sua regra.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from starrp.models.platform import MODULE_BASE


def profile_of(user):
    return getattr(user, "profile", None) if user and user.is_authenticated else None


def is_account_admin(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = profile_of(user)
    return bool(profile and profile.is_account_admin)


def user_permission_codes(user):
    if is_account_admin(user):
        return {"*"}
    profile = profile_of(user)
    return profile.permission_codes() if profile else set()


def has_permission_code(user, code):
    codes = user_permission_codes(user)
    if "*" in codes:
        return True
    implied_by = {
        "cosmos.view": {"cosmos.access", "cosmos.full"},
        "cosmos.manage": {"cosmos.full"},
        "pricing.view": {"pricing.access", "pricing.full"},
        "pricing.create": {"pricing.full"},
        "pricing.update": {"pricing.full"},
        "pricing.delete": {"pricing.full"},
        "pricing.manage": {"pricing.full"},
        "seo.view": {"seo.access", "seo.full"},
        "seo.create": {"seo.full"},
        "seo.update": {"seo.full"},
        "seo.delete": {"seo.full"},
        "seo.manage": {"seo.full"},
        "tasks.view": {"catalog.view", "pricing.access", "pricing.full", "seo.access", "seo.full"},
        "tasks.manage": {"catalog.manage", "pricing.full", "seo.full"},
    }
    if code == "cosmos.view":
        return can_use_cosmos(user)
    if code == "cosmos.manage":
        return can_use_cosmos(user) and bool(implied_by[code] & codes)
    return code in codes or bool(implied_by.get(code, set()) & codes)


def can_use_cosmos(user):
    """Cosmos exige acesso no cargo e continua opt-in por usuário."""
    if is_account_admin(user):
        return True
    profile = profile_of(user)
    codes = user_permission_codes(user)
    return bool(profile and profile.is_active and profile.cosmos_enabled
                and {"cosmos.access", "cosmos.full"} & codes)


def role_rank(user):
    if user and user.is_superuser:
        return 1000
    profile = profile_of(user)
    return profile.rank if profile else -1


class HasAccount(BasePermission):
    message = "Requisição sem conta ativa."

    def has_permission(self, request, view):
        return getattr(request, "account", None) is not None

    def has_object_permission(self, request, view, obj):
        account = getattr(request, "account", None)
        return account is not None and getattr(obj, "account_id", account.id) == account.id


class HasModule(BasePermission):
    message = "Este módulo não está habilitado para a sua conta."

    def has_permission(self, request, view):
        module = getattr(view, "required_module", MODULE_BASE)
        if module == MODULE_BASE or request.user.is_superuser:
            return True
        account = getattr(request, "account", None)
        return bool(account and account.has_module(module))


def _is_api_root(view):
    from rest_framework.routers import APIRootView

    return isinstance(view, APIRootView)


class HasViewPermission(BasePermission):
    message = "Você não tem permissão para esta ação."

    def has_permission(self, request, view):
        action_codes = getattr(view, "action_permissions", {}) or {}
        current = getattr(view, "action", None)
        if current in action_codes and action_codes[current] is None:
            return True  # ação aberta a qualquer usuário autenticado da conta
        code = action_codes.get(current)
        if code is None:
            base = getattr(view, "permission_code", None)
            if base is None:
                # Padrão NEGAR (S-09): view sem `permission_code` só abre se disser que é de propósito
                # (`open_to_account = True`, e aí ela confere o que precisa por dentro).
                return bool(getattr(view, "open_to_account", False)) or _is_api_root(view)
            # Ações em massa: aqui basta ver a lista; cada ação confere a sua (core/bulk.py).
            if request.method in SAFE_METHODS or current == "bulk":
                operation = "view"
            else:
                operation = {"create": "create", "update": "update", "partial_update": "update",
                             "destroy": "delete"}.get(current, "manage")
            code = f"{base}.{operation}"
        return has_permission_code(request.user, code)


class IsAccountAdmin(BasePermission):
    message = "Apenas administradores da conta."

    def has_permission(self, request, view):
        return is_account_admin(request.user)
