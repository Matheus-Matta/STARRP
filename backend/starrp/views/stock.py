import math

from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import BusinessError, StateConflict
from starrp.core.text import decimals_as_text
from starrp.core.viewsets import ReadOnlyTenantViewSet, TenantViewSet
from starrp.models import (
    LabelTemplate, ProductVariant, ReceivingDivergence, StockBalance, StockDocument, StockLot, StockMovement,
    StockSettings, Warehouse,
)
from starrp.models.platform import Module
from starrp.serializers import stock as s
from starrp.services import labels, picking, stock_documents, volumes


class StockView:
    required_module = Module.STOCK
    permission_code = "stock"


class StockSettingsViewSet(StockView, TenantViewSet):
    model = StockSettings
    serializer_class = s.StockSettingsSerializer


class WarehouseViewSet(StockView, TenantViewSet):
    model = Warehouse
    serializer_class = s.WarehouseSerializer
    tree_parent = "parent"
    filterset_fields = ["kind", "is_active", "is_default", "uses_bins"]
    search_fields = ["name"]
    # O PDV precisa ler o depósito padrão mesmo sem o módulo de estoque.
    required_module = Module.BASE


# Colunas que vêm de propriedade (nome com a variação) ordenam pelo nome do produto.
VARIANT_ORDERING = {"variant_name": "variant__product__name", "sku": "variant__sku"}


class StockBalanceViewSet(StockView, ReadOnlyTenantViewSet):
    model = StockBalance
    serializer_class = s.StockBalanceSerializer
    ordering_map = VARIANT_ORDERING
    select_related = ("variant__product", "warehouse")
    filterset_fields = ["warehouse", "variant", "variant__product"]
    search_fields = ["variant__product__name", "variant__sku"]

    @action(detail=False, methods=["get"])
    def alerts(self, request):
        """Variantes abaixo do estoque mínimo (somando todos os depósitos da loja)."""
        qs = ProductVariant.objects.filter(
            product__track_stock=True, product__type__in=["simple", "variable"], min_stock__isnull=False,
            is_active=True, product__is_active=True,
        )
        store = getattr(request, "store", None)
        allowed = getattr(request, "allowed_store_ids", None)
        if store is not None:
            balance_filter = {"balances__warehouse__store": store}
        elif allowed is not None:
            balance_filter = {"balances__warehouse__store__in": allowed}
        else:
            balance_filter = {}
        rows = (
            qs.filter(**balance_filter).annotate(stock=Sum("balances__quantity")).filter(stock__lt=F("min_stock"))
            .annotate(product_name=F("product__name"))
            .values("id", "product", "product_name", "name", "sku", "min_stock", "stock")[:500]
        )
        return Response(list(rows))


class StockLotViewSet(StockView, TenantViewSet):
    model = StockLot
    serializer_class = s.StockLotSerializer
    ordering_map = VARIANT_ORDERING
    http_method_names = ["get", "patch", "head", "options"]
    select_related = ("variant__product", "warehouse")
    filterset_fields = {"variant": ["exact"], "variant__product": ["exact"], "warehouse": ["exact"], "status": ["exact"],
                        "expires_at": ["lte", "gte"]}


