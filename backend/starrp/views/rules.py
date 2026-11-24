"""Regras compartilhadas entre filiais: cadastro com a padrão protegida (models/rules.py)."""
from django.db.models import Prefetch
from rest_framework.exceptions import PermissionDenied

from starrp.core.viewsets import TenantViewSet
from starrp.models import LogisticsRule, Store, StockRule, StoreRule
from starrp.serializers import rules as s
from starrp.services.store_access import scope_to_allowed


class SharedRuleViewSet(TenantViewSet):
    """Cria, edita e exclui. A exclusão (inclusive em massa) passa por `check_deletable`:
    a padrão, a última e a regra em uso por filial ficam."""

    filterset_fields = ["is_default"]
    search_fields = ["name"]
    ordering_fields = ["name", "is_default", "created_at"]

    def check_writable(self, instance):
        """A regra é compartilhada (M-07): quem é de algumas filiais só altera a que é usada SÓ por elas."""
        super().check_writable(instance)
        if self._restricted() and (instance.is_default or instance.stores_using().exclude(
                pk__in=self.request.allowed_store_ids).exists()):
            raise PermissionDenied("Esta regra é usada por outras filiais; só quem acessa a rede pode alterá-la.")

    def save_kwargs(self, serializer, creating):
        if self._restricted() and serializer.validated_data.get("is_default"):
            raise PermissionDenied("A regra padrão vale para a rede; só quem acessa a rede pode definir.")
        return super().save_kwargs(serializer, creating)

    def get_queryset(self):
        # Filiais que usam cada regra numa query só (o serializer lê `stores_alive`; antes: 2 por regra).
        return super().get_queryset().prefetch_related(Prefetch(
            # Só as que o usuário acessa (B-09): o nome das outras não aparece.
            "stores", scope_to_allowed(Store.all_objects.filter(deleted_at__isnull=True), "pk").order_by("name"),
            to_attr="stores_alive"))


class StoreRuleViewSet(SharedRuleViewSet):
    model = StoreRule
    serializer_class = s.StoreRuleSerializer
    permission_code = "settings"


class LogisticsRuleViewSet(SharedRuleViewSet):
    model = LogisticsRule
    serializer_class = s.LogisticsRuleSerializer
    permission_code = "logistics"
    select_related = ("entry_lot_label", "entry_product_label", "conference_label")


class StockRuleViewSet(SharedRuleViewSet):
    model = StockRule
    serializer_class = s.StockRuleSerializer
    permission_code = "stock"
