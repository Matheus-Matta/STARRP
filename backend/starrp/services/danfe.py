"""Dados do DANFE (NF-e A4 e DANFE NFC-e 80 mm) no layout do Manual de Orientação do Contribuinte.

Monta, a partir da nota, tudo o que o documento impresso pede: emitente, destinatário com
endereço, cálculo do imposto, transporte, duplicatas, itens com a tributação de cada linha,
dados adicionais, pagamentos e troco, e as marcas de homologação e de contingência.
O que foi enviado à SEFAZ (`invoice.payload`) vale sobre o cadastro atual: a nota é um retrato.
"""
from decimal import Decimal

from django.db.models import Sum

from starrp.models import FinancialTitle, Installment, Invoice, Payment
from starrp.models.fiscal import DocumentModel, Environment
from starrp.serializers.misc import InvoiceSerializer
from starrp.serializers.sales import PaymentSerializer
from starrp.services import labels

ZERO = Decimal("0")
FREIGHT_MODES = {"0": "0 - Por conta do emitente (CIF)", "1": "1 - Por conta do destinatário (FOB)",
                 "2": "2 - Por conta de terceiros", "9": "9 - Sem ocorrência de transporte"}


def _money(value):
    return f"{Decimal(value or 0):.2f}"


def _address(obj):
    if obj is None:
        return None
    return {"street": obj.street, "number": obj.number, "complement": obj.complement, "district": obj.district,
            "city": obj.city, "state": obj.state, "zip_code": obj.zip_code}


def _line(address):
    if not address:
        return ""
    street = ", ".join(filter(None, [address.get("street"), address.get("number")]))
    return " - ".join(filter(None, [street, address.get("complement")]))


def _issuer(invoice):
    snap = (invoice.payload or {}).get("issuer") or {}
    config = invoice.fiscal_config
    if config is None and not snap:
        return None
    base = {} if config is None else {
        "legal_name": config.legal_name, "trade_name": config.trade_name, "cnpj": config.cnpj,
        "state_registration": config.state_registration, "municipal_registration": config.municipal_registration,
        "phone": config.phone, "email": config.email, "crt": config.crt, "crt_label": config.get_crt_display(),
        "portal_url": config.portal_url, **_address(config),
    }
    data = {**base, **snap}
    data["address_line"] = _line(data)
    data["address"] = ", ".join(filter(None, [data["address_line"], data.get("district"),
                                              f"{data.get('city')}/{data.get('state')}" if data.get("city") else "",
                                              data.get("zip_code")]))
    return data


def _recipient(invoice):
    """Destinatário: o retrato enviado; sem ele, o cliente da venda e o endereço de entrega (ou o principal)."""
    snap = (invoice.payload or {}).get("recipient")
    if snap:
        return {**snap, "address_line": _line(snap)}
    sale = invoice.sale
    customer = sale.customer if sale else None
    if customer is None:
        if not (invoice.recipient_name or invoice.recipient_document):
            return None
        return {"name": invoice.recipient_name, "document": invoice.recipient_document}
    address = sale.shipping_address or customer.addresses.filter(is_default=True).first() or customer.addresses.first()
    data = {"name": invoice.recipient_name or customer.legal_name or customer.name,
            "document": invoice.recipient_document or customer.document,
            "state_registration": customer.state_registration, "phone": customer.phone, "email": customer.email,
            **(_address(address) or {})}
    data["address_line"] = _line(data)
    return data


def _duplicates(invoice):
    """Fatura/duplicatas: as parcelas a receber do cliente geradas pela venda (crediário, boleto)."""
    if invoice.sale_id is None:
        return []
    rows = (Installment.all_objects.filter(title__sale_id=invoice.sale_id, title__kind=FinancialTitle.Kind.RECEIVABLE,
                                           title__customer__isnull=False, deleted_at__isnull=True,
                                           title__deleted_at__isnull=True)
            .exclude(title__status="cancelled").order_by("due_date", "number"))
    return [{"number": f"{i:03d}", "due_date": row.due_date.isoformat(), "amount": str(row.amount)}
            for i, row in enumerate(rows, start=1)]


def build(invoice: Invoice, context=None):
    """O que o `DanfePrint` desenha. `context`: o do serializer (request)."""
    data = InvoiceSerializer(invoice, context=context or {}).data
    payload = invoice.payload or {}
    sale = invoice.sale
    qr = invoice.qr_code_data or invoice.consult_url
    items = invoice.items.all()
    totals = items.aggregate(icms_base=Sum("icms_base"), icms_value=Sum("icms_value"), pis_value=Sum("pis_value"),
                             cofins_value=Sum("cofins_value"))
    data.update(
        barcode_svg=labels.barcode_svg(invoice.access_key) if invoice.access_key else "",
        qr_svg=labels.qr_svg(qr) if qr else "",
        issuer=_issuer(invoice),
        recipient=_recipient(invoice),
        # 0 = entrada (a nota da devolução do cliente), 1 = saída.
        direction="0" if invoice.sale_return_id else "1",
        operation_nature=payload.get("operation_nature")
        or ("DEVOLUCAO DE MERCADORIA" if invoice.sale_return_id else "VENDA DE MERCADORIA"),
        issued_at=payload.get("issued_at") or invoice.created_at.isoformat(),
        homologation=invoice.environment == Environment.HOMOLOGATION,
        contingency=invoice.emission_type == Invoice.EmissionType.OFFLINE,
        nfce=invoice.document_model == DocumentModel.NFCE,
        tax_totals={
            "icms_base": _money(totals["icms_base"]), "icms_value": _money(totals["icms_value"]),
            "icms_st_base": str(payload.get("icms_st_base", "0.00")), "icms_st_value": str(payload.get("icms_st_value", "0.00")),
            "ipi_value": str(payload.get("ipi_value", "0.00")), "insurance": str(payload.get("insurance", "0.00")),
            "other_expenses": str(payload.get("other_expenses", "0.00")),
            "pis_value": _money(totals["pis_value"]), "cofins_value": _money(totals["cofins_value"]),
        },
        transport={
            "mode": FREIGHT_MODES.get(str(payload.get("freight_mode") or ("0" if sale and sale.shipping_address_id else "9"))),
            **(payload.get("transport") or {}),
        },
        duplicates=_duplicates(invoice),
        additional_info=payload.get("additional_info", ""),
        payments=[],
        change_amount="0.00",
    )
    if sale is not None:
        data["payments"] = PaymentSerializer(sale.payments.filter(status=Payment.Status.APPROVED).select_related("method"),
                                             many=True).data
        data["change_amount"] = str(sale.change_amount)
        data["sale_number"] = sale.number
    return data
