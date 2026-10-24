"""Financeiro integrado à operação: caixa → cofre, PIX/cartão → banco, DRE, fluxo e comissões."""
from decimal import Decimal

import pytest
from django.utils import timezone

from starrp.models import (
    CashSession, FinancialAccount, FinancialCategory, FinancialTitle, FinancialTransaction, PaymentMethod,
    KitComponent, StockMovement,
)
from starrp.services import cash, finance, stock
from starrp.services.cash_flow import balances
from starrp.services.finance_setup import vault_for


@pytest.fixture
def fin(ctx):
    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    ctx.bank = FinancialAccount.all_objects.get(account=ctx.account, name="Banco principal")
    return ctx


def _sell(ctx, product, payments, quantity="1", **sale_fields):
    api = ctx.client()
    sale = api.post("/api/v1/sales/", sale_fields, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk), "quantity": quantity}, format="json")
    response = api.post(f"/api/v1/sales/{sale['id']}/checkout/", {"payments": payments}, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def _balance(account):
    return next(row["balance"] for row in balances(account.account, None)["accounts"] if row["id"] == str(account.pk))


def test_conta_nova_ja_tem_plano_de_contas_cofre_e_pix_no_banco(fin):
    keys = set(FinancialCategory.all_objects.filter(account=fin.account).values_list("system_key", flat=True))
    pix = PaymentMethod.all_objects.get(account=fin.account, kind="pix")

    assert {"sales", "card_fees", "commissions", "cash_shortage", "suppliers", "rent"} <= keys
    assert vault_for(fin.store).kind == "cash"
    assert pix.financial_account == fin.bank


def test_ciclo_do_caixa_chega_ao_cofre_e_o_fechamento_conta_a_historia(fin):
    """Troco 100 sai do cofre; venda 50; sangria 30 volta; contado 119 (faltou 1) entra após aprovação."""
    product = fin.product(price="50.00", track_stock=False)
    session = cash.open_session(fin.register, fin.admin, Decimal("100"))
    _sell(fin, product, [{"nsu": "000123", "method": str(fin.methods["cash"].pk), "amount": "50.00"}])
    cash.add_movement(session, fin.admin, "withdrawal", Decimal("30"), "Cofre")
    closed = cash.close_session(session, fin.admin, Decimal("119"))
    vault = vault_for(fin.store)
    before_approval = _balance(vault)
    cash.approve_closing(closed, fin.admin, "Troco errado")

    report = fin.client().get(f"/api/v1/cash/sessions/{session.pk}/report/").json()

    assert closed.status == CashSession.Status.PENDING_APPROVAL
    assert before_approval == Decimal("-70")  # -100 de troco + 30 de sangria
    assert _balance(vault) == Decimal("49")  # 50 vendidos - 1 de quebra
    assert report["sales"]["count"] == 1 and report["sales"]["total"] == "50.00"
    assert report["drawer"]["withdrawal"] == "30.00"
    assert (report["drawer"]["expected"], report["drawer"]["counted"], report["drawer"]["difference"]) == (
        "120.00", "119.00", "-1.00")
    assert report["session"]["approved_by"]


def test_pix_entra_no_banco_com_taxa_cartao_vira_a_receber_e_cancelar_estorna(fin):
    PaymentMethod.all_objects.filter(account=fin.account, kind="pix").update(fee_percent=Decimal("1"))
    PaymentMethod.all_objects.filter(account=fin.account, kind="credit_card").update(fee_percent=Decimal("3"))
    product = fin.product(price="100.00", track_stock=False)

    pix_sale = _sell(fin, product, [{"nsu": "000123", "method": str(fin.methods["pix"].pk), "amount": "100.00"}])
    card_sale = _sell(fin, product, [{"nsu": "000123", "method": str(fin.methods["credit_card"].pk), "amount": "100.00"}])

    assert _balance(fin.bank) == Decimal("99.00")
    title = FinancialTitle.all_objects.get(sale_id=card_sale["id"])
    assert (title.kind, title.total, title.category.system_key) == ("receivable", Decimal("97.00"), "sales")

    fin.client().post(f"/api/v1/sales/{pix_sale['id']}/cancel/", {"reason": "teste"}, format="json")
    assert _balance(fin.bank) == Decimal("0.00")
    assert FinancialTransaction.all_objects.filter(sale_id=pix_sale["id"], reversal_of__isnull=False).count() == 2


def test_dre_fecha_receita_cmv_taxas_comissao_devolucao_e_despesas(fin):
    """2 un × 100 (custo 40), desconto 20, PIX 1%, comissão 5%, devolve 1 un, aluguel 50."""
    PaymentMethod.all_objects.filter(account=fin.account, kind="pix").update(fee_percent=Decimal("1"))
    seller = fin.user("vendedora", "seller", is_seller=True, commission_percent=Decimal("5"))
    customer = fin.client().post("/api/v1/customers/", {"name": "Ana"}, format="json").json()
    product = fin.product(price="100.00")
    stock.move(product, stock.default_warehouse(fin.store), Decimal("5"), StockMovement.Kind.PURCHASE,
               unit_cost=Decimal("40"))
    api = fin.client()
    sale = api.post("/api/v1/sales/", {"seller": seller.pk, "customer": customer["id"]}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk), "quantity": "2"}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/discount/", {"amount": "20.00"}, format="json")
    sale = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                    {"payments": [{"nsu": "000123", "method": str(fin.methods["pix"].pk), "amount": "180.00"}]}, format="json").json()
    created = api.post(f"/api/v1/sales/{sale['id']}/returns/", {
        "items": [{"sale_item": sale["items"][0]["id"], "quantity": "1"}], "reason": "Defeito"}, format="json").json()
    api.post(f"/api/v1/returns/{created['id']}/complete/", {}, format="json")
    finance.create_title(store=fin.store, kind="payable", description="Aluguel", total=Decimal("50"),
                         category_key="rent")

    dre = api.get("/api/v1/reports/dre/").json()

    assert (dre["gross_revenue"], dre["discounts"], dre["returns"], dre["net_revenue"]) == (
        "200.00", "20.00", "90.00", "90.00")
    assert (dre["cmv"], dre["gross_profit"]) == ("40.00", "50.00")
    assert (dre["card_fees"], dre["commissions"], dre["expenses_total"]) == ("1.80", "4.50", "50.00")
    assert dre["operating_result"] == "-6.30"
    assert dre["expenses"] == [{"category": "Aluguel", "amount": "50.00"}]


