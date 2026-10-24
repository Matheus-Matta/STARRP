"""Caixa com operadores vinculados e fechamento cego (a gaveta não aparece para o operador)."""
from decimal import Decimal


def test_so_quem_esta_vinculado_abre_e_o_gerente_assume_qualquer_caixa(ctx):
    cashier = ctx.user("caixa1", "cashier")
    other = ctx.user("caixa2", "cashier")
    manager = ctx.user("gerente1", "manager")
    url = "/api/v1/cash/sessions/"
    body = {"register": str(ctx.register.pk), "opening_amount": "100"}

    blocked = ctx.client(cashier).post(url, body, format="json")
    ctx.register.operators.add(cashier)
    boot_cashier = ctx.client(cashier).post("/api/v1/pdv/bootstrap/", {"installation_id": "t1"}, format="json").json()
    boot_other = ctx.client(other).post("/api/v1/pdv/bootstrap/", {"installation_id": "t2"}, format="json").json()
    opened = ctx.client(cashier).post(url, body, format="json")
    sid = opened.json()["id"]
    stranger_close = ctx.client(other).post(f"{url}{sid}/close/", {"counted_amount": "100"}, format="json")
    manager_move = ctx.client(manager).post(f"{url}{sid}/movements/", {"kind": "supply", "amount": "20"}, format="json")

    assert blocked.status_code == 403 and "vinculado" in blocked.json()["error"]["message"]
    assert [r["id"] for r in boot_cashier["cash_registers"]] == [str(ctx.register.pk)]
    assert boot_other["cash_registers"] == []  # não vinculado: o PDV não oferece o caixa
    assert opened.status_code == 201 and stranger_close.status_code == 403
    assert manager_move.status_code == 200  # gerente assume qualquer caixa


def test_fechamento_cego_o_operador_nao_ve_a_gaveta(ctx):
    cashier = ctx.user("caixa1", "cashier")
    manager = ctx.user("gerente1", "manager")
    ctx.register.operators.add(cashier)
    api = ctx.client(cashier)
    sid = api.post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                   format="json").json()["id"]
    api.post(f"/api/v1/cash/sessions/{sid}/movements/", {"kind": "supply", "amount": "50"}, format="json")

    mine = api.get(f"/api/v1/cash/sessions/{sid}/").json()
    report = api.get(f"/api/v1/cash/sessions/{sid}/report/").json()
    closed = api.post(f"/api/v1/cash/sessions/{sid}/close/", {"counted_amount": "140"}, format="json").json()
    boss = ctx.client(manager).get(f"/api/v1/cash/sessions/{sid}/").json()

    assert mine["expected_now"] is None and mine["blind"] is True
    assert set(report["drawer"]) == {"opening", "counted"} and report["blind"] is True
    assert closed["difference"] is None and closed["status"] == "pending_approval"  # faltou 10: vai ao gerente
    assert Decimal(boss["difference"]) == Decimal("-10.00") and Decimal(boss["expected_now"]) == Decimal("150.00")
