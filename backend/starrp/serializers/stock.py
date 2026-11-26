from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from starrp.core.costs import HideCostFieldsMixin
from starrp.core.errors import StateConflict
from starrp.core.serializers import TenantSerializer, tenant_serializer
from starrp.models import (
    LabelTemplate, ReceivingDivergence, StockBalance, StockDocument, StockDocumentItem, StockLot, StockMovement,
    Warehouse,
)
from starrp.services import numbering, wms


class WarehouseSerializer(TenantSerializer):
    class Meta:
        model = Warehouse
        fields = "__all__"

    @transaction.atomic
    def update(self, instance, validated_data):
        before = instance.uses_bins
        saved = super().update(instance, validated_data)
        if saved.uses_bins and not before:
            wms.start_bins(saved)
        return saved


LabelTemplateSerializer = tenant_serializer(LabelTemplate)


def volumes_of(variant):
    """Caixas em que UMA unidade vem (guarda-roupa em 3 volumes): número e o que vai em cada."""
    if variant is None:
        return []
    return [{"number": v.number, "description": v.description}
            for v in variant.volumes.all() if v.deleted_at is None]


class StockLotSerializer(HideCostFieldsMixin, TenantSerializer):
    cost_fields = ("unit_cost",)
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockLot
        fields = "__all__"
        # Data de entrada não se edita: é ela que decide o que sai primeiro (FIFO).
        read_only_fields = ["quantity", "initial_quantity", "code", "variant", "warehouse", "unit_cost", "received_at"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        made = attrs.get("manufactured_at", getattr(self.instance, "manufactured_at", None))
        expires = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if made and expires and made > expires:
            raise serializers.ValidationError({"expires_at": "A validade é antes da fabricação. Confira as datas."})
        return attrs


class StockBalanceSerializer(TenantSerializer):
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockBalance
        fields = ["id", "variant", "variant_name", "sku", "warehouse", "warehouse_name", "quantity", "updated_at"]


class StockMovementSerializer(HideCostFieldsMixin, TenantSerializer):
    cost_fields = ("unit_cost", "total_cost")
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    operator_name = serializers.CharField(source="operator.get_full_name", read_only=True, default="")
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = StockMovement
        fields = "__all__"


class StockDocumentItemSerializer(HideCostFieldsMixin, TenantSerializer):
    """`TenantSerializer` (R2-03): produto, lote, endereço e item da nota precisam ser da MESMA conta e filial
    (o `ModelSerializer` puro aceitava o id de outra conta e mexia no custo médio dela), e nada negativo."""

    cost_fields = ("unit_cost", "total_cost")  # sem `catalog.view_costs` não vê nem grava o custo (M-10)

    id = serializers.UUIDField(required=False)
    variant_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    volumes = serializers.SerializerMethodField()

    class Meta:
        model = StockDocumentItem
        exclude = ["account", "document", "deleted_at", "created_by", "updated_by"]
        # O vínculo com a nota quem faz é o recebimento (`nfe_receiving`), nunca a tela.
        read_only_fields = ["nfe_item", "arrived_quantity"]

    def get_fields(self):
        fields = super().get_fields()
        fields["id"].read_only = False  # a linha se identifica pelo id no documento de NF-e (`_save_nfe_items`)
        return fields

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
        from starrp.services import rules

        # Uma busca da regra por filial na lista inteira (o contexto é o mesmo para todas as linhas).
        memo = self.context.setdefault("_manual_conference", {}) if isinstance(self.context, dict) else {}
        key = (obj.store_id, obj.account_id)
        if key not in memo:
            memo[key] = rules.of_store("logistics_rule", obj.store_id, obj.account_id).allow_manual_conference
        return memo[key]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        kind = attrs.get("kind") or getattr(self.instance, "kind", None)
        today = timezone.localdate()
        for index, row in enumerate(attrs.get("items", [])):
            if kind != StockDocument.Kind.ADJUSTMENT and row.get("quantity", 0) < 0:
                raise serializers.ValidationError({"items": "Quantidade negativa só em ajuste."})
            if kind == StockDocument.Kind.ENTRY:
                # As mesmas checagens da confirmação, já no rascunho: o erro aparece na linha certa.
                expires, made = row.get("expires_at"), row.get("manufactured_at")
                name = getattr(row.get("variant"), "display_name", f"Item {index + 1}")
                if expires and expires < today:
                    raise serializers.ValidationError({"items": f"{name}: validade já passou. Vencido não entra no estoque."})
                if made and made > today:
                    raise serializers.ValidationError({"items": f"{name}: fabricação no futuro."})
                if made and expires and made > expires:
                    raise serializers.ValidationError({"items": f"{name}: fabricação depois da validade."})
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

    #: O que a tela ajusta numa linha vinda da NF-e; o esperado e o vínculo com a nota são do recebimento (R2-07).
    NFE_EDITABLE = ("quantity", "unit_cost", "lot_number", "expires_at", "manufactured_at", "bin", "destination_bin",
                    "notes", "divergence_reason", "divergence_notes")

    def _save_nfe_items(self, document, items):
        """Documento de NF-e: PATCH com `quantity` menor e `expected_quantity` vazio entrava com menos mercadoria
        sem registrar divergência (e a duplicata saía cheia). As linhas são as da nota: não entram, não saem, não
        trocam de produto, e o esperado fica. Mudou quantidade: a conferência feita antes não vale mais."""
        current = {item.pk: item for item in document.items.filter(deleted_at__isnull=True)}
        sent = {row.get("id"): row for row in items}
        if len(items) != len(current) or set(sent) != set(current) or any(
                sent[pk].get("variant", item.variant) != item.variant for pk, item in current.items()):
            raise StateConflict("As linhas vêm da NF-e: não dá para incluir, tirar nem trocar o produto.",
                                code="nfe_items_locked")
        recheck = False
        for pk, item in current.items():
            row = sent[pk]
            changed = [f for f in self.NFE_EDITABLE if f in row and getattr(item, f, None) != row[f]]
            for field in changed:
                setattr(item, field, row[field])
            if changed:
                item.save(update_fields=[*changed, "updated_at"])
            recheck = recheck or "quantity" in changed
        if recheck and document.checked_at is not None:
            document.checked_at, document.checked_by = None, None
            document.save(update_fields=["checked_at", "checked_by", "updated_at"])

    def _save_items(self, document, items):
        if document.inbound_nfe_id:
            self._save_nfe_items(document, items)
            return
        # Quem não vê custo não o envia: fica o que já estava na linha, senão o custo atual do produto (zerado, a
        # entrada perderia o custo que outra pessoa lançou).
        hides = self.fields["items"].child._hides_costs()
        known = dict(document.items.values_list("variant_id", "unit_cost")) if hides else {}
        document.items.all().delete()
        for row in items:
            row.pop("id", None)
            if hides:
                variant = row["variant"]
                row["unit_cost"] = known.get(variant.pk, variant.average_cost)
            StockDocumentItem.all_objects.create(account_id=document.account_id, document=document, **row)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        validated_data["number"] = numbering.next_number(validated_data["store"], "stock_document")
        document = super().create(validated_data)
        self._save_items(document, items)
        return document

    def check_locked(self, instance, validated_data):
        if not instance.is_editable:
            raise StateConflict("Documento confirmado não pode ser alterado.")
        if instance.inbound_nfe_id:  # R4-06: a entrada da nota virava saída e a nota constava como recebida
            for field in ("kind", "supplier", "destination"):
                if field in validated_data and validated_data[field] != getattr(instance, field):
                    raise StateConflict("Este documento é a entrada de uma NF-e: tipo e fornecedor são os da nota.",
                                        code="nfe_document_locked")

    @transaction.atomic
    def update(self, instance, validated_data):
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
