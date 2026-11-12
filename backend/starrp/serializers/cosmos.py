from rest_framework import serializers

from starrp.models import CosmosConversation, CosmosFinding


class CosmosConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CosmosConversation
        fields = ("id", "title", "last_message_at", "created_at", "store", "finding", "digest_day")
        read_only_fields = ("id", "last_message_at", "created_at", "store", "finding", "digest_day")


class CosmosFindingSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    store_name = serializers.CharField(source="store.name", default=None, read_only=True)

    class Meta:
        model = CosmosFinding
        fields = ("id", "rule", "severity", "title", "detail", "entity", "object_id", "endpoint", "status",
                  "actor", "actor_name", "store", "store_name", "created_at", "resolved_at")
        read_only_fields = fields

    def get_actor_name(self, obj):
        return (obj.actor.get_full_name() or obj.actor.username) if obj.actor_id else None