class StockDocumentViewSet(StockView, TenantViewSet):
    model = StockDocument
    serializer_class = s.StockDocumentSerializer
    prefetch_related = ("items__variant__product", "items__variant__volumes")
    filterset_fields = {"kind": ["exact"], "status": ["exact"], "warehouse": ["exact"], "supplier": ["exact"],
                        "inbound_nfe": ["exact"], "effective_date": ["gte", "lte"]}
    search_fields = ["number", "external_number"]

    def perform_destroy(self, instance):
        if not instance.is_editable:
            raise StateConflict("Documento confirmado não é excluído: cancele-o.")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        return Response(self.get_serializer(stock_documents.post(self.get_object(), request.user)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        doc = stock_documents.cancel(self.get_object(), request.user, request.data.get("reason", ""))
        return Response(self.get_serializer(doc).data)

    @action(detail=True, methods=["get"], url_path="picking-list")
    def picking_list(self, request, pk=None):
        """Onde pegar cada item (endereço/lote), na ordem do caminho do depósito."""
        return Response(decimals_as_text(picking.picking_list(self.get_object())))

    @action(detail=True, methods=["get"])
    def labels(self, request, pk=None):
        """Etiquetas do que entrou: ?template=<id>. Produto: uma por unidade
        (vendido por peso: uma por linha). Lote: uma por lote gerado.
        Volume: uma por caixa de cada unidade (2 guarda-roupas em 3 caixas = 6)."""
        doc = self.get_object()
        template = get_object_or_404(LabelTemplate.objects, pk=request.query_params.get("template"))
        if template.subject == LabelTemplate.Subject.LOT:
            lot_ids = StockMovement.all_objects.filter(document_item__document=doc, lot__isnull=False).values_list(
                "lot_id", flat=True).distinct()
            rows = [{"id": lot_id, "copies": 1} for lot_id in lot_ids]
        else:
            rows = self._label_rows(doc, template)
        found = labels.labels_for(template.subject, rows, doc.store_id)
        return HttpResponse(labels.render(template, found), content_type="text/html; charset=utf-8")

    @staticmethod
    def _label_rows(doc, template):
        items = doc.items.select_related("variant__product").prefetch_related("variant__volumes")
        if template.subject == LabelTemplate.Subject.VOLUME:
            return [{"id": volume.pk, "copies": max(int(math.ceil(item.quantity)), 1)}
                    for item in items for volume in item.variant.volumes.all() if volume.deleted_at is None]
        return [{"id": item.variant_id,
                 "copies": 1 if item.variant.sold_by_weight else max(int(math.ceil(item.quantity)), 1)}
                for item in items]

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """Conclui a conferência: {"codes": [...]} grava o contado de cada produto;
        {"lines": [{"item", "ok"} | {"item", "ok": false, "arrived", "accepted", "reason", "notes"}]}
        é a conferência manual (se a Logística permitir); sem nada, vale a quantidade digitada.
        Depois disso a entrada pode ser aprovada."""
        codes, lines = request.data.get("codes"), request.data.get("lines")
        if codes is not None and (not isinstance(codes, list) or not all(isinstance(c, str) for c in codes)):
            raise BusinessError("Envie `codes` como lista de códigos lidos.")
        if lines is not None and (not isinstance(lines, list) or not all(isinstance(r, dict) for r in lines)):
            raise BusinessError("Envie `lines` como lista de {item, ok, ...}.")
        doc = stock_documents.check(self.get_object(), request.user, codes, lines)
        return Response(self.get_serializer(self.get_queryset().get(pk=doc.pk)).data)

    @action(detail=True, methods=["post"])
    def conference(self, request, pk=None):
        """Conferência por leitura: {"codes": [...]} com EAN/SKU (unidade) ou código
        de volume (caixa). Diz o que bate, o que falta e as caixas soltas."""
        codes = request.data.get("codes")
        if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
            raise BusinessError("Envie `codes` como lista de códigos lidos.")
        return Response(decimals_as_text(volumes.conference(self.get_object(), codes)))


class ReceivingDivergenceViewSet(StockView, ReadOnlyTenantViewSet):
    """Erros de entrada: o que a nota dizia × o que chegou × o que entrou, com o motivo."""

    model = ReceivingDivergence
    serializer_class = s.ReceivingDivergenceSerializer
    select_related = ("variant", "supplier", "document", "inbound_nfe", "checked_by")
    filterset_fields = {"supplier": ["exact"], "reason": ["exact"], "document": ["exact"],
                        "inbound_nfe": ["exact"], "variant": ["exact"], "created_at": ["gte", "lte"]}
    search_fields = ["variant__sku", "variant__product__name", "supplier__name", "notes"]


class StockMovementViewSet(StockView, ReadOnlyTenantViewSet):
    """Kardex: o razão imutável. Não há escrita direta aqui."""

    model = StockMovement
    serializer_class = s.StockMovementSerializer
    ordering_map = {**VARIANT_ORDERING, "operator_name": "operator__first_name"}
    select_related = ("variant__product", "warehouse", "lot")
    filterset_fields = {"variant": ["exact"], "variant__product": ["exact"], "warehouse": ["exact"], "kind": ["exact"],
                        "created_at": ["gte", "lte"], "document_item__document": ["exact"]}


class LabelTemplateViewSet(StockView, TenantViewSet):
    model = LabelTemplate
    serializer_class = s.LabelTemplateSerializer
    permission_code = "catalog"
    required_module = Module.BASE
    filterset_fields = ["subject", "is_system", "is_active", "is_default"]
    search_fields = ["name"]

    def perform_destroy(self, instance):
        if instance.is_system:
            raise StateConflict("Modelo pré-pronto do sistema: desative em vez de excluir.")
        super().perform_destroy(instance)
