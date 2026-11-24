"""Força bruta e oráculo na autorização do PDV (docs/SEGURANCA.md S-04)."""
from django.contrib.auth import get_user_model

from starrp.tests.conftest import Ctx

AUTHORIZE = "/api/v1/pdv/authorize/"


def _ask(api, username, password):
    return api.post(AUTHORIZE, {"code": "sales.cancel", "approval": {"username": username, "password": password}},
                    format="json")


def test_autorizacao_limita_tentativas_por_alvo(ctx):
    cashier = ctx.user("caixa", "cashier")
    ctx.user("gerente", "manager")
    api = ctx.client(cashier)

    codes = [_ask(api, "gerente", f"errada{i}").status_code for i in range(5)]
    blocked = _ask(api, "gerente", "senha123")  # até a certa fica barrada na janela

    assert all(code == 403 for code in codes), codes
    assert blocked.status_code == 429


def test_superusuario_e_usuario_de_outra_conta_nao_autorizam_e_a_resposta_e_igual(ctx):
    User = get_user_model()
    User.objects.create_superuser("suporte", password="SuperSenha-1", email="s@x.com")
    other = Ctx("Outra Loja")
    outsider = other.user("gerente_b", "manager")
    cashier = ctx.user("caixa", "cashier")
    api = ctx.client(cashier)

    superuser = _ask(api, "suporte", "SuperSenha-1")
    foreign = _ask(api, outsider.username, "senha123")
    wrong = _ask(api, "nao-existe", "x")

    assert superuser.status_code == foreign.status_code == wrong.status_code == 403
    messages = {r.json()["error"]["message"] for r in (superuser, foreign, wrong)}
    assert len(messages) == 1, messages  # nada diz que a credencial existe em outro lugar


def test_desbloqueio_da_tela_limita_tentativas(ctx):
    cashier = ctx.user("caixa", "cashier")
    api = ctx.client(cashier)
    ctx.store.set_cash_action_password("2468")
    ctx.store.save()

    codes = [api.post("/api/v1/pdv/unlock/", {"password": f"{i:04d}"}, format="json").status_code for i in range(25)]

    assert 429 in codes
    assert codes.index(429) <= 20


def test_autorizacao_certa_continua_funcionando(ctx):
    cashier = ctx.user("caixa", "cashier")
    ctx.user("gerente", "manager")
    response = _ask(ctx.client(cashier), "gerente", "senha123")
    assert response.status_code == 200, response.json()


def test_caixa_que_erra_de_proposito_nao_trava_o_gerente_para_os_outros(ctx):
    """Rodada 1 (P-10): o bloqueio é de quem tenta, não do gerente."""
    ctx.user("gerente", "manager")
    attacker = ctx.client(ctx.user("caixa", "cashier"))
    other = ctx.client(ctx.user("caixa2", "cashier"))

    for i in range(6):
        _ask(attacker, "gerente", f"errada{i}")

    assert _ask(attacker, "gerente", "senha123").status_code == 429
    assert _ask(other, "gerente", "senha123").status_code == 200


def test_senha_certa_de_quem_nao_tem_a_permissao_da_a_mesma_resposta(ctx):
    """Rodada 1 (P-11): "não tem permissão" confirmaria que a senha do colega está certa."""
    ctx.user("colega", "seller")
    api = ctx.client(ctx.user("caixa", "cashier"))

    right = _ask(api, "colega", "senha123")
    wrong = _ask(api, "colega", "errada")

    assert right.status_code == wrong.status_code == 403
    assert right.json()["error"]["message"] == wrong.json()["error"]["message"]
