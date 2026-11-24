"""Esqueci minha senha: link por e-mail, sem revelar quem tem conta."""
import pathlib

from django.core import mail
from rest_framework.test import APIClient

from starrp.models import PasswordResetRequest

URL = "/api/v1/auth/password-reset/"


def _ask(email):
    return APIClient(SERVER_NAME="localhost").post(URL, {"email": email}, format="json")


def test_link_do_email_redefine_a_senha(ctx):
    seller = ctx.user("vend", "seller")
    seller.email = "vend@loja.com"
    seller.save(update_fields=["email"])

    assert _ask("VEND@loja.com").status_code == 200

    message = mail.outbox[-1]
    assert message.to == ["vend@loja.com"] and "vend" in message.body
    token = message.body.split("/redefinir-senha#token=")[1].split()[0]
    assert not PasswordResetRequest.objects.filter(token_hash=token).exists()  # só o hash no banco
    changed = APIClient(SERVER_NAME="localhost").post(
        f"{URL}confirm/", {"token": token, "password": "Nova-Senha-Forte-77"}, format="json")
    assert changed.status_code == 200, changed.json()
    seller.refresh_from_db()
    assert seller.check_password("Nova-Senha-Forte-77")


def test_email_desconhecido_responde_igual_e_nao_envia(ctx):
    known, unknown = _ask(ctx.admin.email or "a@b.com"), _ask("ninguem@nada.com")
    assert unknown.status_code == known.status_code == 200 and unknown.json() == known.json()
    assert not [m for m in mail.outbox if "ninguem@nada.com" in m.to]


def test_mesmo_email_em_dois_logins_recebe_um_link_de_cada(ctx):
    for name in ("um", "dois"):
        user = ctx.user(name, "seller")
        user.email = "dono@loja.com"
        user.save(update_fields=["email"])
    _ask("dono@loja.com")
    assert len([m for m in mail.outbox if m.to == ["dono@loja.com"]]) == 2


def test_email_fora_do_ar_nao_derruba_a_resposta(ctx, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("smtp fora")

    ctx.admin.email = "dono@loja.com"
    ctx.admin.save(update_fields=["email"])
    monkeypatch.setattr("starrp.services.password_reset.send_mail", broken)
    assert _ask("dono@loja.com").status_code == 200


def test_limite_de_login_do_nginx_vem_antes_da_regex_da_api():
    """No nginx vale a primeira regex que casa: depois da de /api/, o limite de login nunca era aplicado."""
    template = pathlib.Path(__file__).resolve().parents[3] / "docker/nginx/templates/starrp.conf.template"
    text = template.read_text(encoding="utf-8")
    assert text.index("location ~ ^/api/v1/auth/(login|password-reset)/") < text.index("location ~ ^/(api|static)/")
