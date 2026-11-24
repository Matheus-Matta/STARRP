from types import SimpleNamespace

from django.core.cache import cache
from rest_framework.test import APIRequestFactory

from starrp.core.throttling import AnonScopedRateThrottle

VIEW = SimpleNamespace(throttle_scope="login")


def _allowed(user, settings, times):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"login": "2/min"}}
    cache.clear()
    results = []
    for _ in range(times):
        request = APIRequestFactory().post("/api/v1/auth/login/")
        request.user = user
        throttle = AnonScopedRateThrottle()
        throttle.THROTTLE_RATES = {"login": "2/min"}
        results.append(throttle.allow_request(request, VIEW))
    return results


def test_anonimo_tem_limite(settings):
    assert _allowed(SimpleNamespace(is_authenticated=False), settings, 3) == [True, True, False]


def test_usuario_logado_sem_limite(settings):
    assert all(_allowed(SimpleNamespace(is_authenticated=True, pk=1), settings, 5))
