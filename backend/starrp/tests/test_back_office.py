"""Devolução, crediário, estoque (lotes e inventário) e fechamento de caixa."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from starrp.models import CashSession, Customer, FinancialAccount, StockDocument, StockMovement, TitleStatus
from starrp.services import cash, stock, stock_documents


def _sell(ctx, api, product, method, **sale_fields):
    sale = api.post("/api/v1/sales/", sale_fields, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    total = api.get(f"/api/v1/sales/{sale['id']}/").json()["total"]
    response = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                        {"payments": [{"nsu": "000123", "method": str(method.pk), "amount": total}]}, format="json")
    return response


def test_devolucao_gera_vale_troca_que_paga_outra_venda(ctx):
    """Devolver vira crédito do cliente, o estoque volta, e o crédito é aceito como pagamento."""
    customer = Customer.all_objects.create(account=ctx.account, name="Ana", document="12345678909")
    product = ctx.product(price="40.00")
    stock.move(product, stock.default_warehouse(ctx.store), Decimal("2"), StockMovement.Kind.PURCHASE)
    api = ctx.client()
    sale = _sell(ctx, api, product, ctx.methods["pix"], customer=str(customer.pk)).json()

    created = api.post(f"/api/v1/sales/{sale['id']}/returns/", {
        "items": [{"sale_item": sale["items"][0]["id"], "quantity": "1"}], "reason": "Tamanho errado"},
        format="json").json()
    done = api.post(f"/api/v1/returns/{created['id']}/complete/", {}, format="json")
    reuse = _sell(ctx, api, product, ctx.methods["store_credit"], customer=str(customer.pk))

    assert done.status_code == 200, done.json()
    assert api.get(f"/api/v1/customers/{customer.pk}/").json()["credit_balance"] == "0.00"
    assert reuse.status_code == 200, reuse.json()
    assert stock.available(product) == Decimal("1")


def test_crediario_respeita_limite_e_gera_parcelas(ctx):
    """Crediário sem limite é recusado; com limite, vira título com parcelas que são baixadas no financeiro."""
    customer = Customer.all_objects.create(account=ctx.account, name="Bia", document="98765432100")
    product = ctx.product(price="300.00", track_stock=False)
    api = ctx.client()
    method = ctx.methods["installment_plan"]

    sale = api.post("/api/v1/sales/", {"customer": str(customer.pk)}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    over_limit = api.post(f"/api/v1/sales/{sale['id']}/payments/",
                          {"nsu": "000123", "method": str(method.pk), "amount": "300.00", "installments": 3}, format="json")
    Customer.all_objects.filter(pk=customer.pk).update(credit_limit=Decimal("500"))
    ok = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                  {"payments": [{"nsu": "000123", "method": str(method.pk), "amount": "300.00", "installments": 3}]}, format="json")

    assert over_limit.json()["error"]["code"] == "credit_limit_exceeded"
    assert ok.status_code == 200, ok.json()

    blocked = api.get("/api/v1/finance/installments/")
    ctx.account.extra_modules = ["finance"]
    ctx.account.save()
    installments = api.get("/api/v1/finance/installments/", {"title__customer": str(customer.pk)}).json()
    assert blocked.status_code == 403  # módulo Financeiro fora do plano
    assert [row["amount"] for row in installments["results"]] == ["100.00", "100.00", "100.00"]

    bank = FinancialAccount.all_objects.create(account=ctx.account, name="Banco")
    settle = api.post(f"/api/v1/finance/installments/{installments['results'][0]['id']}/settle/",
                      {"financial_account": str(bank.pk), "amount": "100.00"}, format="json")
    assert settle.status_code == 200, settle.json()
    assert settle.json()["status"] == TitleStatus.PAID


def test_saida_consome_lote_que_vence_primeiro(ctx):
    """FEFO: com dois lotes, a venda baixa primeiro o de validade mais próxima."""
    product = ctx.product(name="Iogurte", price="5.00", track_lots=True)
    warehouse = stock.default_warehouse(ctx.store)
    today = timezone.localdate()
    for days, qty in ((10, 5), (3, 5)):
        doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="entry", number=days,
                                               warehouse=warehouse, effective_date=today)
        doc.items.create(account=ctx.account, variant=product, quantity=qty, unit_cost=Decimal("2"),
                         lot_number=f"L{days}", expires_at=today + timedelta(days=days))
        stock_documents.post(doc, ctx.admin)

    stock.move(product, warehouse, Decimal("-3"), StockMovement.Kind.SALE)

    lots = {lot.lot_number: lot.quantity for lot in product.lots.all()}
    assert lots == {"L3": Decimal("2.000"), "L10": Decimal("5.000")}


def test_inventario_ajusta_pela_diferenca(ctx):
    """Inventário grava o saldo do sistema como esperado e move só a diferença."""
    product = ctx.product(price="9.00")
    warehouse = stock.default_warehouse(ctx.store)
    stock.move(product, warehouse, Decimal("10"), StockMovement.Kind.PURCHASE)
    doc = StockDocument.all_objects.create(account=ctx.account, store=ctx.store, kind="inventory", number=1,
                                           warehouse=warehouse, effective_date=timezone.localdate())
    item = doc.items.create(account=ctx.account, variant=product, quantity=Decimal("7"))

    stock_documents.post(doc, ctx.admin)

    item.refresh_from_db()
    assert item.expected_quantity == Decimal("10")
    assert stock.available(product) == Decimal("7")


def test_fechamento_com_diferenca_acima_da_tolerancia_pede_aprovacao(ctx):
    """Faltou R$ 5 na gaveta: o turno não fecha sozinho; o gerente aprova com motivo."""
    cashier = ctx.user("caixa2", "cashier")
    manager = ctx.user("gerente2", "manager")
    ctx.register.operators.add(cashier)  # o caixa é dele
    session = cash.open_session(ctx.register, cashier, Decimal("100"))

    closed = cash.close_session(session, cashier, Decimal("95"))
    approved = cash.approve_closing(closed, manager, "Troco dado errado")

    assert closed.status == CashSession.Status.PENDING_APPROVAL
    assert closed.difference == Decimal("-5.00")
    assert approved.status == CashSession.Status.CLOSED
