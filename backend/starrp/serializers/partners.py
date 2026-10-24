from django.db import transaction
from rest_framework import serializers

from starrp.core.text import only_digits
from starrp.core.serializers import TenantSerializer, tenant_serializer
from starrp.models import Customer, CustomerAddress, CustomerGroup, Supplier, Tag
from starrp.serializers.tags import TaggedSerializerMixin

CustomerGroupSerializer = tenant_serializer(CustomerGroup)


class CustomerAddressSerializer(TenantSerializer):
    """Endereço de entrega. Aninhado no cliente: `id` presente = este já existe."""

    id = serializers.UUIDField(required=False)

    class Meta:
        model = CustomerAddress
        exclude = ["account", "deleted_at", "created_by", "updated_by"]
        extra_kwargs = {"customer": {"required": False}, "label": {"required": False, "allow_blank": True}}

    def get_fields(self):
        fields = super().get_fields()
        fields["id"] = serializers.UUIDField(required=False)  # a base deixa `id` só-leitura
        return fields

    def validate_zip_code(self, value):
        digits = only_digits(value)
        if digits and len(digits) != 8:
            raise serializers.ValidationError("CEP tem 8 dígitos.")
        return digits

    def validate_state(self, value):
        return (value or "").strip().upper()


class DocumentMixin:
    def validate_document(self, value):
        digits = only_digits(value)
        if digits and len(digits) not in (11, 14):
            raise serializers.ValidationError("CPF tem 11 dígitos e CNPJ tem 14.")
        return digits


class CustomerSerializer(TaggedSerializerMixin, DocumentMixin, TenantSerializer):
    """Cliente com os endereços de entrega (lista completa: o que sai da lista é apagado;
    um só fica como padrão) e os metacampos validados pelas definições."""

    tag_scope = Tag.Scope.CUSTOMER
    addresses = CustomerAddressSerializer(many=True, required=False)
    credit_balance = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = "__all__"

    def validate_metafields(self, value):
        from starrp.services import metafields

        return metafields.clean(self.context["request"].account.pk, "customer", value)

    @transaction.atomic
    def create(self, validated_data):
        rows = validated_data.pop("addresses", None)
        customer = super().create(validated_data)
        if rows is not None:
            self._sync_addresses(customer, rows)
        return customer

    @transaction.atomic
    def update(self, instance, validated_data):
        rows = validated_data.pop("addresses", None)
        customer = super().update(instance, validated_data)
        if rows is not None:
            self._sync_addresses(customer, rows)
        return customer

    def _sync_addresses(self, customer, rows):
        user = self.context["request"].user
        current = {a.pk: a for a in customer.addresses.filter(deleted_at__isnull=True)}
        kept = []
        wants_default = next((i for i, r in enumerate(rows) if r.get("is_default")), 0 if rows else None)
        for index, row in enumerate(rows):
            row = {k: v for k, v in row.items() if k not in ("customer",)}
            address = current.pop(row.pop("id", None), None) or CustomerAddress(
                account_id=customer.account_id, customer=customer, created_by=user)
            for field, value in row.items():
                setattr(address, field, value)
            address.is_default = index == wants_default
            address.label = (address.label or "").strip() or ("Principal" if index == 0 else f"Endereço {index + 1}")
            address.updated_by = user
            address.save()
            kept.append(address)
        for leftover in current.values():
            leftover.delete()
        return kept

    def get_credit_balance(self, obj):
        from starrp.services.checkout import credit_balance

        return str(credit_balance(obj))


class SupplierSerializer(DocumentMixin, TenantSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"
