"""Correções na venda concluída: entrega e forma de pagamento (cada uma com permissão própria) e a
nota do pedido para imprimir."""
from starrp.models import CashMovement, FinancialTitle, FinancialTransaction, Invoice, Payment, PaymentMethod, Sale


def _customer(api):
    return api.post("/api/v1/customers/", {"name": "Ana Souza", "addresses": [
        {"label": "Casa", "zip_code": "01310-100", "street": "Av. Paulista", "number": "1000", "district": "Bela Vista",
         "city": "São Paulo", "state": "SP"},
        {"label": "Trabalho", "zip_code": "04538133", "street": "Av. Faria Lima", "number": "3477",
         "city": "São Paulo", "state": "SP"},
    ]}, format="json").json()


def _table(api):
    return api.post("/api/v1/logistics/freight-tables/", {"name": "Motoboy", "kind": "zip_range", "ranges": [
        {"zip_start": "01000000", "zip_end": "05999999", "value": "19.90", "lead_days": 1}]}, format="json").json()


def _completed_sale(ctx, api, method="pix", customer=None, amount="100.00", name="Mesa"):
    variant = ctx.product(name=name, price="100.00", track_stock=False)
    sale = api.post("/api/v1/sales/", {"customer": customer} if customer else {}, format="json").json()
    api.post(f"/api/v1/sales/{sale['id']}/items/", {"variant": str(variant.pk)}, format="json")
    done = api.post(f"/api/v1/sales/{sale['id']}/checkout/",
                    {"payments": [{"method": str(ctx.methods[method].pk), "amount": amount}]}, format="json")
    assert done.status_code == 200, done.json()
    return done.json()


def test_entrega_da_venda_concluida_muda_sem_mexer_no_frete_e_so_com_permissao(ctx):
    api = ctx.client()
    customer = _customer(api)
    table = _table(api)
    sale = _completed_sale(ctx, api, customer=customer["id"])
    work = next(a["id"] for a in customer["addresses"] if a["label"] == "Trabalho")
    cashier = ctx.client(ctx.user("caixa", "cashier"))
    url = f"/api/v1/sales/{sale['id']}/edit-delivery/"

    denied = cashier.post(url, {"address": work, "table": table["id"], "reason": "Cliente pediu"}, format="json")
    no_reason = api.post(url, {"address": work, "table": table["id"]}, format="json")
    delivered = api.post(url, {"address": work, "table": table["id"], "reason": "Cliente pediu entrega"},
                         format="json").json()
    back = api.post(url, {"pickup": True, "reason": "Vai buscar"}, format="json").json()

    assert sale["fulfillment_status"] == "picked_up"
    assert denied.status_code == 403
    assert no_reason.status_code == 422
    assert delivered["shipping_address"] and delivered["metafields"]["_entrega"]["table_name"] == "Motoboy"
    assert delivered["fulfillment_status"] == "pending" and delivered["freight"] == "0.00" and delivered["total"] == "100.00"
    assert back["shipping_address"] is None and back["metafields"]["_retirada"] is True
    assert "_entrega" not in back["metafields"]


def test_troca_de_forma_estorna_a_antiga_e_lanca_a_nova(ctx):
    api = ctx.client()
    sale = _completed_sale(ctx, api, method="pix")
    old = Payment.all_objects.get(sale_id=sale["id"])
    credit = ctx.methods["credit_card"]
    seller = ctx.client(ctx.user("vend", "seller", is_seller=True))
    url = f"/api/v1/sales/{sale['id']}/payments/{old.pk}/change/"

    denied = seller.post(url, {"method": str(credit.pk), "reason": "Era cartão"}, format="json")
    changed = api.post(url, {"method": str(credit.pk), "installments": 2, "nsu": "123", "reason": "Era cartão"},
                       format="json")

    assert denied.status_code == 403
    assert changed.status_code == 200, changed.json()
    body = changed.json()
    by_status = {p["status"]: p for p in body["payments"]}
    assert by_status["cancelled"]["id"] == str(old.pk)
    assert by_status["approved"]["method"] == str(credit.pk) and by_status["approved"]["amount"] == "100.00"
    assert by_status["approved"]["installments"] == 2 and by_status["approved"]["nsu"] == "123"
    assert body["paid_amount"] == "100.00" and body["status"] == "completed"
    # O que o PIX lançou foi estornado; o cartão gera o dele (conta ou título a receber, conforme a forma).
    old_txs = FinancialTransaction.all_objects.filter(payment=old, reversal_of__isnull=True)
    assert all(tx.reversals.exists() for tx in old_txs)
    new = Payment.all_objects.get(pk=by_status["approved"]["id"])
    if credit.generates_receivable:
        assert FinancialTitle.all_objects.filter(payment=new).exists()
    elif credit.financial_account_id:
        assert FinancialTransaction.all_objects.filter(payment=new).exists()


def test_troca_de_dinheiro_cancela_a_entrada_da_gaveta_com_o_turno_aberto(ctx):
    api = ctx.client()
    api.post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "50"}, format="json")
    sale = _completed_sale(ctx, api, method="cash")
    old = Payment.all_objects.get(sale_id=sale["id"])
    pix = ctx.methods["pix"]

    changed = api.post(f"/api/v1/sales/{sale['id']}/payments/{old.pk}/change/",
                       {"method": str(pix.pk), "reason": "Pagou no PIX"}, format="json")

    assert changed.status_code == 200, changed.json()
    assert CashMovement.all_objects.get(payment=old).status == CashMovement.Status.CANCELLED


def test_nota_do_pedido_para_imprimir(ctx):
    api = ctx.client()
    sale = _completed_sale(ctx, api)
    invoice = Invoice.all_objects.create(account=ctx.account, store=ctx.store, sale_id=sale["id"], document_model="65",
                                         series=1, number=42, status="authorized", access_key="3" * 44,
                                         qr_code_data="https://nfce.exemplo/qr?p=1", total="100.00")
    other = _completed_sale(ctx, api, name="Cadeira")

    got = api.get(f"/api/v1/sales/{sale['id']}/invoices/{invoice.pk}/danfe/")
    wrong = api.get(f"/api/v1/sales/{other['id']}/invoices/{invoice.pk}/danfe/")
    seller = ctx.client(ctx.user("vend", "seller", is_seller=True)).get(
        f"/api/v1/sales/{sale['id']}/invoices/{invoice.pk}/danfe/")

    assert got.status_code == 200, got.json()
    body = got.json()
    assert body["number"] == 42 and body["barcode_svg"].startswith("<svg") and "<svg" in body["qr_svg"]
    assert body["payments"][0]["amount"] == "100.00"
    assert wrong.status_code == 404
    assert seller.status_code == 200  # quem vê o pedido imprime a nota dele
    assert Sale.all_objects.get(pk=sale["id"]).invoices.count() == 1
    assert PaymentMethod.all_objects.filter(account=ctx.account).exists()
