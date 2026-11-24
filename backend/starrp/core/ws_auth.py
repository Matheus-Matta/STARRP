"""Autenticação do WebSocket: o mesmo JWT da API, só pelo cookie httpOnly (retaguarda web).

Nada de `?token=` na URL (S-15): o endereço vai para o log do nginx, do proxy e do histórico do navegador.
Sem token válido, `scope["user"]` fica anônimo e o consumidor fecha. A origem do handshake é conferida em
config/asgi.py (outro site não abre o WebSocket com o cookie de quem visita)."""
from http.cookies import SimpleCookie

from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


def _raw_token(scope):
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            cookie = SimpleCookie()
            cookie.load(value.decode())
            if settings.JWT_AUTH_COOKIE in cookie:
                return cookie[settings.JWT_AUTH_COOKIE].value
    return None


@database_sync_to_async
def _user_for(raw):
    """(usuário, emitido em, vence em) do token; anônimo se inválido."""
    auth = JWTAuthentication()
    try:
        token = auth.get_validated_token(raw)
        return auth.get_user(token), token.get("iat"), token.get("exp")
    except (InvalidToken, TokenError, Exception):  # noqa: BLE001 — qualquer falha = anônimo
        return AnonymousUser(), None, None


class JWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        raw = _raw_token(scope)
        user, issued, expires = await _user_for(raw) if raw else (AnonymousUser(), None, None)
        # O consumidor confere de novo a cada mensagem: socket aberto não sobrevive à troca de senha nem ao
        # vencimento do token (rodada 1, P-9).
        scope["user"], scope["token_iat"], scope["token_exp"] = user, issued, expires
        return await self.app(scope, receive, send)
