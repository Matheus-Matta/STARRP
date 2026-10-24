"""Tabelas de frete (cadastro + cotação) e definições de metacampos."""
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import TenantViewSet
from starrp.models import FreightTable, MetafieldDefinition
from starrp.serializers import logistics as s
from starrp.services import freight


class FreightTableViewSet(TenantViewSet):
    """Cadastro em Configurações; ler e cotar é de quem vende (PDV)."""

    model = FreightTable
    serializer_class = s.FreightTableSerializer
    permission_code = "logistics"
    action_permissions = {"list": "sales.view", "retrieve": "sales.view", "quote": "sales.view"}
    filterset_fields = ["kind", "store", "is_active"]
    search_fields = ["name"]
    prefetch_related = ("ranges",)

    @action(detail=False, methods=["get"])
    def quote(self, request):
        """GET ?zip=01001000 → as cotações de todas as tabelas ativas da loja."""
        zip_code = request.query_params.get("zip", "")
        try:
            results = freight.quotes(request.account.pk, getattr(request.store, "pk", None), zip_code)
        except freight.FreightUnavailable as error:
            raise BusinessError(str(error), code="zip_invalid") from error
        return Response([q.as_dict() for q in results])


class MetafieldDefinitionViewSet(TenantViewSet):
    """Campos da ficha técnica / metacampos. Ler é de todos (os formulários montam os campos)."""

    model = MetafieldDefinition
    serializer_class = s.MetafieldDefinitionSerializer
    permission_code = "settings"
    action_permissions = {"list": None, "retrieve": None}
    filterset_fields = ["owner", "type", "is_active", "show_in_specs"]
    search_fields = ["name", "key"]
    prefetch_related = ("categories",)
