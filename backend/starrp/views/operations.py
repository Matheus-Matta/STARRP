from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import StateConflict
from starrp.core.viewsets import SystemDataViewSet, TenantViewSet
from starrp.models import (
    CashDiscrepancy, CashMovement, CashRegister, CashSession, CustomerCredit, PaymentMethod, SaleReturn,
)
from starrp.serializers import operations as s
from starrp.core.text import decimals_as_text
from starrp.services import cash, cash_report, returns


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
    prefetch_related = ("items__sale_item",)
    filterset_fields = ["status", "refund_method", "customer", "sale"]
    action_permissions = {"complete": "sales.return", "cancel": "sales.return"}

    def create(self, request, *args, **kwargs):
        raise StateConflict("Abra a devolução a partir da venda: POST /sales/{id}/returns/.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return Response(s.SaleReturnSerializer(returns.complete(self.get_object(), request.user)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sale_return = self.get_object()
        if sale_return.status != SaleReturn.Status.DRAFT:
            raise StateConflict("Só devolução em rascunho pode ser cancelada.")
        sale_return.status = SaleReturn.Status.CANCELLED
        sale_return.save(update_fields=["status", "updated_at"])
        return Response(s.SaleReturnSerializer(sale_return).data)


class CustomerCreditViewSet(TenantViewSet):
    model = CustomerCredit
    serializer_class = s.CustomerCreditSerializer
    permission_code = "partners"
    http_method_names = ["get", "post", "head", "options"]
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


class CashSessionViewSet(_ActionMixin, TenantViewSet):
    model = CashSession
    serializer_class = s.CashSessionSerializer
    permission_code = "cash"
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("register", "opened_by")
    filterset_fields = {"status": ["exact"], "register": ["exact"], "opened_by": ["exact"], "opened_at": ["gte", "lte"]}
    ordering_map = {"opened_by_name": "opened_by__first_name"}
    action_permissions = {"approve": "cash.approve"}

    def create(self, request, *args, **kwargs):
        data = self._body(s.OpenSessionSerializer)
        session = cash.open_session(data["register"], request.user, data["opening_amount"], data.get("terminal"))
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

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        session = cash.approve_closing(self.get_object(), request.user, request.data.get("reason", ""))
        return Response(s.CashSessionSerializer(session, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get", "post"])
    def movements(self, request, pk=None):
        session = self.get_object()
        if request.method == "POST":
            data = self._body(s.ManualMovementSerializer)
            cash.add_movement(session, request.user, data["kind"], data["amount"], data["reason"],
                              data["destination"])
        return Response(s.CashMovementSerializer(session.movements.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        """Extrato do turno: resumo + movimentos da gaveta + vendas + itens + ocorrências."""
        from starrp.services.cash_statement import statement

        data = statement(self.get_object())
        return Response(decimals_as_text(data if cash.sees_drawer(request.user) else cash.blind(data)))

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        """Fechamento do turno: vendas, formas de pagamento, gaveta, diferença e margem."""
        data = cash_report.summary(self.get_object())
        return Response(decimals_as_text(data if cash.sees_drawer(request.user) else cash.blind(data)))


class CashMovementViewSet(TenantViewSet):
    model = CashMovement
    serializer_class = s.CashMovementSerializer
    permission_code = "cash"
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["session", "kind", "status"]
    action_permissions = {"approve": "cash.approve"}

    def create(self, request, *args, **kwargs):
        raise StateConflict("Lance sangria/suprimento em /cash-sessions/{id}/movements/.")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(s.CashMovementSerializer(cash.approve_movement(self.get_object(), request.user)).data)


class CashDiscrepancyViewSet(TenantViewSet):
    model = CashDiscrepancy
    serializer_class = s.CashDiscrepancySerializer
    permission_code = "cash"
    filterset_fields = ["session", "status"]
    action_permissions = {"resolve": "cash.approve"}

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        item = self.get_object()
        status = request.data.get("status")
        if status not in {CashDiscrepancy.Status.REVIEWED, CashDiscrepancy.Status.REGULARIZED,
                          CashDiscrepancy.Status.CANCELLED}:
            raise StateConflict("Status de resolução inválido.")
        item.status, item.resolved_by, item.resolved_at = status, request.user, timezone.now()
        item.resolution_note = request.data.get("note", "")
        item.save()
        return Response(self.get_serializer(item).data)
