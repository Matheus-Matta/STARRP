from rest_framework import serializers

from starrp.core.serializers import TenantSerializer, tenant_serializer
from starrp.models import Store, Terminal

TerminalSerializer = tenant_serializer(Terminal, read_only=("last_seen_at", "revoked_at"))


class StoreSerializer(TenantSerializer):
    # Senha de ações do caixa: só entra; nunca sai, nem como hash.
    cash_action_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_cash_action_password = serializers.SerializerMethodField()
    parent_name = serializers.CharField(source="parent.name", read_only=True, default=None)
    children_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Store
        fields = "__all__"

    def validate_parent(self, parent):
        """Não responde a si mesma nem a uma unidade que está abaixo dela (fecharia um ciclo)."""
        node = parent
        while node is not None and self.instance is not None:
            if node.pk == self.instance.pk:
                raise serializers.ValidationError("A unidade não pode responder a ela mesma nem a uma subordinada.")
            node = node.parent
        return parent

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
