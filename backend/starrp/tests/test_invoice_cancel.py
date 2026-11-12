"""Nota de saída: DANFE completo pela tela de notas e o cancelamento (só a nota, ou nota + pedido + reembolso)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from starrp.models import Invoice, InvoiceItem, Payment, Sale

from .test_sale_edits import _completed_sale, _customer

REASON = "Cliente desistiu da compra no balcão"


@pytest.fixture(autouse=True)
def _fiscal(ctx):
    ctx.account.extra_modules = ["fiscal"]
    ctx.account.save(update_fields=["extra_modules"])


def _invoice(ctx, sale, model="65", minutes_ago=1, environment="2", **extra):
    fields = {"series": 1, "number": 7, "status": "authorized", "access_key": "3" * 44, "total": "100.00",
              "products_total": "100.00", "protocol": "135000000000001", **extra}
    invoice = Invoice.all_objects.create(
        account=ctx.account, store=ctx.store, sale_id=sale["id"], document_model=model, environment=environment,
        authorized_at=timezone.now() - timedelta(minutes=minutes_ago), **fields)
    InvoiceItem.all_objects.create(account=ctx.account, invoice=invoice, description="Mesa", ncm="94036000",
                                   cfop="5102", csosn="102", quantity=1, unit_price="100.00", total="100.00",
                                   icms_base="100.00", icms_rate="18.00", icms_value="18.00")
    return invoice


def test_danfe_da_nota_traz_destinatario_imposto_e_marcas(ctx):
    api = ctx.client()
    customer = _customer(api)
    sale = _completed_sale(ctx, api, customer=customer["id"])
    invoice = _invoice(ctx, sale, model="55", emission_type="9")

    body = api.get(f"/api/v1/fiscal/invoices/{invoice.pk}/danfe/").json()

    assert body["recipient"]["name"] == "Ana Souza" and body["recipient"]["city"] == "São Paulo"
    assert body["tax_totals"]["icms_value"] == "18.00" and body["tax_totals"]["icms_base"] == "100.00"
    assert body["homologation"] is True and body["contingency"] is True and body["nfce"] is False
    assert body["operation_nature"] == "VENDA DE MERCADORIA" and body["direction"] == "1"
    assert body["transport"]["mode"].startswith("9") and body["barcode_svg"].startswith("<svg")
    assert body["payments"][0]["amount"] == "100.00"


def test_cancelar_so_a_nota_mantem_a_venda(ctx):
    api = ctx.client()
    sale = _completed_sale(ctx, api)
    invoice = _invoice(ctx, sale)
    url = f"/api/v1/fiscal/invoices/{invoice.pk}/cancel/"

    short = api.post(url, {"reason": "errado"}, format="json")
    seller = ctx.client(ctx.user("vend", "seller", is_seller=True)).post(url, {"reason": REASON}, format="json")
    done = api.post(url, {"reason": REASON}, format="json")
    again = api.post(url, {"reason": REASON}, format="json")

    assert short.status_code == 422 and short.json()["error"]["code"] == "invoice_cancel_reason"
    assert seller.status_code == 403
    assert done.status_code == 200, done.json()
    assert done.json()["status"] == "cancelled" and done.json()["cancel_protocol"].startswith("HOMOLOG-")
    assert again.status_code == 409
    assert Sale.all_objects.get(pk=sale["id"]).status == "completed"


def test_cancelar_pedido_cancela_a_nota_e_reembolsa(ctx):
    api = ctx.client()
    sale = _completed_sale(ctx, api, method="pix")
    invoice = _invoice(ctx, sale)

    done = api.post(f"/api/v1/sales/{sale['id']}/cancel/", {"reason": REASON}, format="json")

    assert done.status_code == 200, done.json()
    assert done.json()["status"] == "cancelled"
    invoice.refresh_from_db()
    assert invoice.status == "cancelled" and invoice.cancel_reason == REASON
    assert Payment.all_objects.get(sale_id=sale["id"]).status == Payment.Status.REFUNDED


def test_pela_nota_cancela_o_pedido_junto(ctx):
    api = ctx.client()
    sale = _completed_sale(ctx, api)
    invoice = _invoice(ctx, sale)

    done = api.post(f"/api/v1/fiscal/invoices/{invoice.pk}/cancel/", {"reason": REASON, "with_sale": True}, format="json")

    assert done.status_code == 200, done.json()
    assert done.json()["status"] == "cancelled"
    assert Sale.all_objects.get(pk=sale["id"]).status == "cancelled"


def test_fora_do_prazo_ou_em_producao_nada_muda(ctx):
    api = ctx.client()
    late_sale = _completed_sale(ctx, api)
    late = _invoice(ctx, late_sale, minutes_ago=31)  # NFC-e: 30 minutos
    prod_sale = _completed_sale(ctx, api, name="Cadeira")
    prod = _invoice(ctx, prod_sale, environment="1", access_key="4" * 44, number=8)

    expired = api.post(f"/api/v1/sales/{late_sale['id']}/cancel/", {"reason": REASON}, format="json")
    no_provider = api.post(f"/api/v1/sales/{prod_sale['id']}/cancel/", {"reason": REASON}, format="json")

    assert expired.status_code == 422 and expired.json()["error"]["code"] == "invoice_cancel_deadline"
    assert no_provider.status_code == 409 and no_provider.json()["error"]["code"] == "fiscal_provider_missing"
    for invoice, sale in ((late, late_sale), (prod, prod_sale)):
        invoice.refresh_from_db()
        assert invoice.status == "authorized"
        assert Sale.all_objects.get(pk=sale["id"]).status == "completed"
        assert Payment.all_objects.get(sale_id=sale["id"]).status == Payment.Status.APPROVED
