"""Toda view da API tem permissão declarada (docs/SEGURANCA.md S-09): padrão NEGAR."""
from django.urls import get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.routers import APIRootView
from rest_framework.views import APIView

from starrp.core.permissions import HasViewPermission

# Fora do HasViewPermission de propósito: sem login (login, refresh, logout, reset, avaliação pública, schema)
# ou com a própria regra (MeView: só autenticado; configurações e logo da conta: IsAccountAdmin).

PUBLIC = {"LoginView", "RefreshView", "LogoutView", "PasswordResetRequestView", "PasswordResetConfirmView",
          "PublicReviewView", "SpectacularAPIView", "SpectacularSwaggerView", "MeView", "AccountSettingsView",
          "AccountLogoView"}


def _views():
    seen = {}

    def walk(patterns, prefix=""):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
                continue
            view = getattr(pattern.callback, "cls", None) or getattr(pattern.callback, "view_class", None)
            if view is not None and issubclass(view, APIView):
                seen.setdefault(view, prefix + str(pattern.pattern))

    walk(get_resolver().url_patterns)
    return seen


def test_toda_view_declara_permissao_ou_abertura_explicita():
    loose = []
    for view, route in _views().items():
        if view.__name__ in PUBLIC or issubclass(view, APIRootView):
            continue
        classes = view.permission_classes
        if AllowAny in classes:
            loose.append(f"{route} ({view.__name__}): AllowAny")
            continue
        if HasViewPermission in classes and not getattr(view, "permission_code", None) \
                and not getattr(view, "open_to_account", False):
            loose.append(f"{route} ({view.__name__}): sem permission_code nem open_to_account")
    assert not loose, "\n".join(loose)


def test_estoquista_nao_baixa_a_carteira_de_clientes_pelo_pdv(ctx):
    stockist = ctx.user("estoq", "stockist")
    cashier = ctx.user("caixa", "cashier")
    api = ctx.client(stockist)

    snapshot = api.get("/api/v1/pdv/catalog-snapshot/")
    as_cashier = ctx.client(cashier).get("/api/v1/pdv/catalog-snapshot/")

    assert snapshot.status_code == 403
    assert as_cashier.status_code == 200 and "customers" in as_cashier.json()
