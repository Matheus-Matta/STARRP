"""Rotas da API v1. Cada domínio registra as suas rotas no mesmo router.

Convenção: recurso no plural e em inglês (`/sales/`, `/stock/documents/`),
ação de negócio como sub-rota POST (`/sales/{id}/checkout/`).
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from starrp.urls import catalog, finance, operations, platform, sales, stock, system
from starrp.views import account, auth, cosmos, pdv, reports, reviews, webhooks, wms

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
    path("public/reviews/<str:token>/", reviews.PublicReviewView.as_view(), name="public-review"),
    path(
        "public/webhooks/<str:kind>/<uuid:integration_id>/",
        webhooks.IntegrationWebhookView.as_view(),
        name="integration-webhook",
    ),
    path("pdv/bootstrap/", pdv.PdvBootstrapView.as_view(), name="pdv-bootstrap"),
    path("pdv/unlock/", pdv.PdvUnlockView.as_view(), name="pdv-unlock"),
    path("pdv/fiscal-emitter/", pdv.PdvFiscalEmitterView.as_view(), name="pdv-fiscal-emitter"),
    path("pdv/acbr/", pdv.PdvAcbrView.as_view(), name="pdv-acbr"),
    path("pdv/acbr/health/", pdv.PdvAcbrHealthView.as_view(), name="pdv-acbr-health"),
    path("pdv/fiscal-kit/", pdv.PdvFiscalKitView.as_view(), name="pdv-fiscal-kit"),
    path("pdv/catalog-snapshot/", pdv.PdvCatalogSnapshotView.as_view(), name="pdv-catalog-snapshot"),
    path("pdv/offline-cash/", pdv.PdvOfflineCashView.as_view(), name="pdv-offline-cash"),
    path("pdv/authorize/", pdv.PdvAuthorizeView.as_view(), name="pdv-authorize"),
    path("pdv/offline-sales/", pdv.PdvOfflineSaleView.as_view(), name="pdv-offline-sales"),
    path("account/settings/", account.AccountSettingsView.as_view(), name="account-settings"),
    path("account/logo/", account.AccountLogoView.as_view(), name="account-logo"),
    path("pdv/products/<uuid:pk>/", pdv.PdvProductView.as_view(), name="pdv-product"),
    path("reports/book/<slug:name>/", reports.ReportBookView.as_view(), name="report-book"),
    path("reports/book/<slug:name>/export/", reports.ReportBookExportView.as_view(), name="report-book-export"),
    path("reports/<slug:name>/", reports.ReportView.as_view(), name="reports"),
    path("cosmos/status/", cosmos.CosmosStatusView.as_view(), name="cosmos-status"),
    path("cosmos/attachments/", cosmos.CosmosAttachmentView.as_view(), name="cosmos-attachments"),
    path("cosmos/voice/transcribe/", cosmos.CosmosVoiceTranscriptionView.as_view(), name="cosmos-voice-transcribe"),
    path("cosmos/reports/<uuid:pk>/export/", cosmos.CosmosReportExportView.as_view(), name="cosmos-report-export"),
    path("stock/labels/print/", wms.LabelPrintView.as_view(), name="labels-print"),
    *router.urls,
]
