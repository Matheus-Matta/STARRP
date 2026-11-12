"""Dados fiscais (emitente) e notas emitidas.

    GET/POST/PATCH /fiscal/configs/                 cadastro (lojas vinculadas em `stores`)
    POST /fiscal/configs/from-stores/               cria a partir das lojas com CNPJ ainda sem vínculo
    POST /fiscal/configs/{id}/certificate/          envia o A1 (.pfx) com a senha (multipart)
    POST /fiscal/configs/{id}/sync-dfe/             busca agora as notas de entrada na SEFAZ
    GET  /fiscal/invoices/                          notas emitidas (NFC-e / NF-e)
"""
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import ReadOnlyTenantViewSet, TenantViewSet
from starrp.models import FiscalConfig, Invoice
from starrp.models.platform import Module
from starrp.serializers import misc as s
from starrp.services import danfe, dfe, fiscal_data, invoice_cancel

MAX_PFX_BYTES = 64 * 1024


class FiscalConfigViewSet(TenantViewSet):
    model = FiscalConfig
    serializer_class = s.FiscalConfigSerializer
    permission_code = "fiscal"
    required_module = Module.FISCAL
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    prefetch_related = ("stores", "dfe_states")
    filterset_fields = ["is_active", "environment", "dfe_enabled"]
    search_fields = ["name", "legal_name", "trade_name", "cnpj"]

    def initial(self, request, *args, **kwargs):
        # O certificado chega em multipart: a base exige corpo JSON-objeto.
        super(TenantViewSet, self).initial(request, *args, **kwargs)

    def _respond(self, config, status=200):
        return Response(self.get_serializer(FiscalConfig.all_objects.prefetch_related(*self.prefetch_related)
                                            .get(pk=config.pk)).data, status=status)

    @action(detail=False, methods=["post"], url_path="from-stores")
    def from_stores(self, request):
        created, skipped = fiscal_data.from_all_stores(request.account.pk, request.user)
        return Response({"linked": len(created), "skipped": skipped}, status=201 if created else 200)

    @action(detail=True, methods=["post"])
    def certificate(self, request, pk=None):
        upload, password = request.data.get("file"), str(request.data.get("password", ""))
        if upload is None or not hasattr(upload, "read"):
            raise BusinessError("Envie o arquivo do certificado (.pfx).")
        if upload.size > MAX_PFX_BYTES:
            raise BusinessError("Arquivo grande demais para um certificado A1.")
        return self._respond(fiscal_data.save_certificate(self.get_object(), upload, password))

    @action(detail=True, methods=["post"], url_path="sync-dfe")
    def sync_dfe(self, request, pk=None):
        result = dfe.sync(self.get_object(), request.user)
        return Response({**result, "next_allowed_at": result["next_allowed_at"]})


class InvoiceViewSet(ReadOnlyTenantViewSet):
    model = Invoice
    serializer_class = s.InvoiceSerializer
    permission_code = "fiscal"
    required_module = Module.FISCAL
    select_related = ("store", "fiscal_config", "sale")
    prefetch_related = ("items",)
    filterset_fields = {"status": ["exact"], "document_model": ["exact"], "sale": ["exact"],
                        "fiscal_config": ["exact"], "created_at": ["gte", "lte"]}
    search_fields = ["access_key", "number", "recipient_document", "recipient_name"]
    # Ler a nota imprime o DANFE; cancelar é de quem mexe no fiscal (e, com o pedido, também `sales.cancel`).
    action_permissions = {"danfe": "fiscal.view", "cancel": "fiscal.manage"}
    http_method_names = ["get", "post", "head", "options"]  # POST só nas ações (a nota nasce da venda)

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed("POST")

    @action(detail=True, methods=["get"])
    def danfe(self, request, pk=None):
        """DANFE da nota (NF-e A4 / NFC-e 80 mm): dados completos + código de barras + QR."""
        return Response(danfe.build(self.get_object(), self.get_serializer_context()))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """POST {"reason", "with_sale": bool, "approval"}: cancela a nota na SEFAZ; com `with_sale`,
        cancela também o pedido e reembolsa os pagamentos."""
        invoice = self.get_object()
        reason = str(request.data.get("reason", ""))
        if request.data.get("with_sale") and invoice.sale_id:
            invoice_cancel.cancel_sale_and_invoices(invoice.sale, request.user, reason, request.data.get("approval"))
            invoice.refresh_from_db()
        else:
            invoice = invoice_cancel.cancel_invoice(invoice, request.user, reason)
        return Response(s.InvoiceSerializer(invoice, context=self.get_serializer_context()).data)
