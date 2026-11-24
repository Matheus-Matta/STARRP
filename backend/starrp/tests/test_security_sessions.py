"""Sessão por cookie e troca de senha (docs/SEGURANCA.md S-12)."""
import hashlib
import time
import pytest
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from starrp.models import PasswordResetRequest


def _browser(ctx):
    client = APIClient(HTTP_X_AUTH_TRANSPORT="cookie", SERVER_NAME="localhost")
    response = client.post("/api/v1/auth/login/", {"username": ctx.admin.username, "password": "senha123"},
                           format="json")
    assert response.status_code == 200
    return client


def test_gravacao_com_cookie_vinda_de_outro_site_e_recusada(ctx):
    browser = _browser(ctx)

    attack = browser.post("/api/v1/catalog/brands/", {"name": "CSRF"}, format="json", HTTP_ORIGIN="https://evil.example")
    own = browser.post("/api/v1/catalog/brands/", {"name": "Legítima"}, format="json", HTTP_ORIGIN="http://localhost")
    no_origin = browser.post("/api/v1/catalog/brands/", {"name": "Sem origem"}, format="json")

    assert attack.status_code == 403 and attack.json()["error"]["code"] == "csrf_origin"
    assert own.status_code == 201, own.json()
    assert no_origin.status_code == 201  # não é navegador de outro site (Bearer/servidor/teste)


def test_bearer_do_pdv_nao_e_afetado_pela_origem(ctx):
    response = ctx.client().post("/api/v1/catalog/brands/", {"name": "PDV"}, format="json",
                                 HTTP_ORIGIN="https://qualquer.example")
    assert response.status_code == 201


def test_trocar_a_senha_derruba_o_token_que_ja_estava_aberto(ctx):
    seller = ctx.user("vend", "seller")
    stolen = ctx.client(seller)  # token emitido antes da troca
    assert stolen.get("/api/v1/me/").status_code == 200
    time.sleep(1.1)  # o iat do token é em segundos

    changed = ctx.client().patch(f"/api/v1/users/{seller.profile.pk}/", {"password": "Nova-Senha-Forte-77"},
                                 format="json")

    assert changed.status_code == 200, changed.json()
    assert stolen.get("/api/v1/me/").status_code == 401
    assert ctx.client(seller).get("/api/v1/me/").status_code == 200  # login novo funciona


def test_redefinir_senha_exige_senha_forte_e_encerra_sessoes(ctx):
    token = "token-de-teste-123"
    PasswordResetRequest.objects.create(user=ctx.admin, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                        expires_at=timezone.now() + timedelta(minutes=30))
    open_session = ctx.client()
    time.sleep(1.1)
    api = APIClient(SERVER_NAME="localhost")

    weak = api.post("/api/v1/auth/password-reset/confirm/", {"token": token, "password": "123456"}, format="json")
    strong = api.post("/api/v1/auth/password-reset/confirm/", {"token": token, "password": "Nova-Senha-Forte-77"},
                      format="json")

    assert weak.status_code == 400
    assert strong.status_code == 200, strong.json()
    assert open_session.get("/api/v1/me/").status_code == 401


# ── S-15: WebSocket ───────────────────────────────────────────────────────────────────────────────────

def test_websocket_ignora_token_na_url_e_le_so_o_cookie(settings):
    from starrp.core.ws_auth import _raw_token

    by_query = {"query_string": b"token=abc.def.ghi", "headers": []}
    by_cookie = {"query_string": b"", "headers": [(b"cookie", f"{settings.JWT_AUTH_COOKIE}=xyz".encode())]}

    assert _raw_token(by_query) is None
    assert _raw_token(by_cookie) == "xyz"


def test_websocket_confere_a_origem():
    from channels.security.websocket import OriginValidator

    from config.asgi import application

    assert isinstance(application.application_mapping["websocket"], OriginValidator)


@pytest.mark.django_db(transaction=True)
def test_websocket_com_token_de_antes_da_troca_de_senha_e_recusado(settings):
    """Rodada 1 (P-9): o socket não conferia `sessions_revoked_at`."""
    from asgiref.sync import async_to_sync
    from channels.testing import WebsocketCommunicator
    from rest_framework_simplejwt.tokens import RefreshToken

    from config.asgi import application
    from starrp.services import sessions
    from starrp.tests.conftest import Ctx

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    ctx = Ctx("Loja WS")
    ctx.account.extra_modules = ["cosmos"]
    ctx.account.save(update_fields=["extra_modules"])
    token = str(RefreshToken.for_user(ctx.admin).access_token)
    time.sleep(1.1)
    sessions.revoke_all(ctx.admin)

    async def connect():
        communicator = WebsocketCommunicator(application, "/api/v1/ws/cosmos/", headers=[
            (b"origin", b"http://localhost"), (b"cookie", f"{settings.JWT_AUTH_COOKIE}={token}".encode())])
        connected, code = await communicator.connect()
        await communicator.disconnect()
        return connected, code

    assert async_to_sync(connect)() == (False, 4401)
