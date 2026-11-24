"""Rodada 2 da auditoria, achados do red team (docs/SEGURANCA.md: A-xx, M-xx e B-xx)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from starrp.core.errors import BusinessError
from starrp.core.tenant import tenant_context
from starrp.models import (
    Coupon, Customer, CustomerCredit, DiscountTable, FinancialAccount, FiscalConfig, FiscalSeries, InboundNFe, Promotion,
    RecurringTitle, Sale, StockMovement,
)
from starrp.services import checkout, history, offline_sales, recurring, returns, sales, stock
from starrp.services.coupons import _same_document
from starrp.services.integrations.asaas import Asaas
from starrp.services.provisioning import create_store
from starrp.tests.test_security_round2 import _open_sale, _paid


def _modules(ctx, *names):
    ctx.account.extra_modules = list(names)
    ctx.account.save()


# ── escopo da filial (A-10 a A-13, M-03, M-07, M-12) ────────────────────────
def test_gerente_de_uma_filial_nao_altera_fiscal_da_outra(ctx):
    store_b = create_store(ctx.account, name="Filial B")
    manager = ctx.user("gerente", "manager")
    config = FiscalConfig.all_objects.create(account=ctx.account, name="B", legal_name="B LTDA", cnpj="11222333000181")
    store_b.fiscal_config = config
    store_b.save(update_fields=["fiscal_config"])
    series = FiscalSeries.all_objects.create(account=ctx.account, config=config, series=9)
    api = ctx.client(manager)
    assert api.patch(f"/api/v1/fiscal/configs/{config.pk}/", {"stores": []}, format="json").status_code == 403
    assert api.patch(f"/api/v1/fiscal/series/{series.pk}/", {"next_number": 999}, format="json").status_code == 403
    store_b.refresh_from_db()
    assert store_b.fiscal_config_id == config.pk
    network = ctx.client().patch(f"/api/v1/fiscal/series/{series.pk}/", {"next_number": 5}, format="json")
    assert network.status_code == 200, network.json()  # quem acessa a rede pode


def test_promocao_e_cupom_da_rede_nao_mudam_por_usuario_de_filial(ctx):
    table = DiscountTable.all_objects.create(account=ctx.account, name="Rede")
    rule = Promotion.all_objects.create(account=ctx.account, table=table, name="Regra", value=Decimal("5"))
    coupon = Coupon.all_objects.create(account=ctx.account, store=ctx.store, code="LOJA", value=Decimal("5"))
    api = ctx.client(ctx.user("mkt", "marketing"))
    assert api.patch(f"/api/v1/promotions/rules/{rule.pk}/", {"value": "99"}, format="json").status_code == 403
    assert api.delete(f"/api/v1/promotions/rules/{rule.pk}/").status_code == 403
    assert api.patch(f"/api/v1/promotions/coupons/{coupon.pk}/", {"store": None}, format="json").status_code == 403
    own = api.patch(f"/api/v1/promotions/coupons/{coupon.pk}/", {"name": "ok"}, format="json")
    assert own.status_code == 200, own.json()


def test_regra_de_estoque_usada_por_outra_filial_nao_muda(ctx):
    _modules(ctx, "stock")
    create_store(ctx.account, name="Filial B")
    api = ctx.client(ctx.user("gerente", "manager"))
    response = api.patch(f"/api/v1/stock/rules/{ctx.store.stock_rule_id}/", {"allow_negative_stock": True},
                         format="json")
    assert response.status_code == 403, response.json()


def test_recorrencias_so_das_filiais_de_quem_gera(ctx):
    store_b = create_store(ctx.account, name="Filial B")
    RecurringTitle.all_objects.create(account=ctx.account, store=store_b, kind="payable", description="B",
                                      amount=Decimal("10"), start_date=timezone.localdate())
    with tenant_context(ctx.account, [ctx.store.pk]):
        assert recurring.generate_all(ctx.account) == 0
    assert recurring.generate_all(ctx.account) >= 1  # a tarefa diária vê todas


def test_venda_offline_nao_comissiona_vendedor_de_outra_filial(ctx):
    store_b = create_store(ctx.account, name="Filial B")
    stranger = ctx.user("vendedorb", "seller", stores=[store_b], is_seller=True)
    checks = type("Checks", (), {"issues": []})()
    assert offline_sales._seller(ctx.store, ctx.account, stranger.pk, checks) is None
    assert checks.issues
    local = ctx.user("vendedora", "seller", is_seller=True)
    assert offline_sales._seller(ctx.store, ctx.account, local.pk, checks) == local


def test_forma_de_pagamento_de_outra_filial_ou_desativada(ctx):
    store_b = create_store(ctx.account, name="Filial B")
    sale = _open_sale(ctx, (ctx.product(price="50.00", track_stock=False), "1"))
    method = ctx.methods["pix"]
    method.store = store_b
    with pytest.raises(BusinessError, match="outra filial"):
        checkout.add_payment(sale, method, sale.total, ctx.admin)
    method.store, method.is_active = None, False
    with pytest.raises(BusinessError, match="desativada"):
        checkout.add_payment(sale, method, sale.total, ctx.admin)


# ── venda, vale e devolução (A-03, A-08, M-04, M-06, M-13, M-15, B-08) ──────
def test_exclusao_em_massa_nao_apaga_venda(ctx):
    sale = _paid(ctx, _open_sale(ctx, (ctx.product(track_stock=False), "1")))
    response = ctx.client().post("/api/v1/sales/bulk/", {"action": "delete", "all": True}, format="json")
    assert response.status_code == 403
    assert Sale.all_objects.get(pk=sale.pk).deleted_at is None


@pytest.mark.parametrize("kind", ["store_credit", "installment_plan"])
def test_vale_e_crediario_nao_viram_dinheiro(ctx, kind):
    ctx.require_cash()
    customer = Customer.all_objects.create(account=ctx.account, name="Ana", credit_limit=Decimal("500"))
    CustomerCredit.all_objects.create(account=ctx.account, customer=customer, kind="adjustment", amount=Decimal("50"))
    from starrp.services import cash

    cash.open_session(ctx.register, ctx.admin, Decimal("500"))
    sale = _paid(ctx, _open_sale(ctx, (ctx.product(price="50.00", track_stock=False), "1"), customer=customer), kind)
    draft = returns.create(sale, ctx.admin, [{"sale_item": sale.items.get(), "quantity": Decimal("1")}],
                           refund_method="cash", reason="defeito")
    with pytest.raises(BusinessError, match="passa do que o cliente pagou"):
        returns.complete(draft, ctx.admin)


def test_frete_nao_se_zera_pelo_cliente_da_venda(ctx):
    sale = _open_sale(ctx, (ctx.product(price="50.00", track_stock=False), "1"))
    Sale.all_objects.filter(pk=sale.pk).update(freight=Decimal("80"))
    response = ctx.client().post(f"/api/v1/sales/{sale.pk}/customer/", {"freight": "0.00"}, format="json")
    assert response.status_code == 200
    assert Sale.all_objects.get(pk=sale.pk).freight == Decimal("80")


def test_vale_vencido_nao_vale(ctx):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana")
    CustomerCredit.all_objects.create(account=ctx.account, customer=customer, kind="return", amount=Decimal("100"),
                                      expires_at=timezone.localdate() - timedelta(days=1))
    CustomerCredit.all_objects.create(account=ctx.account, customer=customer, kind="return", amount=Decimal("30"))
    assert checkout.credit_balance(customer) == Decimal("30.00")


def test_cpf_com_e_sem_mascara_e_o_mesmo_no_cupom():
    assert "123.456.789-09" in _same_document("12345678909")
    assert "12345678909" in _same_document("123.456.789-09")


@pytest.mark.parametrize("value", ["-50", "NaN", "Infinity", "abc", {"a": 1}])
def test_numero_invalido_na_venda_offline(value):
    with pytest.raises(BusinessError):
        offline_sales._dec(value)


@pytest.mark.parametrize("items", [{"a": 1}, ["texto"], "x"])
def test_itens_em_formato_errado_na_venda_offline(items):
    with pytest.raises(BusinessError):
        offline_sales._rows(items, "Itens")


def test_quantidade_minuscula_nao_sai_de_graca(ctx):
    sale = _open_sale(ctx)
    with pytest.raises(BusinessError):
        sales.add_item(sale, ctx.product(price="1.00", track_stock=False), Decimal("0.001"), ctx.admin)


# ── custo, fila de impressão, exclusões e entradas ruins ────────────────────
def test_custo_nao_aparece_nos_itens_nem_no_historico(ctx):
    cashier = ctx.user("caixa1", "cashier")
    variant = ctx.product(track_stock=False)
    sale = _open_sale(ctx, (variant, "1"), user=cashier)
    assert "unit_cost" not in ctx.client(cashier).get(f"/api/v1/sales/{sale.pk}/items/").json()[0]
    assert "unit_cost" in ctx.client().get(f"/api/v1/sales/{sale.pk}/items/").json()[0]

    variant.average_cost = Decimal("9.9900")
    variant.save()

    def cost_changes(user):
        return [c for row in history.events(variant, user) for c in row["changes"] if "cost" in str(c.get("key"))]

    assert cost_changes(ctx.admin) and not cost_changes(cashier)


def test_fila_de_impressao_exige_permissao(ctx):
    api = ctx.client(ctx.user("estoquista", "stockist"))
    assert api.get("/api/v1/devices/print-jobs/").status_code == 403
    assert ctx.client().get("/api/v1/devices/print-jobs/").status_code == 200


def test_nfe_de_entrada_nao_nasce_por_post(ctx):
    _modules(ctx, "inbound_nfe")
    response = ctx.client().post("/api/v1/inbound-nfe/", {}, format="json")
    assert response.status_code == 422, response.json()
    assert not InboundNFe.all_objects.exists()


def test_deposito_com_saldo_nao_e_excluido(ctx):
    warehouse = stock.default_warehouse(ctx.store)
    stock.move(ctx.product(), warehouse, Decimal("3"), StockMovement.Kind.PURCHASE)
    assert ctx.client().delete(f"/api/v1/stock/warehouses/{warehouse.pk}/").status_code == 409


@pytest.mark.parametrize("path", ["auth/refresh", "auth/logout", "auth/password-reset", "auth/password-reset/confirm",
                                  "public/reviews/x"])
@pytest.mark.parametrize("body", ["[1]", '"5"', "null", '{"token": {"a": 1}, "password": []}'])
def test_corpo_estranho_nas_rotas_publicas_nao_derruba(db, path, body):
    response = APIClient().post(f"/api/v1/{path}/", body, content_type="application/json")
    assert response.status_code < 500


@pytest.mark.parametrize("query", ["sales/?updated_after=2026-99-99T00:00:00", "reports/summary/?seller=lixo",
                                   "reports/book/cancelamentos/?seller=lixo"])
def test_parametro_estranho_nao_derruba(ctx, query):
    assert ctx.client().get(f"/api/v1/{query}").status_code < 500


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "1e400", "0.001"])
def test_transferencia_com_valor_invalido(ctx, amount):
    _modules(ctx, "finance")
    accounts = [FinancialAccount.all_objects.create(account=ctx.account, store=ctx.store, name=n) for n in "AB"]
    response = ctx.client().post("/api/v1/finance/accounts/transfer/", {
        "source": str(accounts[0].pk), "target": str(accounts[1].pk), "amount": amount}, format="json")
    assert response.status_code in (400, 422), response.json()


def test_webhook_com_token_nao_ascii_e_recusado():
    service = Asaas.__new__(Asaas)
    service.get = lambda key: "segredo"
    assert service.verify_webhook(b"", {"asaas-access-token": "éé"}, {}) is False
