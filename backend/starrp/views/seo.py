"""Analítico de SEO (Vendas): nota do cadastro de cada produto, problemas e sugestões.

GET  /api/v1/seo-checks/                 lista (filtros: status, product)
POST /api/v1/seo-checks/product/         {"product"} cria a análise e manda para o worker
POST /api/v1/seo-checks/run/             começa a rodada: tudo o que está nas regras, em lotes, no worker
GET  /api/v1/seo-checks/run-status/      quanto falta da rodada
GET/POST /api/v1/seo-checks/rules/       as regras: quais produtos a análise pega
POST /api/v1/seo-checks/<id>/refresh/    analisa de novo
POST /api/v1/seo-checks/<id>/apply/      {"fields": ["name", "seo_title", "seo_description", "slug"]} grava as aprovadas
POST /api/v1/seo-checks/<id>/reject/     recusa as sugestões

Pede o módulo `seo`, liberado pela plataforma. Ver pede `catalog.view`; o resto, `catalog.manage`.
"""
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import TenantViewSet
from starrp.models import BackgroundTask, Module, SeoCheck
from starrp.serializers.market import PriceScopeSerializer
from starrp.serializers.seo import SeoCheckDetailSerializer, SeoCheckSerializer
from starrp.services import batches
from starrp.services.market import scope
from starrp.services.seo import analyzer

MANAGE = "catalog.manage"


class SeoCheckViewSet(TenantViewSet):
    model = SeoCheck
    serializer_class = SeoCheckSerializer
    permission_code = "catalog"
    required_module = Module.SEO
    action_permissions = {"product": MANAGE, "run": MANAGE, "rules": MANAGE, "refresh": MANAGE, "apply": MANAGE, "reject": MANAGE}
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("product", "decided_by")
    filterset_fields = ("status", "product")
    search_fields = ["product__name"]
    audit = False

    def get_serializer_class(self):
        return SeoCheckSerializer if self.action == "list" else SeoCheckDetailSerializer

    def create(self, request, *args, **kwargs):
        raise BusinessError("A análise nasce pelo botão do produto ou por \"Analisar agora\".", code="seo_check_readonly")

    @action(detail=False, methods=["post"])
    def product(self, request):
        product_id = serializers.UUIDField().run_validation(request.data.get("product"))
        check = analyzer.start_product(request.account, product_id, request.user)
        return Response({"id": str(check.pk)})

    @action(detail=False, methods=["post"])
    def run(self, request):
        state = batches.start(BackgroundTask.Kind.SEO_ROUND, request.account, user=request.user)
        if not state["total"]:
            raise BusinessError("Nenhum produto nas regras para analisar.", code="seo_nothing_due")
        return Response({"checked": state["total"], **state})

    @action(detail=False, methods=["get"], url_path="run-status")
    def run_status(self, request):
        return Response(batches.status(BackgroundTask.Kind.SEO_ROUND, request.account))

    @action(detail=False, methods=["get", "post"])
    def rules(self, request):
        account = request.account
        if request.method == "POST":
            body = PriceScopeSerializer(data=request.data, context={"account": account})
            body.is_valid(raise_exception=True)
            account.seo_scope = body.data
            account.save(update_fields=["seo_scope", "updated_at"])
        return Response({**scope.of(account, "seo_scope"), "in_scope": analyzer.in_scope_count(account)})

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        check = self.get_object()
        analyzer.start(request.account, [check.product], request.user)
        check.refresh_from_db()
        return Response(self.get_serializer(check).data)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        fields = serializers.ListField(child=serializers.CharField()).run_validation(request.data.get("fields"))
        return Response(self.get_serializer(analyzer.apply(self.get_object(), request.user, fields)).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return Response(self.get_serializer(analyzer.reject(self.get_object(), request.user)).data)
