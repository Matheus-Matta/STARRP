"""Tags como lista de nomes na API: `"tags": ["Lançamento", "Verão"]`.

Quem usa herda `TaggedSerializerMixin` e diz o assunto (`tag_scope`); o nome
novo vira tag da conta no salvar (`services.tags.set_tags`).
"""
from django.db import transaction
from rest_framework import serializers

from starrp.core.serializers import tenant_serializer
from starrp.models import Tag
from starrp.services.tags import set_tags

TagSerializer = tenant_serializer(Tag, read_only=("normalized",))


class TagNamesField(serializers.ListField):
    child = serializers.CharField(max_length=40)

    def get_attribute(self, instance):
        return [t.name for t in instance.tags.all() if t.deleted_at is None]


class TaggedSerializerMixin(serializers.Serializer):
    tag_scope = ""
    tags = TagNamesField(required=False)

    @transaction.atomic
    def create(self, validated_data):
        names = validated_data.pop("tags", None)
        obj = super().create(validated_data)
        if names is not None:
            set_tags(obj, names, self.tag_scope, self.context["request"].user)
        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        names = validated_data.pop("tags", None)
        obj = super().update(instance, validated_data)
        if names is not None:
            set_tags(obj, names, self.tag_scope, self.context["request"].user)
        return obj
