"""Dados fiscais (emitente) e notas emitidas.

    GET/POST/PATCH /fiscal/configs/                 cadastro (lojas vinculadas em `stores`)
    POST /fiscal/configs/from-stores/               cria a partir das lojas com CNPJ ainda sem vínculo
    POST /fiscal/configs/{id}/certificate/          envia o A1 (.pfx) com a senha (multipart)
    POST /fiscal/configs/{id}/sync-dfe/             busca agora as notas de entrada na SEFAZ
    GET  /fiscal/invoices/                          notas emitidas (NFC-e / NF-e)
"""
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import ReadOnlyTenantViewSet, TenantViewSet
from starrp.models import FiscalConfig, Invoice
from starrp.models.platform import Module
from starrp.serializers import misc as s
from starrp.services import dfe, fiscal_data

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
