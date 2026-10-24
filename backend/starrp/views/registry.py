"""Cadastros e configurações: views declarativas (CRUD + filtros)."""
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response

from rest_framework.exceptions import PermissionDenied

from starrp.core.bulk import bulk_action
from starrp.core.bulk_helpers import add_tags, related_param
from starrp.core.errors import StateConflict
from starrp.core.viewsets import ReadOnlyTenantViewSet, SystemDataViewSet, TenantViewSet
from starrp.models import (
    Customer, CustomerAddress, CustomerGroup, Permission, Role, Store, Supplier, Tag, Terminal, UserProfile,
)
from starrp.serializers import company, partners, users
from starrp.services.store_access import sellers_of, visible_profiles


class CustomerGroupViewSet(TenantViewSet):
    model = CustomerGroup
    serializer_class = partners.CustomerGroupSerializer
    permission_code = "partners"
    filterset_fields = ["is_active"]
    search_fields = ["name", "description"]


class CustomerViewSet(TenantViewSet):
    model = Customer
    serializer_class = partners.CustomerSerializer
    permission_code = "partners"
    prefetch_related = ("addresses", "groups", "tags")
    filterset_fields = ["person_type", "is_active", "groups"]
    search_fields = ["name", "legal_name", "document", "phone", "email"]
    ordering_annotations = {"credit_balance": Sum("credits__amount", filter=Q(credits__deleted_at__isnull=True))}

    @bulk_action("Adicionar a um grupo", icon="pi pi-bookmark", params=[
        {"name": "group", "label": "Grupo", "type": "relation", "required": True, "creatable": True,
         "relation": {"endpoint": "/customers/groups/"}}])
    def bulk_add_group(self, request, queryset, params):
        group = related_param(request, params, "group", CustomerGroup, "o grupo")
        for customer in queryset:
            self.check_writable(customer)
            customer.groups.add(group)
        return {"affected": queryset.count()}

    @bulk_action("Adicionar tags", icon="pi pi-hashtag", params=[
        {"name": "tags", "label": "Tags", "type": "tags", "required": True,
         "tagSource": {"endpoint": "/tags/", "params": {"scope": "customer"}}}])
    def bulk_add_tags(self, request, queryset, params):
        return add_tags(self, request, queryset, params, Tag.Scope.CUSTOMER)

    def get_queryset(self):
        from starrp.views.catalog import filter_by_tag

        return filter_by_tag(super().get_queryset(), self.request)


class CustomerAddressViewSet(TenantViewSet):
    model = CustomerAddress
    serializer_class = partners.CustomerAddressSerializer
    permission_code = "partners"
    filterset_fields = ["customer"]


class SupplierViewSet(TenantViewSet):
    model = Supplier
    serializer_class = partners.SupplierSerializer
    permission_code = "partners"
    filterset_fields = ["is_active"]
    search_fields = ["name", "legal_name", "document"]


class StoreViewSet(TenantViewSet):
    model = Store
    serializer_class = company.StoreSerializer
    permission_code = "settings"
    # O seletor de loja precisa listar mesmo para quem não gerencia lojas.
    action_permissions = {"list": None, "retrieve": None}
    filterset_fields = ["is_active", "state"]
    search_fields = ["name", "legal_name", "cnpj", "city"]

    def perform_create(self, serializer):
        from starrp.services.provisioning import create_store

        if self._restricted():
            raise PermissionDenied("Só quem acessa todas as lojas pode criar uma loja nova.")

        data = dict(serializer.validated_data)
        raw = data.pop("cash_action_password", None)
        store = create_store(self.request.account, data.pop("name"), **data)
        if raw:
            store.set_cash_action_password(raw)
            store.save(update_fields=["cash_action_password"])
        serializer.instance = store


class TerminalViewSet(TenantViewSet):
    model = Terminal
    serializer_class = company.TerminalSerializer
    permission_code = "settings"
    filterset_fields = ["device_type", "is_active"]

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        terminal = self.get_object()
        terminal.is_active, terminal.revoked_at = False, timezone.now()
        terminal.revoked_reason = request.data.get("reason", "")
        terminal.save()
        return Response(self.get_serializer(terminal).data)


class PermissionViewSet(ReadOnlyTenantViewSet):
    serializer_class = users.PermissionSerializer
    queryset = Permission.objects.all()
    permission_code = "users"

    def get_queryset(self):
        return Permission.objects.all()


class RoleViewSet(SystemDataViewSet):
    """Cargos FIXOS: nascem com a conta (catálogo em `services/access_catalog.py`). A conta lê
    e ajusta desconto/ativo; criar, excluir e mudar permissões é do suporte."""

    SYSTEM_MESSAGE = "Cargos são fixos do sistema: combine cargos no usuário em vez de criar um novo."
    model = Role
    serializer_class = users.RoleSerializer
    permission_code = "users"
    prefetch_related = ("permissions",)
    filterset_fields = ["is_active", "is_system", "area"]
    search_fields = ["name", "area"]
    ordering_fields = ["rank", "name", "area"]

    def perform_destroy(self, instance):
        if instance.profiles.filter(deleted_at__isnull=True).exists():
            raise StateConflict("Há usuários neste cargo.")
        super().perform_destroy(instance)


class UserProfileViewSet(TenantViewSet):
    model = UserProfile
    serializer_class = users.UserProfileSerializer
    permission_code = "users"
    select_related = ("user", "role", "default_store")
    prefetch_related = ("stores",)
    filterset_fields = ["role", "stores", "all_stores", "is_active", "is_seller"]

    def get_queryset(self):
        return visible_profiles(super().get_queryset())
    search_fields = ["user__username", "user__first_name", "user__last_name", "seller_code"]

    action_permissions = {"sellers": None}

    @action(detail=False, methods=["get"])
    def sellers(self, request):
        """Lista curta de vendedores ativos para o seletor do PDV."""
        if request.store is None:
            raise StateConflict("Selecione a loja (X-Store-ID) para listar os vendedores dela.")
        rows = sellers_of(request.store)
        return Response([
            {"user_id": p.user_id, "name": p.user.get_full_name() or p.user.username, "code": p.seller_code}
            for p in rows
        ])

    def perform_destroy(self, instance):
        if instance.user_id == self.request.user.pk:
            raise StateConflict("Você não pode excluir o próprio usuário.")
        instance.user.is_active = False
        instance.user.save(update_fields=["is_active"])
        super().perform_destroy(instance)

