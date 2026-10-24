"""Rotas da API v1. Cada domínio registra as suas rotas no mesmo router.

Convenção: recurso no plural e em inglês (`/sales/`, `/stock/documents/`),
ação de negócio como sub-rota POST (`/sales/{id}/checkout/`).
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from starrp.urls import catalog, finance, operations, platform, sales, stock, system
from starrp.views import account, auth, pdv, reports, wms

router = DefaultRouter()
for module in (platform, catalog, sales, operations, stock, finance, system):
    module.register(router)

urlpatterns = [
    path("auth/login/", auth.LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", auth.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", auth.LogoutView.as_view(), name="auth-logout"),
    path("auth/password-reset/", auth.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("auth/password-reset/confirm/", auth.PasswordResetConfirmView.as_view(), name="auth-password-confirm"),
    path("me/", auth.MeView.as_view(), name="me"),
    path("pdv/bootstrap/", pdv.PdvBootstrapView.as_view(), name="pdv-bootstrap"),
    path("pdv/unlock/", pdv.PdvUnlockView.as_view(), name="pdv-unlock"),
    path("account/settings/", account.AccountSettingsView.as_view(), name="account-settings"),
    path("pdv/products/<uuid:pk>/", pdv.PdvProductView.as_view(), name="pdv-product"),
    path("reports/<slug:name>/", reports.ReportView.as_view(), name="reports"),
    path("stock/labels/print/", wms.LabelPrintView.as_view(), name="labels-print"),
    *router.urls,
]
