"""Autenticação do WebSocket: o mesmo JWT da API, pelo cookie httpOnly (retaguarda web) ou por
`?token=` (cliente sem cookie). Sem token válido, `scope["user"]` fica anônimo e o consumidor fecha."""
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


def _raw_token(scope):
    query = parse_qs(scope.get("query_string", b"").decode())
    if query.get("token"):
        return query["token"][0]
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            cookie = SimpleCookie()
            cookie.load(value.decode())
            if settings.JWT_AUTH_COOKIE in cookie:
                return cookie[settings.JWT_AUTH_COOKIE].value
    return None


@database_sync_to_async
def _user_for(raw):
    auth = JWTAuthentication()
    try:
        return auth.get_user(auth.get_validated_token(raw))
    except (InvalidToken, TokenError, Exception):  # noqa: BLE001 — qualquer falha = anônimo
        return AnonymousUser()


class JWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        raw = _raw_token(scope)
        scope["user"] = await _user_for(raw) if raw else AnonymousUser()
        return await self.app(scope, receive, send)
