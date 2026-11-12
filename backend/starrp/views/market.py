"""Precificação (Vendas → Precificação): o processo de cada produto e as ofertas que embasam.

GET  /api/v1/price-checks/                   lista (filtros: status, position, worth_it, needs_review)
POST /api/v1/price-checks/<id>/approve/      {"price"?} aplica o preço sugerido (ou outro) no cadastro
POST /api/v1/price-checks/<id>/reject/       recusa (não volta a pedir na semana se o mercado não mexer)
POST /api/v1/price-checks/<id>/refresh/      manda reler o mercado deste produto
POST /api/v1/price-checks/run/               começa a rodada: o que está na vez nas regras, em lotes, no worker
GET  /api/v1/price-checks/run-status/        quanto falta da rodada
POST /api/v1/price-checks/product/           {"product"} cria o processo e manda ler este produto, fora das regras
GET/POST /api/v1/price-checks/rules/         as regras: quais produtos a leitura pega
GET  /api/v1/market-offers/?price_check=<id> as ofertas da última leitura
CRUD /api/v1/competitor-prices/              preços de concorrentes informados pela equipe
POST /api/v1/competitor-prices/import/       planilha (`file`): produto, concorrente, preço, data, link

A leitura roda no worker: a resposta volta na hora, com `reading` verdadeiro, e a tela relê até terminar.
Tudo pede o módulo `pricing`, liberado pela plataforma (plano ou admin do Django).
Ver pede `catalog.view`; decidir e reler pedem `catalog.manage` (é o preço do cadastro).
"""
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import TenantViewSet
from starrp.models import BackgroundTask, CompetitorPrice, MarketOffer, Module, PriceCheck
from starrp.serializers.market import (
    CompetitorPriceSerializer, MarketOfferSerializer, PriceCheckDetailSerializer, PriceCheckSerializer,
    PriceScopeSerializer,
)
from starrp.services import batches
from starrp.services.market import competitors, scope, tracker

MANAGE = "catalog.manage"


def _ready(account):
    if not account.price_tracking_enabled:
        raise BusinessError("Ligue o rastreamento em Configurações da conta → Cosmos.", code="price_tracking_off")


class PriceCheckViewSet(TenantViewSet):
    model = PriceCheck
    serializer_class = PriceCheckSerializer
    permission_code = "catalog"
    required_module = Module.PRICING
    action_permissions = {"approve": MANAGE, "reject": MANAGE, "refresh": MANAGE, "run": MANAGE, "product": MANAGE,
                          "rules": MANAGE}
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("variant__product", "decided_by")
    filterset_fields = ("status", "position", "worth_it", "needs_review", "variant", "variant__product")
    search_fields = ["variant__product__name", "variant__sku"]
    audit = False

    def get_serializer_class(self):
        return PriceCheckSerializer if self.action == "list" else PriceCheckDetailSerializer

    def create(self, request, *args, **kwargs):
        raise BusinessError("O processo nasce da leitura do mercado.", code="price_check_readonly")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        check = tracker.approve(self.get_object(), request.user, request.data.get("price"))
        return Response(self.get_serializer(check).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return Response(self.get_serializer(tracker.reject(self.get_object(), request.user)).data)

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        _ready(request.account)
        check = self.get_object()
        tracker.start(request.account, [check.variant], request.user)
        check.refresh_from_db()
        return Response(self.get_serializer(check).data)

    @action(detail=False, methods=["post"])
    def run(self, request):
        _ready(request.account)
        state = batches.start(BackgroundTask.Kind.PRICE_ROUND, request.account, user=request.user)
        if not state["total"]:
            raise BusinessError("Nada na vez: os produtos das regras já foram lidos ou o limite do mês acabou.", code="price_nothing_due")
        return Response({"checked": state["total"], **state})

    @action(detail=False, methods=["get"], url_path="run-status")
    def run_status(self, request):
        return Response(batches.status(BackgroundTask.Kind.PRICE_ROUND, request.account))

    @action(detail=False, methods=["post"])
    def product(self, request):
        # É um clique neste produto: não pede o rastreamento automático ligado.
        product_id = serializers.UUIDField().run_validation(request.data.get("product"))
        checks = tracker.start_product(request.account, product_id, request.user)
        return Response({"checked": len(checks), "ids": [str(check.pk) for check in checks]})

    @action(detail=False, methods=["get", "post"])
    def rules(self, request):
        account = request.account
        if request.method == "POST":
            body = PriceScopeSerializer(data=request.data, context={"account": account})
            body.is_valid(raise_exception=True)
            account.price_scope = body.data
            account.save(update_fields=["price_scope", "updated_at"])
        return Response({**scope.of(account), "in_scope": tracker.trackable(account).count()})


class MarketOfferViewSet(TenantViewSet):
    model = MarketOffer
    serializer_class = MarketOfferSerializer
    permission_code = "catalog"
    required_module = Module.PRICING
    http_method_names = ["get", "head", "options"]
    filterset_fields = ("price_check", "used")
    audit = False


class CompetitorPriceViewSet(TenantViewSet):
    """Salvar ou apagar recalcula o processo do produto na hora, sem gastar consulta de fonte paga."""

    model = CompetitorPrice
    serializer_class = CompetitorPriceSerializer
    permission_code = "catalog"
    required_module = Module.PRICING
    action_permissions = {"import_sheet": MANAGE}
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    select_related = ("variant__product",)
    filterset_fields = ("variant", "variant__product", "competitor")
    search_fields = ["competitor", "variant__product__name", "variant__sku"]

    def perform_create(self, serializer):
        super().perform_create(serializer)
        competitors.recalculate([serializer.instance.variant])

    def perform_update(self, serializer):
        super().perform_update(serializer)
        competitors.recalculate([serializer.instance.variant])

    def perform_destroy(self, instance):
        variant = instance.variant
        super().perform_destroy(instance)
        competitors.recalculate([variant])

    @action(detail=False, methods=["post"], url_path="import")
    def import_sheet(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise BusinessError("Envie a planilha no campo `file`.", code="file_required")
        return Response(competitors.import_sheet(request.account, request.user, upload.name, upload.read()))
