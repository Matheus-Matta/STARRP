from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


def readiness(_request):
    """O healthcheck do container (D4-04): só fica saudável quem alcança o banco e o cache. Não é publicado no nginx
    (o `/health/` público responde mesmo com o banco fora, para o PDV saber que o servidor está de pé)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        cache.set("starrp:ready", 1, 30)
        ok = cache.get("starrp:ready") == 1
    except Exception:  # noqa: BLE001 — qualquer falha: ainda não está pronto
        ok = False
    return JsonResponse({"status": "ok" if ok else "unavailable"}, status=200 if ok else 503)


urlpatterns = [
    path("health/ready/", readiness, name="readiness"),
    path("health/", healthcheck, name="healthcheck"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/", include("starrp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
