"""Regras compartilhadas entre filiais: cadastro com a padrão protegida (models/rules.py)."""
from starrp.core.viewsets import TenantViewSet
from starrp.models import LogisticsRule, StockRule, StoreRule
from starrp.serializers import rules as s


class SharedRuleViewSet(TenantViewSet):
    """Cria, edita e exclui. A exclusão (inclusive em massa) passa por `check_deletable`:
    a padrão, a última e a regra em uso por filial ficam."""

    filterset_fields = ["is_default"]
    search_fields = ["name"]
    ordering_fields = ["name", "is_default", "created_at"]


class StoreRuleViewSet(SharedRuleViewSet):
    model = StoreRule
    serializer_class = s.StoreRuleSerializer
    permission_code = "settings"


class LogisticsRuleViewSet(SharedRuleViewSet):
    model = LogisticsRule
    serializer_class = s.LogisticsRuleSerializer
    permission_code = "logistics"


class StockRuleViewSet(SharedRuleViewSet):
    model = StockRule
    serializer_class = s.StockRuleSerializer
    permission_code = "stock"
