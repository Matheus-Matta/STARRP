from decimal import Decimal

from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer, tenant_serializer
from starrp.models import BinBalance, InboundNFeItem, LabelTemplate, ProductVariant, StockAdvice, StorageBin, Warehouse

StorageBinSerializer = tenant_serializer(StorageBin)


class BinBalanceSerializer(TenantSerializer):
    bin_code = serializers.CharField(source="bin.code", read_only=True)
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True, default=None)
    expires_at = serializers.DateField(source="lot.expires_at", read_only=True, default=None)

    class Meta:
        model = BinBalance
        fields = ["id", "bin", "bin_code", "variant", "variant_name", "sku", "lot", "lot_number", "expires_at",
                  "quantity", "updated_at"]


class GenerateBinsSerializer(serializers.Serializer):
    """Gera a grade de endereços de uma vez: ruas × prateleiras × níveis.

    Ex.: aisles=["A","B"], racks=3, levels=2 → A-01-1 … B-03-2 (12 endereços),
    com a sequência seguindo rua → prateleira → nível (o caminho da coleta).
    """

    warehouse = TenantPrimaryKeyField(Warehouse)
    aisles = serializers.ListField(child=serializers.CharField(max_length=10), min_length=1)
    racks = serializers.IntegerField(min_value=1, max_value=200)
    levels = serializers.IntegerField(min_value=1, max_value=20)
    kind = serializers.ChoiceField(choices=StorageBin.Kind.choices, default=StorageBin.Kind.STORAGE)


class LabelItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    copies = serializers.IntegerField(min_value=1, max_value=500, default=1)


class LabelPrintSerializer(serializers.Serializer):
    # Sem modelo: o PADRÃO do tipo `subject` (os pré-prontos do sistema já vêm marcados).
    template = TenantPrimaryKeyField(LabelTemplate, required=False)
    subject = serializers.ChoiceField(choices=LabelTemplate.Subject.choices, required=False)
    items = LabelItemSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        if not attrs.get("template") and not attrs.get("subject"):
            raise serializers.ValidationError("Escolha o modelo de etiqueta (ou o tipo, para usar o padrão).")
        return attrs


class NFeImportSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    xml = serializers.CharField(required=False, trim_whitespace=False)

    def validate(self, attrs):
        if not attrs.get("file") and not attrs.get("xml"):
            raise serializers.ValidationError("Envie o arquivo XML (`file`) ou o conteúdo (`xml`).")
        return attrs


class NFeMapItemSerializer(serializers.Serializer):
    item = TenantPrimaryKeyField(InboundNFeItem)
    variant = TenantPrimaryKeyField(ProductVariant)
    conversion_factor = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"),
                                                 default=Decimal("1"))


class NFeReceiveSerializer(serializers.Serializer):
    warehouse = TenantPrimaryKeyField(Warehouse, required=False, allow_null=True,
                                      help_text="Sem depósito: o padrão da filial.")
    bin = TenantPrimaryKeyField(StorageBin, required=False, allow_null=True)
    post = serializers.BooleanField(default=False, help_text="Confere com as quantidades da nota e aprova já.")


class StockAdviceSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    document_number = serializers.IntegerField(source="document.number", read_only=True, default=None)
    decided_by_name = serializers.CharField(source="decided_by.username", read_only=True, default=None)

    class Meta:
        model = StockAdvice
        fields = ("id", "store", "warehouse", "warehouse_name", "kind", "status", "title", "detail", "impact", "moves", "checked_at",
                  "document", "document_number", "decided_by_name", "decided_at", "updated_at")
        read_only_fields = fields
