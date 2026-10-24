"""Autenticação: login, refresh, logout, me e redefinição de senha.

O PDV usa o token no header (`Authorization: Bearer`); a retaguarda web usa
os cookies httpOnly que o login também grava.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from starrp.core.envelope import envelope
from starrp.models import PasswordResetRequest
from starrp.serializers.users import MeSerializer

User = get_user_model()


def _set_cookies(response, access, refresh=None):
    options = {"httponly": True, "secure": settings.AUTH_COOKIE_SECURE, "samesite": settings.AUTH_COOKIE_SAMESITE}
    response.set_cookie(settings.JWT_AUTH_COOKIE, access, **options)
    if refresh:
        response.set_cookie(settings.JWT_AUTH_REFRESH_COOKIE, refresh, path="/api/v1/auth/", **options)
    return response


class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            _set_cookies(response, response.data["access"], response.data["refresh"])
        return response


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.data.get("refresh") or request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)
        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        serializer.is_valid(raise_exception=True)
        response = Response(serializer.validated_data)
        return _set_cookies(response, serializer.validated_data["access"], serializer.validated_data.get("refresh"))


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
        response.delete_cookie(settings.JWT_AUTH_COOKIE)
        response.delete_cookie(settings.JWT_AUTH_REFRESH_COOKIE, path="/api/v1/auth/")
        return response


class MeView(APIView):
    """Fica sob /api/v1/me/ (e não /auth/) porque precisa da conta resolvida."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer().to_representation(request))


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        email = serializers.EmailField().run_validation(request.data.get("email"))
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            token = secrets.token_urlsafe(32)
            PasswordResetRequest.objects.create(
                user=user, token_hash=_token_hash(token),
                expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_TIMEOUT_MINUTES),
            )
            link = f"{settings.FRONTEND_URL}/redefinir-senha?token={token}"
            send_mail("Redefinição de senha", f"Para criar uma nova senha acesse: {link}", None, [user.email])
        # Mesma resposta exista ou não o e-mail: não revela quem tem conta.
        return Response({"detail": "Se o e-mail existir, enviaremos as instruções."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        token, password = request.data.get("token", ""), request.data.get("password", "")
        reset = PasswordResetRequest.objects.filter(token_hash=_token_hash(token)).select_related("user").first()
        if reset is None or not reset.is_usable:
            return Response(envelope(400, "Link inválido ou expirado.", "reset_invalid"), status=400)
        if len(password) < 6:
            return Response(envelope(400, "A senha precisa ter ao menos 6 caracteres."), status=400)
        reset.user.set_password(password)
        reset.user.save(update_fields=["password"])
        reset.used_at = timezone.now()
        reset.save(update_fields=["used_at"])
        return Response({"detail": "Senha alterada."})
