"""Tabelas de frete (cadastro + cotação) e definições de metacampos."""
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.text import only_digits
from starrp.core.viewsets import TenantViewSet
from starrp.models import FreightTable, LogisticsSettings, MetafieldDefinition
from starrp.serializers import logistics as s
from starrp.services import freight, logistics_settings


class FreightTableViewSet(TenantViewSet):
    """Cadastro em Configurações; ler e cotar é de quem vende (PDV)."""

    model = FreightTable
    serializer_class = s.FreightTableSerializer
    permission_code = "logistics"
    action_permissions = {"list": "sales.view", "retrieve": "sales.view", "quote": "sales.view",
                          "estimate": "sales.view"}
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


    @action(detail=False, methods=["get"])
    def estimate(self, request):
        """Conferir frete no PDV: `?zip=` OU o endereço (`street`, `number`, `district`, `city`, `state`).
        Endereço: o CEP vem da ViaCEP (para as tabelas por faixa) e a coordenada do OpenStreetMap
        (para as por distância, medidas até o endereço exato)."""
        params = request.query_params
        found, point = None, None
        zip_code = only_digits(params.get("zip", ""))
        if not zip_code:
            street, city, state = params.get("street", ""), params.get("city", ""), params.get("state", "")
            if not (street and city and state):
                raise BusinessError("Informe o CEP ou o endereço (logradouro, cidade e UF).", code="address_required")
            found = freight.zip_for_address(street, city, state, params.get("district", ""))
            zip_code = found["zip_code"] if found else ""
            point = freight.geocode_address(street, params.get("number", ""), city, state, params.get("district", ""))
            if not zip_code and point is None:
                raise BusinessError("Endereço não encontrado: confira o logradouro, a cidade e a UF.",
                                    code="address_not_found")
        try:
            results = freight.quotes(request.account.pk, getattr(request.store, "pk", None), zip_code, point)
        except freight.FreightUnavailable as error:
            raise BusinessError(str(error), code="zip_invalid") from error
        return Response({"zip_code": zip_code or None, "address": found,
                         "point": [str(point[0]), str(point[1])] if point else None,
                         "quotes": [q.as_dict() for q in results]})


class LogisticsSettingsViewSet(TenantViewSet):
    """Uma configuração por filial: lista todas (nascem sozinhas) e edita; não cria nem exclui."""

    model = LogisticsSettings
    serializer_class = s.LogisticsSettingsSerializer
    permission_code = "logistics"
    http_method_names = ["get", "patch", "put", "head", "options"]
    select_related = ("store",)
    filterset_fields = ["store"]

    def list(self, request, *args, **kwargs):
        logistics_settings.ensure_all(request.account.pk)
        return super().list(request, *args, **kwargs)


class MetafieldDefinitionViewSet(TenantViewSet):
    """Campos da ficha técnica / metacampos. Ler é de todos (os formulários montam os campos)."""

    model = MetafieldDefinition
    serializer_class = s.MetafieldDefinitionSerializer
    permission_code = "settings"
    action_permissions = {"list": None, "retrieve": None}
    filterset_fields = ["owner", "type", "is_active", "show_in_specs"]
    search_fields = ["name", "key"]
    prefetch_related = ("categories",)
