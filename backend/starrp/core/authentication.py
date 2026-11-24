from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication

_CACHE_ATTR = "_starrp_jwt_auth"


class CookieJWTAuthentication(JWTAuthentication):
    """JWT pelo header `Authorization: Bearer` (PDVs) ou pelo cookie httpOnly
    (retaguarda web). Cookies `SameSite=Lax` fecham o vetor de CSRF.

    O resultado fica guardado na requisição: o TenantMiddleware autentica primeiro e o DRF
    reaproveita o MESMO usuário (sem decodificar o token e buscar o usuário de novo, e sem perder
    o perfil/permissões já carregados nele)."""

    def authenticate(self, request):
        django_request = getattr(request, "_request", request)
        cached = getattr(django_request, _CACHE_ATTR, None)
        if cached is not None:
            return cached
        header = self.get_header(request)
        raw_token = self.get_raw_token(header) if header is not None else None
        if raw_token is None:
            raw_token = request.COOKIES.get(settings.JWT_AUTH_COOKIE)
        if not raw_token:
            return None
        validated = self.get_validated_token(raw_token)
        result = (self.get_user(validated), validated)
        setattr(django_request, _CACHE_ATTR, result)
        return result
