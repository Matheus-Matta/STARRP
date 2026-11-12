"""WMS (endereços e saldo por endereço) e impressão de etiquetas."""
from django.db import transaction
from django.http import HttpResponse
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.errors import BusinessError
from starrp.core.permissions import has_permission_code
from starrp.core.viewsets import ReadOnlyTenantViewSet, TenantViewSet
from starrp.models import BinBalance, StockAdvice, StorageBin
from starrp.models.platform import Module
from starrp.serializers import wms as s
from starrp.services import labels
from starrp.services.cosmos import slotting


class StorageBinViewSet(TenantViewSet):
    model = StorageBin
    serializer_class = s.StorageBinSerializer
    permission_code = "stock"
    required_module = Module.STOCK
    select_related = ("warehouse",)
    filterset_fields = ["warehouse", "kind", "aisle", "is_active"]
    search_fields = ["code"]

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def generate(self, request):
        body = s.GenerateBinsSerializer(data=request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        data = body.validated_data
        warehouse = data["warehouse"]
        if not warehouse.uses_bins:
            raise BusinessError("Ligue o controle por endereço (WMS) no depósito antes de gerar endereços.")
        existing = set(StorageBin.objects.filter(warehouse=warehouse).values_list("code", flat=True))
        sequence = StorageBin.objects.filter(warehouse=warehouse).count()
        created = []
        for aisle in data["aisles"]:
            for rack in range(1, data["racks"] + 1):
                for level in range(1, data["levels"] + 1):
                    code = f"{aisle.upper()}-{rack:02d}-{level}"
                    sequence += 1
                    if code in existing:
                        continue
                    created.append(StorageBin(account=request.account, warehouse=warehouse, code=code,
                                              aisle=aisle.upper(), rack=f"{rack:02d}", level=str(level),
                                              kind=data["kind"], sequence=sequence, created_by=request.user))
        StorageBin.all_objects.bulk_create(created)
        return Response({"created": len(created), "skipped": len(existing)}, status=201)


class BinBalanceViewSet(ReadOnlyTenantViewSet):
    """Onde está cada produto: endereço, lote, validade e quantidade."""

    model = BinBalance
    serializer_class = s.BinBalanceSerializer
    permission_code = "stock"
    required_module = Module.STOCK
    select_related = ("bin", "variant__product", "lot")
    ordering_map = {"variant_name": "variant__product__name", "sku": "variant__sku"}
    filterset_fields = {"bin": ["exact"], "bin__warehouse": ["exact"], "variant": ["exact"], "lot": ["exact"],
                        "quantity": ["gt"]}
    search_fields = ["bin__code", "variant__product__name", "variant__sku"]


class StockAdviceViewSet(TenantViewSet):
    """Organização do estoque: o que a Cosmos recomenda mudar nos endereços.

    POST /stock/advices/run/          analisa agora
    POST /stock/advices/<id>/apply/   cria a movimentação em rascunho (o estoque só muda quando ela for confirmada)
    POST /stock/advices/<id>/dismiss/ recusa

    Pede os módulos `stock` e `cosmos` e o interruptor da conta. Ver pede `stock.view`; o resto, `stock.manage`.
    """

    model = StockAdvice
    serializer_class = s.StockAdviceSerializer
    permission_code = "stock"
    required_module = Module.STOCK
    action_permissions = {"run": "stock.manage", "apply": "stock.manage", "dismiss": "stock.manage"}
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("warehouse", "document", "decided_by")
    filterset_fields = ("status", "kind", "warehouse")
    search_fields = ["title"]
    audit = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not slotting.enabled(request.account):
            raise PermissionDenied("A Cosmos no estoque não está ativa nesta conta.")

    def create(self, request, *args, **kwargs):
        raise BusinessError("A recomendação nasce da análise: use \"Analisar agora\".", code="stock_advice_readonly")

    @action(detail=False, methods=["post"])
    def run(self, request):
        return Response({"opened": slotting.analyze(request.account), "open": self.get_queryset().filter(status=StockAdvice.Status.OPEN).count()})

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        return Response(self.get_serializer(slotting.apply(self.get_object(), request.user)).data)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        return Response(self.get_serializer(slotting.dismiss(self.get_object(), request.user)).data)


class LabelPrintView(APIView):
    """POST /stock/labels/print/ {"template": id, "items": [{"id", "copies"}]} → HTML para imprimir.

    O tipo de item (produto, lote ou endereço) vem do `subject` do modelo de etiqueta.
    """

    def post(self, request):
        body = s.LabelPrintSerializer(data=request.data, context={"request": request})
        body.is_valid(raise_exception=True)
        template = body.validated_data.get("template") or labels.default_template(
            request.account.pk, body.validated_data["subject"])
        if template is None:
            raise BusinessError("Nenhum modelo de etiqueta ativo deste tipo. Cadastre em Estoque › Modelos de etiqueta.",
                                code="no_label_template")
        area = "catalog" if template.subject == template.Subject.PRODUCT else "stock"
        if not has_permission_code(request.user, f"{area}.view"):
            raise PermissionDenied()
        rows = labels.labels_for(template.subject, body.validated_data["items"], getattr(request.store, "pk", None))
        if not rows:
            raise BusinessError("Nenhum item encontrado para imprimir.")
        return HttpResponse(labels.render(template, rows), content_type="text/html; charset=utf-8")
