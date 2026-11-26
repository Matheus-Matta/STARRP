from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from starrp.core.costs import redact_report, sees_costs
from starrp.core.errors import StateConflict
from starrp.core.permissions import has_permission_code
from starrp.core.viewsets import SystemDataViewSet, TenantViewSet
from starrp.models import (
    CashDiscrepancy, CashMovement, CashRegister, CashSession, CustomerCredit, PaymentMethod, SaleReturn,
)
from starrp.serializers import operations as s
from starrp.core.text import decimals_as_text
from starrp.services import cash, cash_report, returns
from starrp.services.store_access import scope_own_sales


class _ActionMixin:
    def _body(self, serializer_class):
        body = serializer_class(data=self.request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        return body.validated_data


class SaleReturnViewSet(_ActionMixin, TenantViewSet):
    """Devolução nasce em POST /sales/{id}/returns/; aqui se lê e conclui."""

    model = SaleReturn
    serializer_class = s.SaleReturnSerializer
    permission_code = "sales"
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("sale",)
    prefetch_related = ("items__sale_item",)
    filterset_fields = ["status", "refund_method", "customer", "sale"]
    action_permissions = {"complete": "sales.view", "cancel": "sales.view"}  # confere em `_mine`

    def _mine(self):
        """Quem tem a permissão, ou quem abriu a devolução (a senha do gerente já foi conferida ao abrir)."""
        sale_return = self.get_object()
        recent = timezone.now() - sale_return.created_at < timedelta(hours=24)  # a autorização não vale para sempre
        mine = sale_return.processed_by_id == self.request.user.pk and recent
        if not mine and not has_permission_code(self.request.user, "sales.return"):
            raise PermissionDenied("Só quem abriu a devolução, ou quem pode devolver, conclui ou cancela.")
        return sale_return

    def get_queryset(self):
        return scope_own_sales(super().get_queryset())  # vendedor: só as devoluções das vendas dele

    def create(self, request, *args, **kwargs):
        raise StateConflict("Abra a devolução a partir da venda: POST /sales/{id}/returns/.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return Response(s.SaleReturnSerializer(returns.complete(self._mine(), request.user)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(s.SaleReturnSerializer(returns.cancel(self._mine(), request.user)).data)


class CustomerCreditViewSet(TenantViewSet):
    """Extrato imutável: créditos nascem da devolução e débitos do checkout."""

    model = CustomerCredit
    serializer_class = s.CustomerCreditSerializer
    permission_code = "partners"
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["customer", "kind"]


class PaymentMethodViewSet(SystemDataViewSet):
    model = PaymentMethod
    serializer_class = s.PaymentMethodSerializer
    permission_code = "settings"
    action_permissions = {"list": "sales.view", "retrieve": "sales.view"}
    filterset_fields = ["kind", "is_active", "store"]
    search_fields = ["name"]


class CashRegisterViewSet(TenantViewSet):
    model = CashRegister
    serializer_class = s.CashRegisterSerializer
    permission_code = "settings"
    action_permissions = {"list": "cash.view", "retrieve": "cash.view"}
    filterset_fields = ["is_active", "store"]
    search_fields = ["name", "code"]

    def perform_destroy(self, instance):
        if CashSession.all_objects.filter(register=instance, closed_at__isnull=True, deleted_at__isnull=True).exists():
            raise StateConflict("Este caixa tem turno aberto: feche o turno antes de excluir.")  # M-16
        super().perform_destroy(instance)


class CashSessionViewSet(_ActionMixin, TenantViewSet):
    model = CashSession
    serializer_class = s.CashSessionSerializer
    permission_code = "cash"
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("register", "opened_by")
    filterset_fields = {"status": ["exact"], "register": ["exact"], "opened_by": ["exact"], "opened_at": ["gte", "lte"]}
    ordering_map = {"opened_by_name": "opened_by__first_name"}
    # Aprovar abre para quem opera o caixa: sem `cash.approve`, o corpo traz `approval` (gerente ou senha da filial).
    action_permissions = {"approve": "cash.manage", "approve_opening": "cash.manage"}

    def get_queryset(self):
        # `pending_movements` do serializer na mesma query (antes: uma contagem por turno).
        return super().get_queryset().annotate(pending_count=Count(
            "movements", filter=Q(movements__status=CashMovement.Status.PENDING, movements__deleted_at__isnull=True)))

    def create(self, request, *args, **kwargs):
        data = self._body(s.OpenSessionSerializer)
        session = cash.open_session(data["register"], request.user, data["opening_amount"], data.get("terminal"),
                                    data["notes"])
        return Response(s.CashSessionSerializer(session, context=self.get_serializer_context()).data, status=201)

    @action(detail=False, methods=["get"])
    def current(self, request):
        """Turno aberto do usuário na loja ativa (o que o PDV mostra no topo)."""
        session = cash.session_for_user(request.store, request.user) if request.store else None
        return Response(s.CashSessionSerializer(session, context=self.get_serializer_context()).data if session else None)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        data = self._body(s.CloseSessionSerializer)
        session = cash.close_session(self.get_object(), request.user, data["counted_amount"], data["notes"])
        return Response(s.CashSessionSerializer(session, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="approve-opening")
    def approve_opening(self, request, pk=None):
        """Abertura com diferença: o gerente aprova (direto ou pelo `approval` no corpo)."""
        session = cash.approve_opening(self.get_object(), request.user, request.data.get("reason", ""),
                                       request.data.get("approval"))
        return Response(s.CashSessionSerializer(session, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Fechamento com diferença: o gerente aprova (direto ou pelo `approval` no corpo)."""
        data = self._body(s.DecisionSerializer)
        session = cash.approve_closing(self.get_object(), request.user, data["reason"], data.get("approval"))
        return Response(s.CashSessionSerializer(session, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get", "post"])
    def movements(self, request, pk=None):
        """GET: movimentos do turno. POST: sangria/suprimento (devolve o movimento criado, que pode
        vir `pending` aguardando aprovação)."""
        session = self.get_object()
        if request.method == "POST":
            data = self._body(s.ManualMovementSerializer)
            movement = cash.add_movement(session, request.user, data["kind"], data["amount"], data["reason"],
                                         data["destination"], data.get("approval"))
            return Response(s.CashMovementSerializer(movement).data, status=201)
        rows = session.movements.all()
        if not cash.sees_drawer(request.user):
            rows = rows.exclude(kind__in=cash.BLIND_KINDS)
        return Response(s.CashMovementSerializer(rows, many=True).data)

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        """Extrato do turno: resumo + movimentos da gaveta + vendas + itens + ocorrências."""
        from starrp.services.cash_statement import statement

        return Response(self._visible(request, statement(self.get_object())))

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        """Fechamento do turno: vendas, formas de pagamento, gaveta, diferença e margem."""
        return Response(self._visible(request, cash_report.summary(self.get_object())))

    @staticmethod
    def _visible(request, data):
        """Fechamento cego esconde a gaveta; sem `catalog.view_costs`, somem custo e margem das vendas."""
        if not cash.sees_drawer(request.user):
            data = cash.blind(data)
        if not sees_costs(request.user):
            data = redact_report(data)
        return decimals_as_text(data)


class CashMovementViewSet(_ActionMixin, TenantViewSet):
    model = CashMovement
    serializer_class = s.CashMovementSerializer
    permission_code = "cash"
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["session", "kind", "status"]
    select_related = ("operator", "approved_by")
    action_permissions = {"approve": "cash.manage", "reject": "cash.manage"}

    def get_queryset(self):
        qs = super().get_queryset()
        return qs if cash.sees_drawer(self.request.user) else qs.exclude(kind__in=cash.BLIND_KINDS)

    def create(self, request, *args, **kwargs):
        raise StateConflict("Lance sangria/suprimento em /cash-sessions/{id}/movements/.")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Sangria/suprimento pendente: gerente direto, ou `approval` (gerente/senha do caixa da filial)."""
        data = self._body(s.DecisionSerializer)
        movement = cash.approve_movement(self.get_object(), request.user, data["reason"], data.get("approval"))
        return Response(s.CashMovementSerializer(movement).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Gerente recusa, ou o operador desiste do que lançou: fica cancelado, fora da gaveta."""
        data = self._body(s.DecisionSerializer)
        return Response(s.CashMovementSerializer(cash.reject_movement(self.get_object(), request.user, data["reason"])).data)


class CashDiscrepancyViewSet(TenantViewSet):
    model = CashDiscrepancy
    serializer_class = s.CashDiscrepancySerializer
    permission_code = "cash"
    # A ocorrência nasce do fechamento e só se RESOLVE: o caixa não cria, edita nem apaga a própria (R2-27).
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        raise StateConflict("A ocorrência de caixa nasce do fechamento do turno.")

    filterset_fields = ["session", "status"]
    action_permissions = {"resolve": "cash.approve"}

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        item = self.get_object()
        status = str(request.data.get("status") or "")
        if status not in {CashDiscrepancy.Status.REVIEWED, CashDiscrepancy.Status.REGULARIZED,
                          CashDiscrepancy.Status.CANCELLED}:
            raise StateConflict("Status de resolução inválido.")
        item.status, item.resolved_by, item.resolved_at = status, request.user, timezone.now()
        item.resolution_note = str(request.data.get("note") or "")
        item.save()
        return Response(self.get_serializer(item).data)
