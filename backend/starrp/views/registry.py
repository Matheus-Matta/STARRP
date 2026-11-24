"""Cadastros e configurações: views declarativas (CRUD + filtros)."""
from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from starrp.core.bulk import bulk_action
from starrp.core.bulk_helpers import add_tags, related_param
from starrp.core.errors import BusinessError, StateConflict
from starrp.core.viewsets import ReadOnlyTenantViewSet, SystemDataViewSet, TenantViewSet
from starrp.models import (
    Customer, CustomerAddress, CustomerCredit, CustomerGroup, Permission, Role, Store, Supplier, Tag, Terminal, UserProfile,
)
from starrp.serializers import company, operations, partners, users
from starrp.core.permissions import has_permission_code, is_account_admin
from starrp.services import customer_credits, fiscal_data, fiscal_emission
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
    action_permissions = {"grant_credit": "partners.credit"}

    def get_queryset(self):
        # `credit_balance` do serializer numa subquery (antes: uma soma por cliente). Subquery, e não
        # Sum com join, para o filtro por grupo/tag não multiplicar as linhas da soma.
        credits = (CustomerCredit.all_objects.filter(customer=OuterRef("pk"), deleted_at__isnull=True)
                   .order_by().values("customer").annotate(t=Sum("amount")).values("t"))
        from starrp.views.catalog import filter_by_tag

        return filter_by_tag(super().get_queryset(), self.request).annotate(credit_total=Subquery(credits))

    @extend_schema(request=partners.CustomerCreditGrantInput, responses={201: operations.CustomerCreditSerializer})
    @action(detail=True, methods=["post"], url_path="grant-credit")
    def grant_credit(self, request, pk=None):
        profile = getattr(request.user, "profile", None)
        is_director = bool(profile and any(role.code == "director" for role in profile.roles_all()))
        if not is_account_admin(request.user) and not is_director:
            raise PermissionDenied("Somente administradores da conta e diretores podem conceder crédito.")
        body = partners.CustomerCreditGrantInput(data=request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        credit = customer_credits.grant(self.get_object(), request.user, **body.validated_data)
        return Response(operations.CustomerCreditSerializer(credit).data, status=201)

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
    action_permissions = {"list": None, "retrieve": None, "fiscal": None, "fiscal_certificate": None}
    filterset_fields = ["is_active", "state", "kind", "parent"]
    search_fields = ["name", "legal_name", "cnpj", "city"]
    select_related = ("parent",)
    # Hierarquia: a lista abre a matriz e mostra quem responde a ela (`?root=1` / `?parent=`).
    tree_parent = "parent"

    def perform_create(self, serializer):
        from starrp.services.provisioning import create_store

        if self._restricted():
            raise PermissionDenied("Só quem acessa todas as filiais pode criar uma filial nova.")

        data = dict(serializer.validated_data)
        raw = data.pop("cash_action_password", None)
        store = create_store(self.request.account, data.pop("name"), **data)
        if raw:
            store.set_cash_action_password(raw)
            store.save(update_fields=["cash_action_password"])
        serializer.instance = store

    def initial(self, request, *args, **kwargs):
        # O certificado da aba "Nota fiscal" chega em multipart: a base exige corpo JSON-objeto.
        if self.action == "fiscal_certificate":
            return super(TenantViewSet, self).initial(request, *args, **kwargs)
        return super().initial(request, *args, **kwargs)

    def _fiscal_permission(self, request, write):
        if not has_permission_code(request.user, "fiscal.manage" if write else "fiscal.view"):
            raise PermissionDenied("A nota fiscal da filial é de quem administra o fiscal.")

    @action(detail=True, methods=["get", "post"])
    def fiscal(self, request, pk=None):
        """Aba "Nota fiscal" da filial. GET: a conferência da emissão (o que falta, o que cada PDV recebe).
        POST: grava ambiente, regime, emissão no PDV, contingência e CSC nos dados fiscais (cria pelo CNPJ)."""
        write = request.method == "POST"
        self._fiscal_permission(request, write)
        store = self.get_object()
        if write:
            fiscal_emission.apply_store_settings(store, request.data, request.user)
            store.refresh_from_db()
        return Response(fiscal_emission.readiness(store))

    @action(detail=True, methods=["post"], url_path="fiscal/certificate",
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def fiscal_certificate(self, request, pk=None):
        """Certificado A1 (.pfx + senha) nos dados fiscais da filial (cria pelo CNPJ se faltar)."""
        from starrp.views.fiscal import MAX_PFX_BYTES

        self._fiscal_permission(request, True)
        store = self.get_object()
        upload, password = request.data.get("file"), str(request.data.get("password", ""))
        if upload is None or not hasattr(upload, "read"):
            raise BusinessError("Envie o arquivo do certificado (.pfx).")
        if upload.size > MAX_PFX_BYTES:
            raise BusinessError("Arquivo grande demais para um certificado A1.")
        config = store.fiscal_config if store.fiscal_config and store.fiscal_config.deleted_at is None else None
        fiscal_data.save_certificate(config or fiscal_data.from_store(store, request.user), upload, password)
        store.refresh_from_db()
        return Response(fiscal_emission.readiness(store))


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
    """Cargos fixos: o administrador ajusta desconto, ativo e a matriz de permissões."""

    SYSTEM_MESSAGE = "Cargos são fixos: edite a matriz de um cargo existente."
    model = Role
    serializer_class = users.RoleSerializer
    permission_code = "users"
    prefetch_related = ("permissions",)
    filterset_fields = ["is_active", "is_system", "area"]
    search_fields = ["name", "area"]
    ordering_fields = ["rank", "name", "area"]

    def get_queryset(self):
        # `user_count` do serializer numa query só (antes: 2 contagens por cargo).
        return super().get_queryset().annotate(
            main_users=Count("profiles", filter=Q(profiles__deleted_at__isnull=True), distinct=True),
            extra_users=Count("extra_profiles", distinct=True, filter=Q(extra_profiles__deleted_at__isnull=True)
                              & ~Q(extra_profiles__role=F("pk"))),
        )

    def check_permissions(self, request):
        """Cargo define o acesso de todos que estão nele: só o administrador da conta muda (rodada 1, P-2). Sem
        isso, quem tem `users.manage` subia o desconto máximo do próprio cargo ou desligava o do Diretor."""
        super().check_permissions(request)
        if request.method not in SAFE_METHODS and not is_account_admin(request.user):
            raise PermissionDenied("Só o administrador da conta altera cargos.")

    def perform_destroy(self, instance):
        if instance.profiles.filter(deleted_at__isnull=True).exists():
            raise StateConflict("Há usuários neste cargo.")
        super().perform_destroy(instance)


class UserProfileViewSet(TenantViewSet):
    model = UserProfile
    serializer_class = users.UserProfileSerializer
    permission_code = "users"
    select_related = ("user", "role", "default_store")
    prefetch_related = ("stores", "extra_roles", "extra_permissions")
    filterset_fields = ["role", "stores", "all_stores", "is_active", "is_seller"]

    def get_queryset(self):
        return visible_profiles(super().get_queryset())
    search_fields = ["user__username", "user__first_name", "user__last_name", "seller_code"]

    action_permissions = {"sellers": None}

    @action(detail=False, methods=["get"])
    def sellers(self, request):
        """Lista curta de vendedores ativos para o seletor do PDV."""
        if request.store is None:
            raise StateConflict("Selecione a filial (X-Store-ID) para listar os vendedores dela.")
        rows = sellers_of(request.store)
        return Response([
            {"user_id": p.user_id, "name": p.user.get_full_name() or p.user.username, "code": p.seller_code}
            for p in rows
        ])

    def check_writable(self, instance):
        """Ações em massa (ativar/desativar) passam por aqui, não pelo serializer: a mesma regra de nível
        (S-24) e ninguém desliga o próprio acesso."""
        super().check_writable(instance)
        # Em massa só se liga/desliga acesso: o próprio não. (No PATCH comum o serializer confere campo a campo.)
        if getattr(self, "action", None) == "bulk" and instance.user_id == self.request.user.pk:
            raise PermissionDenied("Você não pode alterar o seu próprio acesso.")
        problem = users.target_problem(self.request.user, instance)
        if problem:
            raise PermissionDenied(problem)

    def perform_destroy(self, instance):
        if instance.user_id == self.request.user.pk:
            raise StateConflict("Você não pode excluir o próprio usuário.")
        problem = users.target_problem(self.request.user, instance)  # S-24
        if problem:
            raise PermissionDenied(problem)
        instance.user.is_active = False
        instance.user.save(update_fields=["is_active"])
        super().perform_destroy(instance)

