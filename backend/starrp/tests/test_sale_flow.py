"""O fluxo do PDV de ponta a ponta, pela API."""
from decimal import Decimal

from starrp.models import CashSession, Commission, Payment, Sale, StockMovement
from starrp.services import cash, stock


def _stock(ctx, product, quantity, cost="20.00"):
    warehouse = stock.default_warehouse(ctx.store)
    stock.move(product, warehouse, Decimal(quantity), StockMovement.Kind.PURCHASE, unit_cost=Decimal(cost))
    return warehouse


def _open_cash(ctx, user, amount="100.00"):
    return cash.open_session(ctx.register, user, Decimal(amount))


def test_venda_em_dinheiro_com_troco_baixa_estoque_e_entra_na_gaveta(ctx):
    """Venda completa: lê o código, paga em dinheiro com troco, baixa o estoque e a gaveta confere."""
    product = ctx.product(barcode="7891000315507", price="45.90")
    _stock(ctx, product, 10)
    session = _open_cash(ctx, ctx.admin)
    api = ctx.client()

    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"code": "7891000315507", "quantity": "2"}, format="json")
    response = api.post(f"/api/v1/sales/{sale['id']}/checkout/", {
        "payments": [{"nsu": "000123", "method": str(ctx.methods["cash"].pk), "amount": "91.80", "tendered": "100.00"}]
    }, format="json")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "completed"
    assert Decimal(body["total"]) == Decimal("91.80")
    assert Decimal(body["change_amount"]) == Decimal("8.20")
    assert stock.available(product) == Decimal("8")
    session = CashSession.all_objects.get(pk=session.pk)
    assert cash.expected_cash(session) == Decimal("191.80")


def test_venda_nao_conclui_sem_pagamento_total(ctx):
    """Concluir com saldo em aberto é recusado com código próprio (o PDV mostra "falta receber")."""
    product = ctx.product(price="10.00")
    _stock(ctx, product, 5)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")

    response = api.post(f"/api/v1/sales/{sale['id']}/complete/", {}, format="json")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "payment_pending"


def test_dinheiro_exige_caixa_aberto(ctx):
    """Sem turno aberto, pagamento em dinheiro devolve 409 — não 400 —, para o PDV não reenviar em laço."""
    product = ctx.product(price="10.00")
    _stock(ctx, product, 5)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")

    response = api.post(f"/api/v1/sales/{sale['id']}/payments/",
                        {"nsu": "000123", "method": str(ctx.methods["cash"].pk), "amount": "10.00"}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cash_session_required"


def test_comissao_do_vendedor_sobre_o_valor_liquido(ctx):
    """A comissão incide sobre o que o cliente pagou (desconto do total rateado), não sobre o preço cheio."""
    seller = ctx.user("joana", "seller", is_seller=True, commission_percent=Decimal("5"))
    product = ctx.product(price="100.00")
    _stock(ctx, product, 5)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {"seller": seller.pk}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/discount/", {"amount": "10.00"}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "90.00"}]}, format="json")

    commission = Commission.all_objects.get(sale_id=sale["id"])
    assert commission.base_amount == Decimal("90.00")
    assert commission.amount == Decimal("4.50")


def test_cancelar_venda_concluida_devolve_estoque_e_dinheiro(ctx):
    """Cancelar venda concluída estorna estoque e tira o dinheiro do turno ATUAL como devolução."""
    product = ctx.product(price="30.00")
    _stock(ctx, product, 3)
    session = _open_cash(ctx, ctx.admin, "0")
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"nsu": "000123", "method": str(ctx.methods["cash"].pk), "amount": "30.00"}]}, format="json")

    response = api.post(f"/api/v1/sales/{sale['id']}/cancel/", {"reason": "Cliente desistiu"}, format="json")

    assert response.status_code == 200, response.json()
    assert Sale.all_objects.get(pk=sale["id"]).status == Sale.Status.CANCELLED
    assert stock.available(product) == Decimal("3")
    assert Payment.all_objects.get(sale_id=sale["id"]).status == Payment.Status.REFUNDED
    assert cash.expected_cash(CashSession.all_objects.get(pk=session.pk)) == Decimal("0")


