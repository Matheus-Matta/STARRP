from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from starrp.models import SeoCheck

SUGGESTIONS = (("name", "Nome do produto", "suggested_name"), ("seo_title", "Título no Google", "suggested_seo_title"),
               ("seo_description", "Resumo no Google", "suggested_seo_description"), ("slug", "Endereço (slug)", "suggested_slug"))


class SeoCheckSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reading = serializers.BooleanField(read_only=True, help_text="A análise está no worker: a tela espera e relê.")
    reading_stalled = serializers.BooleanField(read_only=True, help_text="Pediu a análise e ela não terminou.")
    issues_count = serializers.SerializerMethodField()
    suggestions_count = serializers.SerializerMethodField()

    class Meta:
        model = SeoCheck
        fields = ("id", "product", "product_name", "checked_at", "reading", "reading_stalled", "error", "score",
                  "has_search_data", "status", "status_display", "issues_count", "suggestions_count", "updated_at")
        read_only_fields = fields

    def get_issues_count(self, obj) -> int:
        return len(obj.issues or [])

    def get_suggestions_count(self, obj) -> int:
        return sum(bool(getattr(obj, column)) for _, _, column in SUGGESTIONS)


class SeoCheckDetailSerializer(SeoCheckSerializer):
    """A análise aberta: de onde veio a nota, o que melhorar, o antes e depois e os termos pesquisados."""

    suggestions = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta(SeoCheckSerializer.Meta):
        fields = (*SeoCheckSerializer.Meta.fields, "breakdown", "issues", "keywords", "suggestions", "decided_by_name", "decided_at")
        read_only_fields = fields

    @extend_schema_field({"type": "array", "items": {"type": "object"}})
    def get_suggestions(self, obj):
        ai = obj.ai_result or {}
        return [{"field": name, "label": label, "current": getattr(obj.product, name) or "", "suggested": getattr(obj, column),
                 "from_ai": bool(ai.get(name)) and ai.get(name) == getattr(obj, column)}
                for name, label, column in SUGGESTIONS if getattr(obj, column)]

    def get_decided_by_name(self, obj) -> str | None:
        return (obj.decided_by.get_full_name() or obj.decided_by.username) if obj.decided_by_id else None
