"""Sangria e suprimento passam por aprovação: gerente, usuário/senha do gerente ou a senha de ações
do caixa da filial (como no StarChef). Pendente não mexe na gaveta e trava o fechamento."""
from decimal import Decimal

import pytest

from starrp.services import cash


@pytest.fixture
def turno(ctx):
    cashier = ctx.user("caixa1", "cashier")
    ctx.link(cashier)
    ctx.store.set_cash_action_password("4321")
    ctx.store.save(update_fields=["cash_action_password"])
    api = ctx.client(cashier)
    sid = api.post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                   format="json").json()["id"]
    return api, sid, cashier


def _move(api, sid, **body):
    return api.post(f"/api/v1/cash/sessions/{sid}/movements/", body, format="json")


def test_operador_lanca_pendente_e_a_gaveta_so_muda_depois_de_aprovar(ctx, turno):
    api, sid, _ = turno
    manager = ctx.user("gerente1", "manager")
    supply = _move(api, sid, kind="supply", amount="30", reason="Troco").json()
    withdrawal = _move(api, sid, kind="withdrawal", amount="50", reason="Cofre").json()
    session = cash.CashSession.all_objects.get(pk=sid)
    before = cash.expected_cash(session)
    blocked = api.post(f"/api/v1/cash/sessions/{sid}/close/", {"counted_amount": "80"}, format="json")

    boss = ctx.client(manager)
    ok = boss.post(f"/api/v1/cash/movements/{withdrawal['id']}/approve/", {"reason": "Depósito no banco"}, format="json")
    no = boss.post(f"/api/v1/cash/movements/{supply['id']}/reject/", {"reason": "Não chegou troco"}, format="json")

    assert supply["status"] == withdrawal["status"] == "pending"
    assert before == Decimal("100.00")  # pendente não entra nem sai da gaveta
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "movements_pending"
    assert ok.json()["status"] == "approved" and ok.json()["approved_by_name"] and ok.json()["approval_reason"]
    assert no.json()["status"] == "cancelled"
    assert cash.expected_cash(session) == Decimal("50.00")


def test_senha_do_caixa_da_filial_aprova_no_ato_e_senha_errada_pede_de_novo(turno):
    api, sid, _ = turno
    wrong = _move(api, sid, kind="withdrawal", amount="20", approval={"cash_password": "0000"})
    right = _move(api, sid, kind="withdrawal", amount="20", approval={"cash_password": "4321"})

    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "approval_required"
    assert right.status_code == 201 and right.json()["status"] == "approved"
    assert right.json()["authorized_by_password"] is True and right.json()["approved_by_name"] == "Senha do caixa"


def test_aprovar_depois_sem_permissao_exige_autorizacao(turno):
    api, sid, _ = turno
    pending = _move(api, sid, kind="supply", amount="10").json()
    url = f"/api/v1/cash/movements/{pending['id']}/approve/"

    alone = api.post(url, {}, format="json")
    with_password = api.post(url, {"reason": "Gerente ao telefone", "approval": {"cash_password": "4321"}}, format="json")
    again = api.post(url, {"approval": {"cash_password": "4321"}}, format="json")

    assert alone.status_code == 403 and alone.json()["error"]["code"] == "approval_required"
    assert with_password.json()["status"] == "approved"
    assert again.status_code == 409  # já decidido: não aprova duas vezes


def test_operador_desiste_do_que_lancou_mas_nao_do_dos_outros(ctx, turno):
    api, sid, _ = turno
    other = ctx.user("caixa2", "cashier")
    mine = _move(api, sid, kind="supply", amount="10").json()

    stranger = ctx.client(other).post(f"/api/v1/cash/movements/{mine['id']}/reject/", {}, format="json")
    gave_up = api.post(f"/api/v1/cash/movements/{mine['id']}/reject/", {"reason": "Lancei errado"}, format="json")

    assert stranger.status_code == 403
    assert gave_up.json()["status"] == "cancelled"


def test_sangria_pendente_conta_no_limite_da_gaveta(turno):
    api, sid, _ = turno
    first = _move(api, sid, kind="withdrawal", amount="70")
    second = _move(api, sid, kind="withdrawal", amount="40")

    assert first.status_code == 201
    assert second.status_code == 422  # 70 já reservados de 100


def test_fechamento_com_diferenca_aprovado_pela_senha_da_filial(turno):
    api, sid, _ = turno
    closed = api.post(f"/api/v1/cash/sessions/{sid}/close/", {"counted_amount": "90"}, format="json").json()
    no_reason = api.post(f"/api/v1/cash/sessions/{sid}/approve/", {"approval": {"cash_password": "4321"}}, format="json")
    alone = api.post(f"/api/v1/cash/sessions/{sid}/approve/", {"reason": "Troco errado"}, format="json")
    approved = api.post(f"/api/v1/cash/sessions/{sid}/approve/",
                        {"reason": "Troco errado", "approval": {"cash_password": "4321"}}, format="json")

    assert closed["status"] == "pending_approval"
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "reason_required"
    assert alone.status_code == 403 and alone.json()["error"]["code"] == "approval_required"
    assert approved.json()["status"] == "closed"
