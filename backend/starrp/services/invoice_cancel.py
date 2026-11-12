"""Cancelamento da nota de saída (evento 110111) e o "cancela tudo" do pedido: nota + venda + reembolso.

Regras da SEFAZ que valem aqui:
- só nota AUTORIZADA se cancela (rejeitada/erro nunca valeu);
- justificativa de 15 a 255 caracteres;
- prazo contado da autorização: NF-e 24 horas, NFC-e 30 minutos. Passou do prazo, o caminho
  é a devolução (troca/devolução do pedido), que emite a nota de entrada.

O evento na SEFAZ é a ÚLTIMA coisa da transação: se ele falhar, nada muda no banco (nem a venda
nem a nota). A emissão ainda não está integrada: em homologação o protocolo é gerado aqui; em
produção, sem integração, recusa — melhor não cancelar do que dizer que cancelou.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError, StateConflict
from starrp.models import Invoice
from starrp.models.fiscal import DocumentModel, Environment

REASON_MIN, REASON_MAX = 15, 255
DEADLINES = {DocumentModel.NFE: timedelta(hours=24), DocumentModel.NFCE: timedelta(minutes=30)}
DEADLINE_LABEL = {DocumentModel.NFE: "24 horas", DocumentModel.NFCE: "30 minutos"}


def check(invoice, reason):
    """Recusa (com a mensagem para o usuário) o que a SEFAZ recusaria."""
    if invoice.status != Invoice.Status.AUTHORIZED:
        raise StateConflict(f"Só nota autorizada se cancela; esta está '{invoice.get_status_display()}'.",
                            code="invoice_not_authorized")
    reason = (reason or "").strip()
    if not REASON_MIN <= len(reason) <= REASON_MAX:
        raise BusinessError(f"A justificativa do cancelamento da nota precisa ter de {REASON_MIN} a {REASON_MAX} "
                            "caracteres (regra da SEFAZ).", code="invoice_cancel_reason")
    since = invoice.authorized_at or invoice.created_at
    deadline = DEADLINES.get(invoice.document_model)
    if deadline and timezone.now() - since > deadline:
        raise BusinessError(f"Passou o prazo de cancelamento da {invoice.get_document_model_display().split(' ')[0]} "
                            f"({DEADLINE_LABEL[invoice.document_model]} depois da autorização). Faça a devolução do "
                            "pedido, que emite a nota de entrada.", code="invoice_cancel_deadline")
    return reason


def _send_event(invoice, reason):
    """Evento de cancelamento na SEFAZ; devolve o protocolo."""
    if invoice.environment == Environment.PRODUCTION:
        raise StateConflict("O envio do cancelamento à SEFAZ em produção ainda não está integrado. Cancele no "
                            "emissor/portal e depois registre aqui.", code="fiscal_provider_missing")
    return f"HOMOLOG-{timezone.now():%Y%m%d%H%M%S}"


def _mark(invoice, user, reason):
    invoice.status, invoice.cancelled_at, invoice.cancel_reason = Invoice.Status.CANCELLED, timezone.now(), reason
    invoice.updated_by = user
    invoice.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_by", "updated_at"])


def _finish(invoices, reason):
    for invoice in invoices:
        invoice.cancel_protocol = _send_event(invoice, reason)
        invoice.save(update_fields=["cancel_protocol", "updated_at"])


@transaction.atomic
def cancel_invoice(invoice, user, reason):
    """Só a nota: a venda continua concluída (ex.: nota com dado errado, para emitir de novo)."""
    invoice = Invoice.all_objects.select_for_update().get(pk=invoice.pk)
    reason = check(invoice, reason)
    _mark(invoice, user, reason)
    _finish([invoice], reason)
    return invoice


@transaction.atomic
def cancel_sale_and_invoices(sale, user, reason, approval=None):
    """Pedido inteiro: cancela a(s) nota(s) autorizada(s), a venda (estoque volta, comissão e cupom
    saem, títulos cancelados) e reembolsa os pagamentos (dinheiro sai do turno aberto de quem cancela;
    cartão/PIX ficam estornados para devolver na maquininha/banco)."""
    from starrp.services import checkout

    invoices = list(Invoice.all_objects.select_for_update().filter(sale=sale, status=Invoice.Status.AUTHORIZED,
                                                                   deleted_at__isnull=True))
    reason = (reason or "").strip()
    for invoice in invoices:
        check(invoice, reason)
    for invoice in invoices:
        _mark(invoice, user, reason)
    sale = checkout.cancel(sale, user, reason, approval)
    _finish(invoices, reason)
    return sale
