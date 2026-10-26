"""Tabelas de frete (com as faixas de CEP aninhadas) e definições de metacampos."""
import re

from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer
from starrp.core.text import only_digits
from starrp.models import Category, FreightTable, FreightZipRange, LogisticsSettings, MetafieldDefinition


def _zip(value):
    digits = only_digits(value or "")
    if len(digits) != 8:
        raise serializers.ValidationError("CEP tem 8 dígitos.")
    return digits


class FreightZipRangeSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    # Aceita "01000-000": o tamanho é conferido depois de tirar a máscara.
    zip_start = serializers.CharField(max_length=9)
    zip_end = serializers.CharField(max_length=9)

    class Meta:
        model = FreightZipRange
        fields = ["id", "zip_start", "zip_end", "value", "lead_days", "label"]

    def validate_zip_start(self, value):
        return _zip(value)

    def validate_zip_end(self, value):
        return _zip(value)

    def validate(self, attrs):
        if attrs["zip_start"] > attrs["zip_end"]:
            raise serializers.ValidationError({"zip_end": "O CEP final tem que ser maior que o inicial."})
        return attrs


class FreightTableSerializer(TenantSerializer):
    """Tabela de frete. `ranges` é a lista completa das faixas (faixa de CEP)."""

    ranges = FreightZipRangeSerializer(many=True, required=False)
    origin_zip = serializers.CharField(max_length=9, required=False, allow_blank=True)
    range_count = serializers.SerializerMethodField()

    class Meta:
        model = FreightTable
        fields = "__all__"

    def get_range_count(self, obj):
        return sum(1 for r in obj.ranges.all() if r.deleted_at is None)

    def validate_origin_zip(self, value):
        return _zip(value) if value else ""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        kind = attrs.get("kind", getattr(self.instance, "kind", FreightTable.Kind.ZIP_RANGE))
        if kind == FreightTable.Kind.DISTANCE:
            errors = {}
            if not attrs.get("origin_zip", getattr(self.instance, "origin_zip", "")):
                errors["origin_zip"] = "Informe o CEP de onde a entrega sai."
            if attrs.get("price_per_km", getattr(self.instance, "price_per_km", None)) is None:
                errors["price_per_km"] = "Informe quanto custa cada km."
            if errors:
                raise serializers.ValidationError(errors)
        else:
            ranges = attrs.get("ranges")
            if ranges == [] or (ranges is None and self.instance is None):
                raise serializers.ValidationError({"ranges": "Adicione ao menos uma faixa de CEP."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        rows = validated_data.pop("ranges", None)
        table = super().create(validated_data)
        self._sync(table, rows or [])
        return table

    @transaction.atomic
    def update(self, instance, validated_data):
        rows = validated_data.pop("ranges", None)
        table = super().update(instance, validated_data)
        if rows is not None:
            self._sync(table, rows)
        return table

    def _sync(self, table, rows):
        user = self.context["request"].user
        current = {r.pk: r for r in table.ranges.filter(deleted_at__isnull=True)}
        for row in rows:
            item = current.pop(row.pop("id", None), None) or FreightZipRange(
                account_id=table.account_id, table=table, created_by=user)
            for field, value in row.items():
                setattr(item, field, value)
            item.save()
        for leftover in current.values():
            leftover.delete()


class MetafieldDefinitionSerializer(TenantSerializer):
    categories = TenantPrimaryKeyField(Category, many=True, required=False)
    options = serializers.ListField(child=serializers.CharField(max_length=60), required=False)

    class Meta:
        model = MetafieldDefinition
        fields = "__all__"
        extra_kwargs = {"key": {"required": False}}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        name = attrs.get("name", getattr(self.instance, "name", ""))
        key = attrs.get("key") or getattr(self.instance, "key", "") or slugify(name).replace("-", "_")
        attrs["key"] = re.sub(r"[^a-z0-9_-]", "_", key.lower())[:60]
        kind = attrs.get("type", getattr(self.instance, "type", "text"))
        if kind == MetafieldDefinition.Type.SELECT and not attrs.get("options", getattr(self.instance, "options", [])):
            raise serializers.ValidationError({"options": "Lista de opções precisa de ao menos uma opção."})
        owner = attrs.get("owner", getattr(self.instance, "owner", "product"))
        if owner != MetafieldDefinition.Owner.PRODUCT:
            attrs["categories"] = []
        return attrs


class LogisticsSettingsSerializer(TenantSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = LogisticsSettings
        fields = "__all__"
        read_only_fields = ["store"]
