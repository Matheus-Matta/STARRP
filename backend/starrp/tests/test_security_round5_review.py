"""Rodada 5 (docs/SEGURANCA.md): o que ainda furava ou quebrava nas correções da rodada 4."""
from decimal import Decimal

import pytest

from starrp.core.errors import StateConflict
from starrp.models import CashMovement, Coupon, Customer, FiscalConfig, Invoice, Payment, Sale, Terminal
from starrp.services import cash, checkout, fiscal_emission
from starrp.tests.test_security_round4_money import _boot, _off, _pay, _sale


def _limit(ctx, code, percent):
    role = ctx.user_role(code)
    role.max_discount_percent = Decimal(percent)
    role.save()


def _tv(ctx):
    return ctx.product(name="TV", price="1000.00", track_stock=False)


def test_descontos_somados_sao_marcados_na_venda_pronta(ctx):
    _limit(ctx, "cashier", "10")
    api = ctx.client(ctx.user("caixa", "cashier"))
    _boot(api)
    body = _off(ctx, _tv(ctx), "900.00", discount="90.00")
    body["payments"][0].update(amount="810.00", tendered="810.00")
    sale = Sale.all_objects.get(pk=api.post("/api/v1/pdv/offline-sales/", body, format="json").json()["id"])
    assert sale.total == 810 and sale.metafields["_approval_unverified"]


def test_pedido_guardado_com_descontos_somados_fica_no_limite_e_conclui(ctx):
    _limit(ctx, "cashier", "10")
    api = ctx.client(ctx.user("caixa", "cashier"))
    _boot(api)
    body = _off(ctx, _tv(ctx), "1000.00", park=True, discount="90.00")
    body.pop("payments")
    body["items"][0]["discount"] = "100"
    sale = Sale.all_objects.get(pk=api.post("/api/v1/pdv/offline-sales/", body, format="json").json()["id"])
    assert sale.total == 900
    api.post(f"/api/v1/sales/{sale.pk}/resume/", {}, format="json")
    assert _pay(ctx, api, sale.pk, sale.total, "cash").status_code == 200


def test_pedido_refeito_no_pdv_nao_herda_o_turno_de_quem_montou(ctx):
    ctx.require_cash()
    v = _tv(ctx)
    a, b = ctx.user("caixaa", "cashier"), ctx.user("caixab", "cashier")
    ctx.link(a)
    _boot(ctx.client(a))
    session = cash.open_session(ctx.register, a, Decimal("0"))
    sid = _sale(ctx, ctx.client(a), v)
    ctx.client(a).post(f"/api/v1/sales/{sid}/park/", {}, format="json")
    cash.close_session(session, a, Decimal("0"))
    response = ctx.client(b).post("/api/v1/pdv/offline-sales/", _off(ctx, v, "1000.00", replaces=sid), format="json")
    assert response.status_code == 409 and cash.expected_cash(session) == 0


def test_numero_de_nota_rejeitada_nao_volta_para_outra_venda(ctx):
    v = ctx.product(name="TV", price="10.00", track_stock=False)
    api = ctx.client(ctx.user("caixa", "cashier"))
    _boot(api)
    config = FiscalConfig.all_objects.create(account=ctx.account, name="x", cnpj="11222333000181")
    ctx.store.fiscal_config = config
    ctx.store.save()
    series = fiscal_emission.terminal_series(config, Terminal.all_objects.get(installation_id="pc-1"), "65")
    note = {"document_model": "65", "series": series.series, "number": 1, "result": {"situacao": "rejeitada"}}
    assert api.post("/api/v1/pdv/offline-sales/", {**_off(ctx, v, "10.00"), "invoice": note}, format="json").status_code == 201
    series.refresh_from_db()
    assert series.next_number == 2 and Invoice.all_objects.get().status == "rejected"


def test_pagamento_de_turno_esperando_aprovacao_nao_se_reescreve(ctx):
    ctx.require_cash()
    a = ctx.user("caixaa", "cashier")
    ctx.link(a)
    api = ctx.client(a)
    session = cash.open_session(ctx.register, a, Decimal("0"))
    sid = _sale(ctx, api, _tv(ctx), "2")
    api.post(f"/api/v1/sales/{sid}/payments/", {"method": str(ctx.methods["cash"].pk), "amount": "1000",
                                                "tendered": "1000"}, format="json")
    assert cash.close_session(session, a, Decimal("900")).status == "pending_approval"
    with pytest.raises(StateConflict):
        checkout.remove_payment(Payment.all_objects.get(sale_id=sid), a)
    assert CashMovement.all_objects.get().status == "approved"


def test_motivo_do_fechamento_nao_entrega_a_diferenca(ctx):
    ctx.require_cash()
    a = ctx.user("caixaa", "cashier")
    ctx.link(a)
    api = ctx.client(a)
    _boot(api)
    session = cash.open_session(ctx.register, a, Decimal("0"))
    cash.close_session(session, a, Decimal("0"))
    api.post("/api/v1/pdv/offline-sales/", _off(ctx, _tv(ctx), "1000.00", cash_session=str(session.pk)), format="json")
    session.refresh_from_db()
    assert "1000" in session.approval_reason
    for path in ("", "report/", "statement/", "history/"):
        response = api.get(f"/api/v1/cash/sessions/{session.pk}/{path}")
        assert response.status_code == 200 and "diferença agora" not in response.content.decode()


def test_item_antigo_autorizado_pelo_gerente_conclui(ctx):
    _limit(ctx, "cashier", "5")
    manager = ctx.user("ger", "manager")
    api = ctx.client(ctx.user("caixaa", "cashier"))
    sid = _sale(ctx, api, _tv(ctx))
    item = Sale.all_objects.get(pk=sid).items.get()
    item.discount, item.total, item.metafields = 100, 900, {"_approved_by": manager.pk}
    item.save()
    Sale.all_objects.filter(pk=sid).update(subtotal=900, total=900)
    assert _pay(ctx, api, sid, "900").status_code == 200


def test_primeira_compra_vale_para_cliente_identificado_sem_cpf(ctx):
    Coupon.all_objects.create(account=ctx.account, code="BEM", kind=Coupon.Kind.PERCENT, value=10, first_purchase_only=True)
    customer = Customer.all_objects.create(account=ctx.account, name="Estrangeiro")
    api = ctx.client()
    sid = api.post("/api/v1/sales/", {"customer": str(customer.pk)}, format="json").json()["id"]
    api.post(f"/api/v1/sales/{sid}/items/", {"variant": str(_tv(ctx).pk)}, format="json")
    assert api.post(f"/api/v1/sales/{sid}/coupon/", {"code": "BEM"}, format="json").status_code == 200
