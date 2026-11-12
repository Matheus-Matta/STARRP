from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from starrp.core.serializers import TenantSerializer
from starrp.models import Brand, Category, CompetitorPrice, MarketOffer, PriceCheck, Product
from starrp.services.market import sources


class PriceCheckSerializer(serializers.ModelSerializer):
    product = serializers.CharField(source="variant.product_id", read_only=True)
    product_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    shelf_price = serializers.DecimalField(source="variant.price", max_digits=12, decimal_places=2, read_only=True)
    position_display = serializers.CharField(source="get_position_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    decided_by_name = serializers.SerializerMethodField()
    # A conta nunca vê qual API foi usada (ver services/market/sources.py).
    source = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    standing = serializers.CharField(read_only=True, help_text="Nosso lugar entre os concorrentes: 2º de 6.")
    reading = serializers.BooleanField(read_only=True, help_text="A leitura está no worker: a tela espera e relê.")
    reading_stalled = serializers.BooleanField(read_only=True, help_text="Pediu a leitura e ela não terminou.")

    class Meta:
        model = PriceCheck
        fields = ("id", "variant", "product", "product_name", "sku", "shelf_price", "checked_at", "reading", "reading_stalled", "source", "error", "ai_note",
                  "current_price", "cost", "current_margin", "competitors", "offers_found", "market_min",
                  "market_p25", "market_median", "market_p75", "market_avg", "market_max", "market_rank", "standing", "price_index", "dispersion", "confidence",
                  "position", "position_display", "suggested_price", "suggested_margin", "floor_price", "worth_it",
                  "needs_review", "reason", "status", "status_display", "decided_by", "decided_by_name",
                  "decided_at", "applied_price", "previous_price", "updated_at")
        read_only_fields = fields

    def get_source(self, obj) -> str:
        return sources.public_sources(obj.source)

    def get_error(self, obj) -> str:
        return sources.public_error(obj.error)

    def get_decided_by_name(self, obj):
        return (obj.decided_by.get_full_name() or obj.decided_by.username) if obj.decided_by_id else None


class MarketOfferSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()

    def get_source(self, obj) -> str:
        return sources.public_key(obj.source)

    class Meta:
        model = MarketOffer
        fields = ("id", "price_check", "source", "query", "observed_at", "external_id", "title", "url", "seller", "price", "free_shipping",
                  "match_score", "match_reason", "used")
        read_only_fields = fields


class PriceCheckDetailSerializer(PriceCheckSerializer):
    """O processo aberto: com o que foi achado no mercado, para conferir oferta por oferta."""

    offers = MarketOfferSerializer(many=True, read_only=True)
    searches = serializers.SerializerMethodField()

    @extend_schema_field({"type": "array", "items": {"type": "object"}})
    def get_searches(self, obj):
        return sources.public_searches(obj.searches)

    class Meta(PriceCheckSerializer.Meta):
        fields = (*PriceCheckSerializer.Meta.fields, "searches", "offers")
        read_only_fields = fields


class PriceScopeSerializer(serializers.Serializer):
    """As regras da precificação (ver services/market/scope.py). Id de outra conta é recusado."""

    categories = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    brands = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    products = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    exclude_products = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    min_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False,
                                         allow_null=True, default=None)
    max_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False,
                                         allow_null=True, default=None)
    only_in_stock = serializers.BooleanField(required=False, default=False)
    only_with_barcode = serializers.BooleanField(required=False, default=False)

    MODELS = {"categories": Category, "brands": Brand, "products": Product, "exclude_products": Product}

    def validate(self, attrs):
        account = self.context["account"]
        for field, model in self.MODELS.items():
            ids = set(attrs[field])
            if model.all_objects.filter(account=account, deleted_at__isnull=True, pk__in=ids).count() != len(ids):
                raise serializers.ValidationError({field: "Há item que não existe nesta conta."})
        low, high = attrs["min_price"], attrs["max_price"]
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError({"max_price": "O preço máximo está menor que o mínimo."})
        return attrs


class CompetitorPriceSerializer(TenantSerializer):
    product_name = serializers.CharField(source="variant.display_name", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)

    class Meta:
        model = CompetitorPrice
        fields = ["id", "variant", "product_name", "sku", "competitor", "price", "observed_on", "url", "notes",
                  "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Informe um preço maior que zero.")
        return value
