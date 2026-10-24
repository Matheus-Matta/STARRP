from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer, tenant_serializer
from starrp.models import FinancialAccount, FinancialCategory, FinancialTitle, FinancialTransaction, Installment
from starrp.services import finance

Money = {"max_digits": 14, "decimal_places": 2}

FinancialAccountSerializer = tenant_serializer(FinancialAccount)
FinancialCategorySerializer = tenant_serializer(FinancialCategory)
class FinancialTransactionSerializer(TenantSerializer):
    account_name = serializers.CharField(source="financial_account.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    is_reversal = serializers.SerializerMethodField()

    class Meta:
        model = FinancialTransaction
        fields = "__all__"
        # Origem automática e vínculos só o sistema grava; o usuário lança avulso.
        read_only_fields = ["installment", "cash_session", "sale", "payment", "reversal_of", "source_key",
                            "transfer_pair", "operator"]

    def get_is_reversal(self, obj) -> bool:
        return obj.reversal_of_id is not None

ZERO, HUNDRED = Decimal("0"), Decimal("100")


class InstallmentSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(read_only=True, **Money)
    title_description = serializers.CharField(source="title.description", read_only=True)
    kind = serializers.CharField(source="title.kind", read_only=True)
    party_name = serializers.SerializerMethodField()

    def get_party_name(self, obj):
        party = obj.title.customer or obj.title.supplier
        return party.name if party else ""

    class Meta:
        model = Installment
        exclude = ["account", "deleted_at", "created_by", "updated_by"]
        read_only_fields = ["title", "paid_amount", "paid_at", "status"]


class FinancialTitleSerializer(TenantSerializer):
    """Título lançado à mão: informa total e nº de parcelas (mensais)."""

    installments = InstallmentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    open_amount = serializers.SerializerMethodField()
    next_due = serializers.SerializerMethodField()
    installment_count = serializers.IntegerField(write_only=True, required=False, default=1, min_value=1)
    first_due = serializers.DateField(write_only=True, required=False)

    class Meta:
        model = FinancialTitle
        fields = "__all__"
        read_only_fields = ["status", "issue_date", "sale", "payment", "inbound_nfe"]

    def _open(self, obj):
        return [i for i in obj.installments.all() if i.deleted_at is None and i.status in ("open", "partial")]

    def get_open_amount(self, obj):
        return str(sum((i.amount - i.paid_amount for i in self._open(obj)), Decimal("0")))

    def get_next_due(self, obj):
        dates = sorted(i.due_date for i in self._open(obj))
        return dates[0] if dates else None

    @transaction.atomic
    def create(self, validated_data):
        count = validated_data.pop("installment_count", 1)
        first_due = validated_data.pop("first_due", None)
        return finance.create_title(
            installments=count, first_due=first_due, user=validated_data.pop("created_by", None),
            **{k: v for k, v in validated_data.items() if k not in ("account", "updated_by")},
        )


class SettleSerializer(serializers.Serializer):
    financial_account = TenantPrimaryKeyField(FinancialAccount)
    amount = serializers.DecimalField(min_value=ZERO, **Money)
    interest = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    fine = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    discount = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    date = serializers.DateField(required=False)
