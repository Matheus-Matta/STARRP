"""NF-e de entrada pela retaguarda.

    POST /inbound-nfe/sync/              busca na SEFAZ as notas de todos os CNPJs (ou ?config=<id>)
    POST /inbound-nfe/import/            envia o XML (arquivo `file` ou texto `xml`)
    POST /inbound-nfe/{id}/science/      ciência da operação + baixa o XML completo
    POST /inbound-nfe/{id}/download/     tenta baixar de novo o XML completo
    POST /inbound-nfe/{id}/manifest/     confirmação / desconhecimento / não realizada {code, reason}
    POST /inbound-nfe/{id}/map-item/     vincula um item a um produto (e aprende)
    POST /inbound-nfe/{id}/rematch/      tenta casar de novo os itens pendentes
    POST /inbound-nfe/{id}/receive/      gera (ou devolve) a entrada em rascunho para a conferência
    POST /inbound-nfe/{id}/ignore/       marca a nota como ignorada (restore/ desfaz)
    POST /inbound-nfe/{id}/discard-entry/  volta da conferência: descarta a entrada em rascunho
    POST /inbound-nfe/{id}/undo-receipt/   desfaz o recebimento {reason}: estorna estoque e contas a pagar
    POST /inbound-nfe/items/{id}/create-product/   cadastra o produto a partir do item
    POST /inbound-nfe/items/{id}/ignore/           o item não entra no estoque (unignore/ desfaz)
    POST /inbound-nfe/items/{id}/unmap/            desfaz o vínculo {forget: esquece o aprendido}
"""
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.viewsets import TenantViewSet
from starrp.models import FiscalConfig, InboundNFe, InboundNFeItem
from starrp.models.platform import Module
from starrp.serializers import misc
from starrp.serializers import wms as s
from starrp.serializers.stock import StockDocumentSerializer
from starrp.services import dfe, inbound_nfe, nfe_receiving, stock, stock_documents

MAX_XML_BYTES = 5 * 1024 * 1024


