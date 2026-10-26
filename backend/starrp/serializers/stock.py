from django.db import transaction
from rest_framework import serializers

from starrp.core.errors import StateConflict
from starrp.core.serializers import TenantSerializer, tenant_serializer
from starrp.models import (
    LabelTemplate, ReceivingDivergence, StockBalance, StockDocument, StockDocumentItem, StockLot, StockMovement,
    StockSettings, Warehouse,
)
from starrp.services import numbering

StockSettingsSerializer = tenant_serializer(StockSettings)
WarehouseSerializer = tenant_serializer(Warehouse)
LabelTemplateSerializer = tenant_serializer(LabelTemplate)


def volumes_of(variant):
    """Caixas em que UMA unidade vem (guarda-roupa em 3 volumes): número e o que vai em cada."""
    if variant is None:
        return []
    return [{"number": v.number, "description": v.description}
            for v in variant.volumes.all() if v.deleted_at is None]


class StockLotSerializer(TenantSerializer):
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockLot
        fields = "__all__"
        read_only_fields = ["quantity", "initial_quantity", "code", "variant", "warehouse", "unit_cost"]


class StockBalanceSerializer(TenantSerializer):
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockBalance
        fields = ["id", "variant", "variant_name", "sku", "warehouse", "warehouse_name", "quantity", "updated_at"]


class StockMovementSerializer(TenantSerializer):
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    operator_name = serializers.CharField(source="operator.get_full_name", read_only=True, default="")
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = StockMovement
        fields = "__all__"


class StockDocumentItemSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    volumes = serializers.SerializerMethodField()

    class Meta:
        model = StockDocumentItem
        exclude = ["account", "document", "deleted_at", "created_by", "updated_by"]

    def get_volumes(self, obj):
        return volumes_of(obj.variant)


class StockDocumentSerializer(TenantSerializer):
    """Documento com itens aninhados. Itens só mudam enquanto rascunho."""

    items = StockDocumentItemSerializer(many=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    checked_by_name = serializers.CharField(source="checked_by.get_full_name", read_only=True, default=None)
    inbound_nfe_number = serializers.CharField(source="inbound_nfe.number", read_only=True, default=None)
    item_count = serializers.SerializerMethodField()
    # Logística permite conferir item a item (sem ler os códigos)?
    manual_conference = serializers.SerializerMethodField()

    class Meta:
        model = StockDocument
        fields = "__all__"
        read_only_fields = ["number", "status", "posted_at", "posted_by", "cancelled_at", "cancelled_by",
                            "checked_at", "checked_by", "inbound_nfe", "conference_mode"]
        signed_fields = ()

    def get_item_count(self, obj):
        return len(obj.items.all())

    def get_manual_conference(self, obj):
        from starrp.services import logistics_settings

        return logistics_settings.for_store(obj.store_id).allow_manual_conference

    def validate(self, attrs):
        attrs = super().validate(attrs)
        kind = attrs.get("kind") or getattr(self.instance, "kind", None)
        for row in attrs.get("items", []):
            if kind != StockDocument.Kind.ADJUSTMENT and row.get("quantity", 0) < 0:
                raise serializers.ValidationError({"items": "Quantidade negativa só em ajuste."})
        return attrs

    def to_internal_value(self, data):
        # Ajuste aceita quantidade negativa (é a diferença com sinal).
        if data.get("kind") == StockDocument.Kind.ADJUSTMENT:
            self.fields["items"].child.fields["quantity"].min_value = None
            validators = self.fields["items"].child.fields["quantity"].validators
            self.fields["items"].child.fields["quantity"].validators = [
                v for v in validators if v.__class__.__name__ != "MinValueValidator"
            ]
        return super().to_internal_value(data)

    def _save_items(self, document, items):
        document.items.all().delete()
        for row in items:
            row.pop("id", None)
            StockDocumentItem.all_objects.create(account_id=document.account_id, document=document, **row)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        validated_data["number"] = numbering.next_number(validated_data["store"], "stock_document")
        document = super().create(validated_data)
        self._save_items(document, items)
        return document

    @transaction.atomic
    def update(self, instance, validated_data):
        if not instance.is_editable:
            raise StateConflict("Documento confirmado não pode ser alterado.")
        items = validated_data.pop("items", None)
        document = super().update(instance, validated_data)
        if items is not None:
            self._save_items(document, items)
        return document


class ReceivingDivergenceSerializer(TenantSerializer):
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    document_number = serializers.IntegerField(source="document.number", read_only=True)
    nfe_number = serializers.CharField(source="inbound_nfe.number", read_only=True, default=None)
    checked_by_name = serializers.CharField(source="checked_by.get_full_name", read_only=True, default=None)
    difference = serializers.SerializerMethodField()

    class Meta:
        model = ReceivingDivergence
        fields = "__all__"

    def get_difference(self, obj):
        return str(obj.arrived_quantity - obj.expected_quantity)
