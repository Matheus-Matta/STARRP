"""Regras compartilhadas entre filiais (models/rules.py)."""
from rest_framework import serializers

from starrp.core.serializers import TenantSerializer
from starrp.models import LabelTemplate, LogisticsRule, StockRule, StoreRule


class SharedRuleSerializer(TenantSerializer):
    # Quem usa a regra (a filial escolhe a regra no cadastro dela).
    store_names = serializers.SerializerMethodField()
    store_count = serializers.SerializerMethodField()

    class Meta:
        fields = "__all__"

    def get_store_names(self, obj):
        return list(obj.stores_using().order_by("name").values_list("name", flat=True))

    def get_store_count(self, obj):
        return obj.stores_using().count()

    def validate_is_default(self, value):
        if self.instance is not None and self.instance.is_default and not value:
            raise serializers.ValidationError(
                f"Sempre existe uma {self.Meta.model.KIND_LABEL} padrão: marque outra como padrão em vez de desmarcar esta.")
        return value


class StoreRuleSerializer(SharedRuleSerializer):
    class Meta(SharedRuleSerializer.Meta):
        model = StoreRule


class LogisticsRuleSerializer(SharedRuleSerializer):
    entry_lot_label_name = serializers.CharField(source="entry_lot_label.name", read_only=True, default=None)
    entry_product_label_name = serializers.CharField(source="entry_product_label.name", read_only=True, default=None)
    conference_label_name = serializers.CharField(source="conference_label.name", read_only=True, default=None)

    class Meta(SharedRuleSerializer.Meta):
        model = LogisticsRule

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for field, subjects in LogisticsRule.LABEL_SUBJECTS.items():
            template = attrs.get(field)
            if template is not None and template.subject not in subjects:
                kinds = " ou ".join(LabelTemplate.Subject(s).label.lower() for s in subjects)
                raise serializers.ValidationError({field: f"Escolha um modelo de etiqueta de {kinds}."})
        return attrs


class StockRuleSerializer(SharedRuleSerializer):
    class Meta(SharedRuleSerializer.Meta):
        model = StockRule
