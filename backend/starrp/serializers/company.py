from rest_framework import serializers

from starrp.core.serializers import TenantSerializer, tenant_serializer
from starrp.models import Store, Terminal

TerminalSerializer = tenant_serializer(Terminal, read_only=("last_seen_at", "revoked_at"))


class StoreSerializer(TenantSerializer):
    # Senha de ações do caixa: só entra; nunca sai, nem como hash.
    cash_action_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_cash_action_password = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = "__all__"

    def get_has_cash_action_password(self, obj):
        return bool(obj.cash_action_password)

    def _apply_password(self, instance, raw):
        if raw is not None:
            instance.set_cash_action_password(raw)
            instance.save(update_fields=["cash_action_password", "updated_at"])

    def create(self, validated_data):
        raw = validated_data.pop("cash_action_password", None)
        store = super().create(validated_data)
        self._apply_password(store, raw)
        return store

    def update(self, instance, validated_data):
        raw = validated_data.pop("cash_action_password", None)
        store = super().update(instance, validated_data)
        self._apply_password(store, raw)
        return store