def test_kit_sai_com_o_custo_dos_componentes(fin):
    a, b = fin.product(name="Caneca", sku="CAN", price="10"), fin.product(name="Colher", sku="COL", price="5")
    type(a).all_objects.filter(pk=a.pk).update(average_cost=Decimal("3"))
    type(b).all_objects.filter(pk=b.pk).update(average_cost=Decimal("5"))
    kit = fin.product(name="Kit café", sku="KIT", price="30", type="kit")
    KitComponent.all_objects.create(account=fin.account, kit=kit.product, component=a, quantity=Decimal("2"))
    KitComponent.all_objects.create(account=fin.account, kit=kit.product, component=b, quantity=Decimal("1"))
    api = fin.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()

    body = api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(kit.pk)}, format="json").json()

    assert Decimal(body["items"][0]["unit_cost"]) == Decimal("11")


def test_pagamento_de_comissao_baixa_as_pendentes_e_sai_do_banco(fin):
    seller = fin.user("vend2", "seller", is_seller=True, commission_percent=Decimal("5"))
    product = fin.product(price="100.00", track_stock=False)
    _sell(fin, product, [{"nsu": "000123", "method": str(fin.methods["pix"].pk), "amount": "100.00"}], seller=seller.pk)
    api = fin.client()

    paid = api.post("/api/v1/commissions/payout/", {"seller": seller.pk, "financial_account": str(fin.bank.pk)},
                    format="json")
    again = api.post("/api/v1/commissions/payout/", {"seller": seller.pk, "financial_account": str(fin.bank.pk)},
                     format="json")

    assert paid.status_code == 201 and paid.json()["total"] == "5.00"
    assert _balance(fin.bank) == Decimal("95.00")
    assert again.status_code == 422


def test_transferencia_fluxo_de_caixa_vencimentos_e_lancamento_imutavel(fin):
    vault = vault_for(fin.store)
    api = fin.client()
    api.post("/api/v1/finance/accounts/transfer/", {"source": str(vault.pk), "target": str(fin.bank.pk),
                                                    "amount": "40.00", "description": "Depósito"}, format="json")
    finance.create_title(store=fin.store, kind="payable", description="Luz", total=Decimal("30"),
                         category_key="utilities")
    expense = api.post("/api/v1/finance/transactions/", {
        "financial_account": str(fin.bank.pk), "kind": "out", "amount": "12.00", "date": str(timezone.localdate()),
        "description": "Material de limpeza"}, format="json").json()

    flow = api.get("/api/v1/reports/cash-flow/").json()
    aging = api.get("/api/v1/reports/aging/").json()
    edit = api.patch(f"/api/v1/finance/transactions/{expense['id']}/", {"amount": "1.00"}, format="json")
    reversal = api.post(f"/api/v1/finance/transactions/{expense['id']}/reverse/", {}, format="json")

    assert (flow["inflow"], flow["outflow"]) == ("40.00", "52.00")
    assert aging["payable"]["next_7_days"] == "30.00"
    assert edit.status_code == 405
    # +40 da transferência, -12 da despesa, +12 do estorno: a despesa foi desfeita.
    assert reversal.status_code == 201 and _balance(fin.bank) == Decimal("40.00")


def test_estorno_em_massa_pula_o_que_nao_pode(fin):
    api = fin.client()
    tx = api.post("/api/v1/finance/transactions/", {"financial_account": str(fin.bank.pk), "kind": "out", "amount": "80.00",
                                                     "date": "2026-10-01", "description": "Conta de luz"}, format="json").json()

    first = api.post("/api/v1/finance/transactions/bulk/", {"action": "reverse", "ids": [tx["id"]]}, format="json").json()
    again = api.post("/api/v1/finance/transactions/bulk/", {"action": "reverse", "ids": [tx["id"]]}, format="json").json()

    assert first["affected"] == 1
    assert again["affected"] == 0 and again["skipped"][0]["reason"] == "já estornado"
    listed = api.get("/api/v1/finance/transactions/", {"ordering": "-date"}).json()["results"]
    assert sorted(row["is_reversal"] for row in listed) == [False, True]


def test_titulo_mostra_em_aberto_e_proximo_vencimento(fin):
    api = fin.client()
    title = api.post("/api/v1/finance/titles/", {"kind": "payable", "description": "Aluguel", "total": "300.00",
                                                  "installment_count": 3, "first_due": "2026-11-10"}, format="json").json()
    first = title["installments"][0]

    api.post(f"/api/v1/finance/installments/{first['id']}/settle/", {"financial_account": str(fin.bank.pk),
                                                                       "amount": "100.00"}, format="json")
    body = api.get(f"/api/v1/finance/titles/{title['id']}/").json()

    assert body["open_amount"] == "200.00" and body["next_due"] == "2026-12-10"
    assert body["installments"][0]["party_name"] == "" and body["installments"][0]["kind"] == "payable"