class InboundNFeViewSet(TenantViewSet):
    model = InboundNFe
    serializer_class = misc.InboundNFeSerializer
    permission_code = "inbound_nfe"
    required_module = Module.INBOUND_NFE
    http_method_names = ["get", "patch", "post", "head", "options"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    select_related = ("store", "fiscal_config")
    prefetch_related = ("items__variant__product", "items__variant__volumes", "stock_documents")
    filterset_fields = {"receiving": ["exact"], "fiscal_status": ["exact"], "manifestation": ["exact"],
                        "supplier": ["exact"], "store": ["exact"], "fiscal_config": ["exact"],
                        "xml_status": ["exact"], "issued_at": ["gte", "lte"]}
    search_fields = ["access_key", "number", "supplier_name", "supplier_document"]
    # Desfazer o recebimento estorna estoque: além da nota, precisa mexer no estoque.
    action_permissions = {"sync": "inbound_nfe.manage", "undo_receipt": "stock.manage"}

    # Etapa (`stage`) é derivada: o filtro traduz para as colunas que a compõem.
    STAGES = {
        "summary": Q(xml_status__in=["summary_only", "pending", "error"], ignored_at__isnull=True,
                        fiscal_status__in=["unknown", "authorized"]),
        "pending_mapping": Q(xml_status="available", ignored_at__isnull=True, receiving="not_started",
                                items__variant__isnull=True, items__ignored=False),
        "checking": Q(xml_status="available", receiving="not_started", stock_documents__status="draft",
                         stock_documents__deleted_at__isnull=True),
        "received": Q(receiving__in=["received", "divergent"]),
        "cancelled": Q(fiscal_status="cancelled"),
        "ignored": Q(ignored_at__isnull=False),
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        stage = self.request.query_params.get("stage")
        if stage in self.STAGES:
            queryset = queryset.filter(self.STAGES[stage]).distinct()
        return queryset

    def initial(self, request, *args, **kwargs):
        # O import aceita multipart (arquivo): a base exige corpo JSON-objeto.
        super(TenantViewSet, self).initial(request, *args, **kwargs)

    def _body(self, serializer_class):
        body = serializer_class(data=self.request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        return body.validated_data

    def _respond(self, nfe, status=200):
        nfe = InboundNFe.all_objects.prefetch_related("items__variant__product", "items__variant__volumes").get(pk=nfe.pk)
        return Response(self.get_serializer(nfe).data, status=status)

    @action(detail=False, methods=["post"])
    def sync(self, request):
        """Busca agora em cada CNPJ (dados fiscais) com a busca ligada. Um CNPJ que
        falha (sem certificado, intervalo da SEFAZ) não impede os outros."""
        configs = FiscalConfig.objects.filter(dfe_enabled=True, is_active=True)
        if request.data.get("config"):
            configs = configs.filter(pk=request.data["config"])
        results = []
        for config in configs:
            try:
                result = dfe.sync(config, request.user)
                results.append({"config": config.name, "ok": True, "notes": result["notes"],
                                "received": result["received"], "message": result["reason"]})
            except BusinessError as error:
                results.append({"config": config.name, "ok": False, "notes": 0, "received": 0,
                                "message": str(error.detail if hasattr(error, "detail") else error)})
        if not results:
            raise BusinessError("Nenhum CNPJ com a busca de notas ligada. Configure em Dados fiscais.",
                                code="dfe_no_config")
        return Response({"results": results, "notes": sum(r["notes"] for r in results)})

    @action(detail=True, methods=["post"])
    def science(self, request, pk=None):
        return self._respond(dfe.science(self.get_object(), request.user))

    @action(detail=True, methods=["post"])
    def download(self, request, pk=None):
        return self._respond(dfe.download(self.get_object(), request.user))

    @action(detail=True, methods=["post"])
    def manifest(self, request, pk=None):
        code = str(request.data.get("code", ""))
        if code not in ("210200", "210220", "210240"):
            raise BusinessError("Escolha confirmação (210200), desconhecimento (210220) ou não realizada (210240).")
        nfe = self.get_object()
        dfe.manifest(nfe, code, request.user, str(request.data.get("reason", "")))
        return self._respond(nfe)

    @action(detail=False, methods=["post"], url_path="import")
    def import_xml(self, request):
        if request.store is None:
            raise BusinessError("Selecione a filial destinatária (X-Store-ID).", code="store_required")
        data = self._body(s.NFeImportSerializer)
        upload = data.get("file")
        if upload is not None and upload.size > MAX_XML_BYTES:
            raise BusinessError("Arquivo grande demais para um XML de NF-e.")
        content = upload.read() if upload is not None else data["xml"].encode("utf-8")
        return self._respond(inbound_nfe.import_xml(request.store, content, request.user), status=201)

    @action(detail=True, methods=["post"], url_path="map-item")
    def map_item(self, request, pk=None):
        nfe = self.get_object()
        data = self._body(s.NFeMapItemSerializer)
        if data["item"].nfe_id != nfe.pk:
            raise BusinessError("O item não pertence a esta nota.")
        inbound_nfe.map_item(data["item"], data["variant"], data["conversion_factor"], request.user)
        return self._respond(nfe)

    @action(detail=True, methods=["post"])
    def rematch(self, request, pk=None):
        nfe = self.get_object()
        inbound_nfe.auto_match(nfe)
        return self._respond(nfe)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        data = self._body(s.NFeReceiveSerializer)
        nfe = self.get_object()
        warehouse = data.get("warehouse") or stock.default_warehouse(nfe.store)
        doc = nfe_receiving.build_entry(nfe, warehouse, request.user, bin=data.get("bin"))
        if data["post"]:  # receber e aprovar de uma vez: quem pediu responde pela contagem
            doc = stock_documents.post(stock_documents.check(doc, request.user), request.user)
        return Response(StockDocumentSerializer(doc, context=self.get_serializer_context()).data, status=201)

    @action(detail=True, methods=["post"], url_path="discard-entry")
    def discard_entry(self, request, pk=None):
        nfe = self.get_object()
        inbound_nfe.discard_entry(nfe, request.user)
        return self._respond(nfe)

    @action(detail=True, methods=["post"], url_path="undo-receipt")
    def undo_receipt(self, request, pk=None):
        nfe = self.get_object()
        inbound_nfe.undo_receipt(nfe, request.user, str(request.data.get("reason", "")))
        return self._respond(nfe)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._respond(inbound_nfe.restore(self.get_object()))

    @action(detail=True, methods=["post"])
    def ignore(self, request, pk=None):
        nfe = self.get_object()
        if nfe_receiving.open_entry(nfe) is not None:
            raise StateConflict("A nota tem entrada de estoque: descarte a conferência ou desfaça o recebimento antes.")
        nfe.ignored_at, nfe.ignored_by = timezone.now(), request.user
        nfe.ignored_reason = str(request.data.get("reason", ""))
        nfe.save(update_fields=["ignored_at", "ignored_by", "ignored_reason", "updated_at"])
        return self._respond(nfe)


class InboundNFeItemViewSet(TenantViewSet):
    model = InboundNFeItem
    serializer_class = misc.InboundNFeItemSerializer
    permission_code = "inbound_nfe"
    required_module = Module.INBOUND_NFE
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("variant__product", "nfe")
    filterset_fields = ["nfe", "variant", "ignored"]

    @action(detail=True, methods=["post"], url_path="create-product")
    def create_product(self, request, pk=None):
        item = self.get_object()
        inbound_nfe.product_from_item(item, request.user, price=request.data.get("price"))
        return Response(self.get_serializer(InboundNFeItem.all_objects.get(pk=item.pk)).data, status=201)

    @action(detail=True, methods=["post"])
    def ignore(self, request, pk=None):
        item = inbound_nfe.ignore_item(self.get_object(), str(request.data.get("reason", "")), request.user)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def unignore(self, request, pk=None):
        item = inbound_nfe.unignore_item(self.get_object(), request.user)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def unmap(self, request, pk=None):
        item = inbound_nfe.unmap_item(self.get_object(), request.user, forget=request.data.get("forget", True) is not False)
        return Response(self.get_serializer(item).data)

