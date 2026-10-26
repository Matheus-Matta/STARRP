"""Abertura do caixa com conferência cega (padrão do StarChef)."""
from decimal import Decimal

from starrp.models import CashSession, Store
from starrp.services import cash


def _sell(api, ctx, variant):
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    return api.post(f"/api/v1/sales/{sale['id']}/checkout/", {"payments": [
        {"method": str(ctx.methods["pix"].pk), "amount": "10.00", "nsu": "1"}]}, format="json")


def test_abertura_confere_com_o_que_o_ultimo_fechamento_deixou(ctx):
    ctx.require_cash()
    Store.all_objects.filter(pk=ctx.store.pk).update(cash_action_password="")
    ctx.store.set_cash_action_password("gerente9")
    ctx.store.save()
    variant = ctx.product(name="Bala", price="10.00", track_stock=False)
    cashier = ctx.user("caixa1", "cashier")
    ctx.register.operators.add(cashier)
    api = ctx.client(cashier)
    url = "/api/v1/cash/sessions/"
    body = {"register": str(ctx.register.pk)}

    blocked = _sell(api, ctx, variant)  # PDV sem turno aberto: não cobra (nem PIX)
    first = api.post(url, {**body, "opening_amount": "150", "notes": "Troco do cofre"}, format="json").json()
    twice = api.post(url, {**body, "opening_amount": "150"}, format="json")
    cash.close_session(CashSession.all_objects.get(pk=first["id"]), cashier, Decimal("150"))

    wrong = api.post(url, {**body, "opening_amount": "120"}, format="json").json()  # faltam 30 na gaveta
    held = _sell(api, ctx, variant)
    boot = api.post("/api/v1/pdv/bootstrap/", {"installation_id": "t1"}, format="json").json()
    no_auth = api.post(f"{url}{wrong['id']}/approve-opening/", {}, format="json")
    ok = api.post(f"{url}{wrong['id']}/approve-opening/", {"reason": "Conferido com o cofre",
                                                          "approval": {"cash_password": "gerente9"}}, format="json")
    sold = _sell(api, ctx, variant)

    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "cash_session_required"
    assert first["status"] == "open" and first["opening_is_initial"] is True and first["opening_notes"] == "Troco do cofre"
    assert twice.status_code == 409  # já tem turno em andamento
    assert wrong["status"] == "pending_opening" and wrong["opening_difference"] is None  # cego para o operador
    assert held.status_code == 409 and boot["cash_session"]["status"] == "pending_opening"
    assert no_auth.status_code == 403 and ok.json()["status"] == "open"
    assert sold.status_code == 200


def test_abertura_que_bate_abre_direto_e_o_gerente_ve_a_diferenca(ctx):
    manager = ctx.user("gerente1", "manager")
    cashier = ctx.user("caixa1", "cashier")
    ctx.register.operators.add(cashier)
    first = cash.open_session(ctx.register, cashier, Decimal("200"))
    cash.close_session(first, cashier, Decimal("200"))
    same = cash.open_session(ctx.register, cashier, Decimal("200"))
    cash.close_session(same, cashier, Decimal("200"))
    other = cash.open_session(ctx.register, cashier, Decimal("210"))
    seen = ctx.client(manager).get(f"/api/v1/cash/sessions/{other.pk}/").json()

    assert same.status == CashSession.Status.OPEN and same.opening_expected == Decimal("200")
    assert other.status == CashSession.Status.PENDING_OPENING
    assert Decimal(seen["opening_difference"]) == Decimal("10.00") and Decimal(seen["opening_expected"]) == Decimal("200.00")
