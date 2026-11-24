"""Resolve a conta (tenant) e a loja da requisição.

Antes o isolamento era feito três vezes (manager por ContextVar, mixin que
ignorava o manager, e um middleware que re-parseava todo JSON de resposta
procurando `account`). Agora é uma vez: este middleware fixa a conta no
contexto e o `TenantManager` filtra toda consulta por ela.

A loja ativa vem do header `X-Store-ID` (o seletor da retaguarda ou a loja do
PDV) e é validada contra o perfil: quem está preso a uma loja não troca.
"""
import logging

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from starrp.core.authentication import CookieJWTAuthentication
from starrp.core.envelope import envelope
from starrp.core.tenant import clear_current_account, set_current_account

logger = logging.getLogger(__name__)

ALL_STORES = "*"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _cross_site_cookie_write(request):
    """CSRF com o login por cookie (S-12): o SameSite já barra a maioria, mas é configurável. Gravação que leva
    o cookie de login e vem de OUTRA origem (o navegador sempre manda `Origin` num POST de outro site) é
    recusada. Sem cookie (PDV desktop/app móvel, Bearer) ou sem Origin (não é navegador), segue."""
    if request.method in SAFE_METHODS:
        return False
    if not (request.COOKIES.get(settings.JWT_AUTH_COOKIE) or request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)):
        return False
    origin = request.META.get("HTTP_ORIGIN") or ""
    if not origin:
        return False
    if origin == "null":
        return True  # página sandbox/arquivo local: nunca é o app
    own = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}"
    trusted = {o.rstrip("/") for o in getattr(settings, "CSRF_TRUSTED_ORIGINS", [])}
    return origin.rstrip("/") not in trusted | {own}
PUBLIC_PREFIXES = ("/admin/", "/static/", "/media/", "/health/", "/api/schema/", "/api/v1/auth/", "/api/v1/public/")


def _deny(status, message, code=None):
    return JsonResponse(envelope(status, message, code), status=status)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt = CookieJWTAuthentication()

    def __call__(self, request):
        request.account = None
        request.store = None
        if request.path.startswith("/api/") and _cross_site_cookie_write(request):
            return _deny(403, "Origem não confiável para esta gravação.", "csrf_origin")
        try:
            if request.path.startswith("/api/") and not request.path.startswith(PUBLIC_PREFIXES):
                denied = self._resolve(request)
                if denied is not None:
                    return denied
            return self.get_response(request)
        finally:
            clear_current_account()

    def _resolve(self, request):
        try:
            authenticated = self.jwt.authenticate(request)
        except (InvalidToken, TokenError, AuthenticationFailed):
            return _deny(401, "Credencial inválida ou expirada.", "not_authenticated")
        if not authenticated:
            request.user = AnonymousUser()
            return None  # o DRF responde 401 pela permissão IsAuthenticated
        request.user, request.auth = authenticated
        return bind_user(request)


def bind_user(request):
    """Conta, perfil, lojas permitidas e loja ativa de `request.user` (já autenticado).

    Também serve fora do HTTP: o WebSocket da Cosmos e as chamadas que ela faz à API
    em nome do usuário passam por aqui, com as mesmas regras. Devolve a resposta de
    recusa (403) ou `None`; o contexto da conta fica fixado na thread.
    """
    request.store = None
    account, profile = _account_for(request)
    if account is None:
        return _deny(403, "Seu usuário não está vinculado a nenhuma conta.")
    if not account.is_active:
        return _deny(403, "A conta não está ativa.", "account_inactive")
    request.account = account
    request.profile = profile
    if _revoked(request, profile):
        return _deny(401, "Sua sessão foi encerrada (senha alterada). Entre de novo.", "session_revoked")
    allowed = profile.allowed_store_ids() if profile is not None else None
    if allowed is not None and not allowed:
        return _deny(403, "Seu usuário não tem acesso a nenhuma filial. Peça ao administrador.", "no_store_access")
    request.allowed_store_ids = allowed
    set_current_account(account, allowed)
    # Vendedor (sem `sales.view_all`): lista, consultas e relatórios de venda mostram só as dele.
    from starrp.core.permissions import has_permission_code
    from starrp.core.tenant import set_own_sales_user

    set_own_sales_user(None if has_permission_code(request.user, "sales.view_all") else request.user.pk)
    return _resolve_store(request, profile, allowed)


def _revoked(request, profile):
    """Token emitido antes de `sessions_revoked_at` (troca/redefinição de senha) não vale mais (S-12)."""
    revoked = getattr(profile, "sessions_revoked_at", None)
    token = getattr(request, "auth", None)
    if revoked is None or token is None or not hasattr(token, "get"):
        return False
    issued = token.get("iat")
    return issued is not None and int(issued) < int(revoked.timestamp())


def _account_for(request):
    from starrp.models import Account, UserProfile

    user = request.user
    if user.is_superuser and request.headers.get("X-Account-ID"):
        return Account.objects.filter(id=request.headers["X-Account-ID"]).first(), None
    profile = (
        UserProfile.alive_objects.select_related("account", "role", "default_store")
        .filter(user=user, is_active=True)
        .first()
    )
    if profile is None:
        return None, None
    # O mesmo objeto em `user.profile`: as checagens de permissão da requisição usam este perfil
    # (e o cache de cargos/permissões dele) em vez de buscar o perfil de novo.
    user.profile = profile
    return profile.account, profile


def _resolve_store(request, profile, allowed):
    """Loja ATIVA: o header, senão a padrão do usuário, senão a única que ele tem.

    `X-Store-ID: *` pede a visão de TODAS as lojas permitidas (sem loja ativa).

    Já com o contexto fixado, `Store.objects` só acha loja permitida: pedir
    uma loja de fora dá 403, e não "achei" — nem a existência dela vaza.
    """
    from starrp.models import Store

    requested = request.headers.get("X-Store-ID")
    if requested == ALL_STORES:
        return None  # visão consolidada das lojas permitidas, sem loja ativa
    if requested:
        try:
            request.store = Store.objects.filter(id=requested).first()
        except (ValueError, ValidationError):
            request.store = None
        if request.store is None:
            return _deny(403, "Você não tem acesso à filial informada em X-Store-ID.", "store_forbidden")
    elif profile is not None and profile.default_store_id and Store.objects.filter(
        pk=profile.default_store_id
    ).exists():
        request.store = profile.default_store
    else:
        # Quem enxerga UMA loja só (restrito ou admin de conta com uma loja)
        # não precisa escolher: ela é a ativa.
        visible = list(Store.objects.filter(is_active=True).values_list("pk", flat=True)[:2])
        if len(visible) == 1:
            request.store = Store.objects.filter(pk=visible[0]).first()
    return None
