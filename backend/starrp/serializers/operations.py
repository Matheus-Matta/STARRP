"""Serializers de devolução, pagamento e caixa."""
from decimal import Decimal
from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer, tenant_serializer
from starrp.serializers.sales import ApprovalField
from starrp.models import (
    CashDiscrepancy, CashMovement, CashRegister, CashSession, CustomerCredit, PaymentMethod, SaleItem, SaleReturn,
    SaleReturnItem, Terminal,
)

Money = {"max_digits": 14, "decimal_places": 2}

PaymentMethodSerializer = tenant_serializer(PaymentMethod)
class CashRegisterSerializer(TenantSerializer):
    """Caixa e QUEM opera (`operators`, ids de usuário): só eles abrem, movimentam e fecham."""

    operator_names = serializers.SerializerMethodField()
    in_use_by = serializers.SerializerMethodField(help_text="Quem está com o turno deste caixa agora (vazio = livre).")

    class Meta:
        model = CashRegister
        fields = "__all__"

    def get_in_use_by(self, obj):
        busy = (obj.sessions.filter(deleted_at__isnull=True).exclude(status__in=["closed", "cancelled"])
                .select_related("opened_by").first())
        return (busy.opened_by.get_full_name() or busy.opened_by.username) if busy else None

    def get_operator_names(self, obj):
        return ", ".join(u.get_full_name() or u.username for u in obj.operators.all())

    def validate_operators(self, users):
        from starrp.models import UserProfile

        account = self.context["request"].account
        ok = set(UserProfile.all_objects.filter(account=account, user__in=users, deleted_at__isnull=True)
                 .values_list("user_id", flat=True))
        strangers = [u.username for u in users if u.pk not in ok]
        if strangers:
            raise serializers.ValidationError(f"Usuário fora da conta: {', '.join(strangers)}.")
        return users
CustomerCreditSerializer = tenant_serializer(CustomerCredit)
CashDiscrepancySerializer = tenant_serializer(
    CashDiscrepancy, read_only=("status", "resolved_by", "resolved_at")
)

ZERO, HUNDRED = Decimal("0"), Decimal("100")


class SaleReturnItemSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source="sale_item.description", read_only=True)

    class Meta:
        model = SaleReturnItem
        fields = ["id", "sale_item", "description", "quantity", "unit_price", "total", "restock"]


class SaleReturnSerializer(TenantSerializer):
    items = SaleReturnItemSerializer(many=True, read_only=True)
    sale_number = serializers.IntegerField(source="sale.number", read_only=True)

    class Meta:
        model = SaleReturn
        fields = "__all__"
        read_only_fields = [f.name for f in SaleReturn._meta.fields]


class ReturnItemInput(serializers.Serializer):
    sale_item = TenantPrimaryKeyField(SaleItem)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=ZERO)
    restock = serializers.BooleanField(default=True)


class ReturnCreateSerializer(serializers.Serializer):
    items = ReturnItemInput(many=True)
    refund_method = serializers.ChoiceField(choices=SaleReturn.Refund.choices, default=SaleReturn.Refund.STORE_CREDIT)
    reason = serializers.CharField()
    approval = serializers.DictField(child=serializers.CharField(), required=False)


class CashMovementSerializer(TenantSerializer):
    operator_name = serializers.CharField(source="operator.get_full_name", read_only=True)
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CashMovement
        fields = "__all__"
        read_only_fields = [f.name for f in CashMovement._meta.fields]

    def get_approved_by_name(self, obj) -> str:
        if obj.authorized_by_password:
            return "Senha do caixa"
        return (obj.approved_by.get_full_name() or obj.approved_by.username) if obj.approved_by else ""


class CashSessionSerializer(TenantSerializer):
    register_name = serializers.CharField(source="register.name", read_only=True)
    opened_by_name = serializers.CharField(source="opened_by.get_full_name", read_only=True)
    expected_now = serializers.SerializerMethodField()

    class Meta:
        model = CashSession
        fields = "__all__"
        read_only_fields = [f.name for f in CashSession._meta.fields]

    def get_expected_now(self, obj):
        from starrp.services.cash import expected_cash

        return str(expected_cash(obj)) if obj.status == CashSession.Status.OPEN else str(obj.expected_amount)

    def to_representation(self, instance):
        """Fechamento cego: sem `cash.approve`, o esperado e a diferença não saem (`null`)."""
        from starrp.services.cash import sees_drawer

        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is None or not sees_drawer(request.user):
            data.update(expected_now=None, expected_amount=None, difference=None, closing_report=None,
                        opening_expected=None, opening_difference=None, blind=True)
        return data


class OpenSessionSerializer(serializers.Serializer):
    register = TenantPrimaryKeyField(CashRegister)
    opening_amount = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    terminal = TenantPrimaryKeyField(Terminal, required=False, allow_null=True)


class CloseSessionSerializer(serializers.Serializer):
    counted_amount = serializers.DecimalField(min_value=ZERO, **Money)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ManualMovementSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY])
    amount = serializers.DecimalField(min_value=ZERO, **Money)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    destination = serializers.CharField(required=False, allow_blank=True, default="")
    approval = ApprovalField()


class DecisionSerializer(serializers.Serializer):
    """Aprovar/recusar: justificativa e, sem permissão, a autorização (gerente ou senha do caixa)."""
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    approval = ApprovalField()