def test_reenvio_com_a_mesma_chave_nao_cobra_duas_vezes(ctx):
    """O PDV reenvia o checkout com a mesma Idempotency-Key: a resposta é repetida, nada é executado de novo."""
    product = ctx.product(price="25.00")
    _stock(ctx, product, 5)
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk)}, format="json")
    body = {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "25.00"}]}

    first = api.post(f"/api/v1/sales/{sale['id']}/checkout/", body, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    second = api.post(f"/api/v1/sales/{sale['id']}/checkout/", body, format="json", HTTP_IDEMPOTENCY_KEY="k-1")

    assert first.status_code == second.status_code == 200
    assert second["Idempotent-Replay"] == "true"
    assert Payment.all_objects.filter(sale_id=sale["id"]).count() == 1
    assert stock.available(product) == Decimal("4")


def test_painel_com_venda_concluida_traz_margem_e_mais_vendidos(ctx):
    """O painel agrega vendas reais: faturamento, margem (preço - custo) e ranking de produtos."""
    product = ctx.product(price="50.00")
    _stock(ctx, product, 10, cost="20.00")
    api = ctx.client()
    sale = api.post("/api/v1/sales/", {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk), "quantity": "2"}, format="json")
    api.post(f"/api/v1/sales/{sale['id']}/checkout/",
             {"payments": [{"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": "100.00"}]}, format="json")

    response = api.get("/api/v1/reports/dashboard/")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert Decimal(body["summary"]["revenue"]) == Decimal("100.00")
    assert Decimal(body["summary"]["gross_margin"]) == Decimal("60.00")
    assert Decimal(body["top_products"][0]["sold_quantity"]) == Decimal("2")
    # Dinheiro sai como texto com centavos, nunca como float.
    assert body["summary"]["revenue"] == "100.00"


def test_extrato_do_turno_e_itens_vendidos_por_produto(ctx):
    """O extrato junta vendas, pagamentos, itens somados e ocorrências; os itens filtram por produto e cliente."""
    product = ctx.product(name="Café", price="20.00")
    _stock(ctx, product, 10, cost="8.00")
    session = _open_cash(ctx, ctx.admin)
    api = ctx.client()
    customer = api.post("/api/v1/customers/", {"name": "Ana"}, format="json").json()
    for qty in ("2", "1"):
        sale = api.post("/api/v1/sales/", {"customer": customer["id"]}, format="json").json()
        api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(product.pk), "quantity": qty}, format="json")
        api.post(f"/api/v1/sales/{sale['id']}/checkout/", {"payments": [
            {"nsu": "000123", "method": str(ctx.methods["pix"].pk), "amount": str(20 * int(qty))}]}, format="json")
    api.post(f"/api/v1/cash/sessions/{session.pk}/movements/", {"kind": "withdrawal", "amount": "50.00",
                                                                  "reason": "Depósito"}, format="json")

    body = api.get(f"/api/v1/cash/sessions/{session.pk}/statement/").json()
    items = api.get("/api/v1/sales/items/", {"variant__product": str(product.product_id), "sale__status": "completed",
                                             "ordering": "-completed_at"}).json()["results"]
    bought = api.get("/api/v1/sales/items/", {"sale__customer": customer["id"]}).json()["results"]

    assert len(body["sales_list"]) == 2 and body["sales_list"][0]["payments"].startswith("PIX")
    assert body["items"] == [{**body["items"][0], "description": "Café", "quantity": "3.000", "total": "60.00",
                              "cost": "24.00", "margin": "36.00", "sales": 2}]
    assert [m["kind"] for m in body["movements"]].count("withdrawal") == 1
    assert [i["quantity"] for i in items] == ["1.000", "2.000"] and items[0]["margin"] == "12.00"
    assert len(bought) == 2 and bought[0]["customer_name"] == "Ana"
