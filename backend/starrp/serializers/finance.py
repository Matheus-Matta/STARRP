from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer, tenant_serializer
from starrp.models import (
    FinancialAccount,
    FinancialCategory,
    FinancialTitle,
    FinancialTransaction,
    Installment,
    RecurringTitle,
)
from starrp.services import finance, recurring

Money = {"max_digits": 14, "decimal_places": 2}

FinancialAccountSerializer = tenant_serializer(FinancialAccount)
FinancialCategorySerializer = tenant_serializer(FinancialCategory)
class FinancialTransactionSerializer(TenantSerializer):
    account_name = serializers.CharField(source="financial_account.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    party_name = serializers.SerializerMethodField()
    is_reversal = serializers.SerializerMethodField()

    def get_party_name(self, obj) -> str:
        party = obj.customer or obj.supplier
        return party.name if party else ""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("customer") and attrs.get("supplier"):
            raise serializers.ValidationError("Escolha cliente OU fornecedor.")
        return attrs

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
    due_time = serializers.TimeField(source="title.due_time", read_only=True, default=None)
    late = serializers.SerializerMethodField()

    def get_party_name(self, obj):
        party = obj.title.customer or obj.title.supplier
        return party.name if party else ""

    def get_late(self, obj) -> dict:
        """Encargos de atraso de HOJE (multa + juros do título) e o saldo atualizado com eles."""
        charges = finance.late_charges(obj)
        return {"days_late": charges["days_late"], "fine": str(charges["fine"]), "interest": str(charges["interest"]),
                "updated_balance": str(obj.balance + charges["fine"] + charges["interest"])}

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
    installment_count = serializers.IntegerField(write_only=True, required=False, default=1, min_value=1,
                                                 max_value=420)  # 35 anos por mês
    first_due = serializers.DateField(write_only=True, required=False)
    # "single": paga tudo de uma vez (1 parcela); "installments": parcelado pela frequência.
    payment_mode = serializers.ChoiceField(choices=["single", "installments"], write_only=True, required=False)

    class Meta:
        model = FinancialTitle
        fields = "__all__"
        read_only_fields = ["status", "sale", "payment", "inbound_nfe", "recurring", "recurring_period"]
        extra_kwargs = {"issue_date": {"required": False}}

    def _open(self, obj):
        return [i for i in obj.installments.all() if i.deleted_at is None and i.status in ("open", "partial")]

    def get_open_amount(self, obj):
        return str(sum((i.balance for i in self._open(obj)), Decimal("0")))

    def get_next_due(self, obj):
        dates = sorted(i.due_date for i in self._open(obj))
        return dates[0] if dates else None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("due_day") is not None and not 1 <= attrs["due_day"] <= 31:
            raise serializers.ValidationError({"due_day": "Dia de 1 a 31."})
        if "total" in attrs and attrs["total"] <= 0:
            raise serializers.ValidationError({"total": "Informe um valor maior que zero."})
        self._check_frozen(attrs)
        return attrs

    def _check_frozen(self, attrs):
        """Título lançado não muda de valor nem de tipo (as parcelas não acompanham, R2-20); e o que veio de
        venda/NF-e/recorrência, ou já tem baixa, também não troca de cliente/fornecedor."""
        if self.instance is None:
            return
        frozen = ["kind", "total", "store"]
        t = self.instance
        if t.sale_id or t.payment_id or t.inbound_nfe_id or t.recurring_id or t.installments.filter(
                paid_amount__gt=0, deleted_at__isnull=True).exists():
            frozen += ["customer", "supplier"]
        for field in frozen:
            if field in attrs and attrs[field] != getattr(t, field):
                raise serializers.ValidationError({field: "Este campo não muda depois de lançado: cancele o título e "
                                                          "lance de novo."})

    @transaction.atomic
    def create(self, validated_data):
        count = validated_data.pop("installment_count", 1)
        first_due = validated_data.pop("first_due", None)
        if validated_data.pop("payment_mode", None) == "single":
            count = 1
        return finance.create_title(
            installments=count, first_due=first_due, user=validated_data.pop("created_by", None),
            **{k: v for k, v in validated_data.items() if k not in ("account", "updated_by")},
        )


class SettleSerializer(serializers.Serializer):
    financial_account = TenantPrimaryKeyField(FinancialAccount, required=False, allow_null=True)
    amount = serializers.DecimalField(min_value=ZERO, default=ZERO, **Money)
    use_credit = serializers.BooleanField(default=False)
    allow_excess = serializers.BooleanField(default=False)
    interest = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    fine = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    discount = serializers.DecimalField(min_value=ZERO, default=0, **Money)
    date = serializers.DateField(required=False)

    def validate_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("A baixa não pode ter data futura.")
        return value


class RecurringTitleSerializer(TenantSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    upcoming = serializers.SerializerMethodField()
    next_due = serializers.SerializerMethodField()
    party_name = serializers.SerializerMethodField()
    generated = serializers.SerializerMethodField()

    def get_next_due(self, obj):
        dates = recurring.upcoming(obj, 1) if obj.is_active else []
        return dates[0] if dates else None

    def get_party_name(self, obj) -> str:
        party = obj.customer or obj.supplier
        return party.name if party else ""

    class Meta:
        model = RecurringTitle
        fields = "__all__"
        read_only_fields = ["next_period"]

    def get_upcoming(self, obj) -> list:
        return [d.isoformat() for d in recurring.upcoming(obj)] if obj.is_active else []

    def get_generated(self, obj) -> int:
        if hasattr(obj, "generated_count"):  # anotado pela RecurringTitleViewSet
            return obj.generated_count
        return obj.titles.filter(deleted_at__isnull=True).count()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        merged = {**({f: getattr(self.instance, f) for f in ("customer", "supplier", "kind")} if self.instance else {}),
                  **attrs}
        if merged.get("customer") and merged.get("supplier"):
            raise serializers.ValidationError("Escolha cliente OU fornecedor.")
        day = attrs.get("due_day")
        if day is not None and not 1 <= day <= 31:
            raise serializers.ValidationError({"due_day": "Dia de 1 a 31."})
        if attrs.get("amount") is not None and attrs["amount"] <= 0:
            raise serializers.ValidationError({"amount": "Informe um valor maior que zero."})
        # Janela de geração limitada (R2-08): início em 1900 ou 30 mil dias de antecedência gerava milhares de títulos.
        start = attrs.get("start_date")
        if start is not None and start != getattr(self.instance, "start_date", None) and (
                start < timezone.localdate() - timedelta(days=366)):
            raise serializers.ValidationError({"start_date": "O início pode ser no máximo um ano atrás."})
        if attrs.get("lead_days") is not None and attrs["lead_days"] > 365:
            raise serializers.ValidationError({"lead_days": "No máximo 365 dias antes do vencimento."})
        if self.instance and any(k in attrs for k in ("start_date", "frequency", "due_day", "due_weekday"))                 and not self.instance.titles.exists():
            attrs["next_period"] = None  # ainda não gerou nada: recomeça pelo novo início
        return attrs
