"""Autenticação: login, refresh, logout, me e redefinição de senha.

O PDV usa o token no header (`Authorization: Bearer`); a retaguarda web usa
os cookies httpOnly que o login também grava.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from starrp.core.envelope import envelope
from starrp.core.throttling import AnonScopedRateThrottle
from starrp.models import PasswordResetRequest
from starrp.serializers.users import MeSerializer
from starrp.services import password_reset, sessions
from starrp.tasks.accounts import send_password_reset

User = get_user_model()


# O app web avisa que trabalha SÓ com cookie: aí os tokens não vão no corpo da resposta (um script
# injetado na página não teria o que ler). PDV desktop e app móvel não mandam e seguem recebendo.
COOKIE_ONLY_HEADER = "HTTP_X_AUTH_TRANSPORT"


def _cookie_only(request, token_from_cookie=False):
    return token_from_cookie or request.META.get(COOKIE_ONLY_HEADER, "").lower() == "cookie"


def _without_tokens(response):
    response.data = {key: value for key, value in response.data.items() if key not in ("access", "refresh")}
    return response


def _set_cookies(response, access, refresh=None):
    options = {"httponly": True, "secure": settings.AUTH_COOKIE_SECURE, "samesite": settings.AUTH_COOKIE_SAMESITE}
    response.set_cookie(settings.JWT_AUTH_COOKIE, access, **options)
    if refresh:
        response.set_cookie(settings.JWT_AUTH_REFRESH_COOKIE, refresh, path="/api/v1/auth/", **options)
    return response


class LoginView(TokenObtainPairView):
    throttle_classes = [AnonScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            _set_cookies(response, response.data["access"], response.data["refresh"])
            if _cookie_only(request):
                _without_tokens(response)
        return response


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from_body = request.data.get("refresh")
        refresh = from_body or request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)
        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        # Refresh vencido, já girado ou revogado no logout: 401 (como nas views do simplejwt), não 500.
        # (`get_authenticate_header` abaixo impede o DRF de rebaixar o 401 para 403.)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as error:
            raise InvalidToken(error.args[0]) from error
        response = Response(serializer.validated_data)
        _set_cookies(response, serializer.validated_data["access"], serializer.validated_data.get("refresh"))
        # Renovado pelo cookie = navegador: o token novo fica só no cookie.
        return _without_tokens(response) if _cookie_only(request, token_from_cookie=not from_body) else response

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.data.get("refresh") or request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except Exception:  # noqa: BLE001 — token já inválido: logout continua
                pass
        response = Response({"detail": "Sessão encerrada."})
        response.delete_cookie(settings.JWT_AUTH_COOKIE, samesite=settings.AUTH_COOKIE_SAMESITE)
        response.delete_cookie(settings.JWT_AUTH_REFRESH_COOKIE, path="/api/v1/auth/", samesite=settings.AUTH_COOKIE_SAMESITE)
        return response


class MeView(APIView):
    """Fica sob /api/v1/me/ (e não /auth/) porque precisa da conta resolvida."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer().to_representation(request))


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        email = serializers.EmailField().run_validation(request.data.get("email"))
        # Procurar, criar o link e enviar ficam na fila: a resposta é a mesma, e no mesmo tempo, exista ou não o
        # e-mail (não revela quem tem conta). O link nasce no worker: não passa pelo Redis.
        send_password_reset.delay(email)
        return Response({"detail": "Se o e-mail existir, enviaremos as instruções."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonScopedRateThrottle]
    throttle_scope = "password_reset"

    @transaction.atomic
    def post(self, request):
        token, password = str(request.data.get("token") or ""), str(request.data.get("password") or "")
        reset = (PasswordResetRequest.objects.select_for_update(of=("self",)).filter(token_hash=password_reset.token_hash(token))
                 .select_related("user").first())
        if reset is None or not reset.is_usable:
            return Response(envelope(400, "Link inválido ou expirado.", "reset_invalid"), status=400)
        try:
            validate_password(password, user=reset.user)  # S-12: mesma política da tela de usuários
        except DjangoValidationError as error:
            return Response(envelope(400, " ".join(error.messages), "password_weak"), status=400)
        reset.user.set_password(password)
        reset.user.save(update_fields=["password"])
        # Este link e os outros ainda abertos deste usuário deixam de valer (R2-28).
        password_reset.invalidate(reset.user)
        sessions.revoke_all(reset.user)  # quem estava logado com a senha antiga sai
        return Response({"detail": "Senha alterada."})
