"""Limites de requisição: só para quem NÃO está logado. Usuário autenticado não tem limite."""
from rest_framework.throttling import ScopedRateThrottle


class AnonScopedRateThrottle(ScopedRateThrottle):
    """O limite por escopo (login, redefinição de senha) vale só para anônimos."""

    def allow_request(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return True
        return super().allow_request(request, view)
