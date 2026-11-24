"""Contrato de regras do PDV: os casos de `shared/pdv-rules.cases.json` contra os services DE
VERDADE (caixa e checkout). O desktop roda os mesmos casos contra `pdv/rules.ts`
(`npm --prefix desktop run test:rules`). Os dois precisam dar o MESMO resultado (ok ou o mesmo
código de erro): é o que garante que a venda/turno feito no PC sem servidor não volta recusado.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from rest_framework.exceptions import APIException

from starrp.models import CashRegister, PaymentMethod, StoreRule
from starrp.services import cash, checkout, sales

CASES = json.loads((Path(__file__).resolve().parents[3] / "shared" / "pdv-rules.cases.json").read_text(encoding="utf-8"))


def _code(action):
    try:
        action()
    except APIException as error:
        codes = error.get_codes()
        return codes if isinstance(codes, str) else str(codes)
    return "ok"


def _cases(kind):
    return [pytest.param(case, id=case["name"]) for case in CASES[kind]]


@pytest.fixture
def cashier(ctx):
    user = ctx.user("caixa-paridade", "cashier")
    ctx.link(user)
    return user


@pytest.mark.parametrize("case", _cases("open"))
def test_abertura(ctx, cashier, case):
    given = case["given"]
    register = ctx.register
    if given["register"] == "inactive":
        CashRegister.all_objects.filter(pk=register.pk).update(is_active=False)
        register.refresh_from_db()
    elif given["register"] == "not_linked":
        register = CashRegister.all_objects.create(account=ctx.account, store=ctx.store, name="Caixa 99")
    elif given["register"] == "busy":
        cash.open_session(register, ctx.admin, Decimal("0"))  # outro operador (gerente) já abriu
    if given.get("has_session"):
        cash.open_session(register, cashier, Decimal("0"))
    assert _code(lambda: cash.open_session(register, cashier, Decimal(given["amount"]))) == case["expect"]


@pytest.mark.parametrize("case", _cases("movement"))
def test_sangria_suprimento(ctx, cashier, case):
    given = case["given"]
    session = cash.open_session(ctx.register, cashier, Decimal(given["drawer"]))
    if given.get("closed"):
        session = cash.close_session(session, cashier, Decimal(given["drawer"]))
    result = _code(lambda: cash.add_movement(session, cashier, given["kind"], Decimal(given["amount"]), "paridade"))
    assert result == case["expect"]


@pytest.mark.parametrize("case", _cases("close"))
def test_fechamento(ctx, cashier, case):
    given = case["given"]
    session = cash.open_session(ctx.register, cashier, Decimal("50.00"))
    for _ in range(given.get("pending", 0)):
        cash.add_movement(session, cashier, "supply", Decimal("1.00"), "pendente")  # caixa não aprova: fica pendente
    if given.get("closed"):
        cash.close_session(session, cashier, Decimal("50.00"))
    assert _code(lambda: cash.close_session(session, cashier, Decimal(given["counted"]))) == case["expect"]


@pytest.mark.parametrize("case", _cases("sale"))
def test_venda(ctx, cashier, case):
    given = case["given"]
    StoreRule.all_objects.filter(pk=ctx.store.rule_id).update(
        require_open_cash_session=bool(given.get("require_cash")), require_seller=bool(given.get("require_seller")),
        require_payment_reference=bool(given.get("require_reference")))
    ctx.store.refresh_from_db()
    variant = ctx.product(name="Item", price=given["price"], track_stock=False)
    session = None if given.get("no_session") else cash.open_session(ctx.register, cashier, Decimal("0"))
    sale = sales.create(ctx.store, cashier, seller=cashier if given.get("seller") else None, cash_session=session)

    def run():
        for quantity in given["items"]:
            sales.add_item(sale, variant, Decimal(quantity), cashier)
        rows = []
        for p in given["payments"]:
            method = PaymentMethod.all_objects.filter(account=ctx.account, kind=p["kind"]).first()
            method.max_installments = p.get("max_installments", 1)
            method.requires_reference = bool(p.get("requires_reference"))
            method.is_active = True
            method.save()
            rows.append({"method": method, "amount": Decimal(p["amount"]),
                         "tendered": Decimal(p["tendered"]) if p.get("tendered") else None,
                         "installments": p.get("installments", 1), "nsu": p.get("nsu", "")})
        sale.refresh_from_db()
        checkout.checkout(sale, cashier, rows)

    assert _code(run) == case["expect"]
