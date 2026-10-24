from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer, tenant_serializer
from starrp.models import (
    Attribute, AttributeValue, Brand, Category, Image, KitComponent, Product, ProductBarcode, ProductImage,
    ProductVariant, ProductVolume, ServiceRule, SupplierProduct, Tag,
)
from starrp.serializers.tags import TaggedSerializerMixin
from starrp.core.text import clean_html
from starrp.services import catalog, media, variant_grid



class RichSeoMixin:
    """Descrição do editor chega limpa (sem script) e o slug sai do nome quando vazio.
    Ex.: "Camiseta Básica" → slug "camiseta-basica" (ou "camiseta-basica-2" se já existir)."""

    def validate_description(self, value):
        return clean_html(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        sent = attrs.get("slug")
        if sent is not None or self.instance is None or not self.instance.slug:
            name = attrs.get("name") or getattr(self.instance, "name", "")
            attrs["slug"] = catalog.free_slug(self.Meta.model, self.context["request"].account.pk, sent or name,
                                              getattr(self.instance, "pk", None))
        return attrs


class CategorySerializer(RichSeoMixin, TenantSerializer):
    class Meta:
        model = Category
        fields = "__all__"


BrandSerializer = tenant_serializer(Brand)
AttributeValueSerializer = tenant_serializer(AttributeValue, read_only=("normalized",))
KitComponentSerializer = tenant_serializer(KitComponent)
ProductImageSerializer = tenant_serializer(ProductImage)
SupplierProductSerializer = tenant_serializer(SupplierProduct)


class AttributeSerializer(TenantSerializer):
    values = AttributeValueSerializer(many=True, read_only=True)

    class Meta:
        model = Attribute
        fields = "__all__"


class ImageSerializer(TenantSerializer):
    # Endereço relativo (/media/...): a tela e o servidor de arquivos ficam na mesma origem.
    url = serializers.SerializerMethodField()

    class Meta:
        model = Image
        fields = ["id", "url", "original_name", "content_type", "size", "width", "height", "alt_text", "created_at"]
        read_only_fields = ["original_name", "content_type", "size", "width", "height"]

    def get_url(self, obj):
        return obj.file.url if obj.file else None


class GalleryItemSerializer(serializers.Serializer):
    image = TenantPrimaryKeyField(Image)
    alt = serializers.CharField(max_length=255, required=False, allow_blank=True)


class GalleryField(serializers.Field):
    """Galeria (produto ou variante) com uma chave só, `images`, para ler e gravar.

    Lê:   [{"image": "<id>", "url": "/media/...", "alt": "...", "width": 800, "height": 800}]
    Grava: [{"image": "<id>", "alt": "..."}] — a ordem é a posição; a 1ª é a capa.
    """

    def __init__(self, **kwargs):
        super().__init__(source="*", required=False, **kwargs)

    def to_representation(self, obj):
        # Produto: só as do produto (variante vazia). Variante: as dela.
        return media.gallery(obj.images.all(), obj.pk if isinstance(obj, ProductVariant) else None)

    def to_internal_value(self, data):
        items = GalleryItemSerializer(data=data, many=True, context=self.context)
        items.is_valid(raise_exception=True)
        return {"gallery": items.validated_data}


class BarcodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductBarcode
        fields = ["id", "code", "is_primary"]

    def validate_code(self, value):
        from starrp.services.barcodes import ean_check_digit_ok

        value = value.strip()
        # Código numérico no tamanho de GTIN precisa fechar o dígito verificador;
        # o prefixo "2" é de uso interno (etiqueta própria/balança) e passa.
        if value.isdigit() and len(value) in (8, 12, 13, 14) and not value.startswith("2"):
            if not ean_check_digit_ok(value):
                raise serializers.ValidationError("Dígito verificador do EAN/GTIN inválido.")
        return value


class VolumeSerializer(serializers.ModelSerializer):
    """Caixa da variante. O número sai da ordem da lista (1ª = Vol 1)."""

    cubic_meters = serializers.DecimalField(max_digits=12, decimal_places=6, read_only=True)

    class Meta:
        model = ProductVolume
        fields = ["id", "number", "description", "barcode", "gross_weight", "height_cm", "width_cm", "length_cm",
                  "cubic_meters"]
        read_only_fields = ["number"]


class VariantSerializer(TenantSerializer):
    """Variante aninhada no produto. `values` = ids dos valores da grade (Cor: Azul...)."""

    id = serializers.UUIDField(required=False)
    sku = serializers.CharField(max_length=60, required=False, allow_blank=True)
    values = TenantPrimaryKeyField(AttributeValue, many=True, required=False)
    options = serializers.SerializerMethodField()
    barcodes = BarcodeSerializer(many=True, required=False)
    volumes = VolumeSerializer(many=True, required=False)
    images = GalleryField()

    class Meta:
        model = ProductVariant
        exclude = ["product", "account", "deleted_at", "created_by", "updated_by"]
        read_only_fields = ["average_cost", "last_cost", "position"]

    def get_fields(self):
        fields = super().get_fields()
        # O `id` da variante PRECISA ser gravável: é ele que diz "esta já existe".
        # A base marca todo `id` como só-leitura; sem isto cada salvar do produto
        # apagava as variantes e criava novas (perdendo o vínculo com o estoque).
        fields["id"] = serializers.UUIDField(required=False)
        return fields

    @extend_schema_field({"type": "array", "items": {"type": "object", "properties": {
        "attribute": {"type": "string"}, "value": {"type": "string"}, "value_id": {"type": "string"}}}})
    def get_options(self, obj):
        rows = [vv.value for vv in obj.variant_values.all() if vv.deleted_at is None]
        return [{"attribute": v.attribute.name, "value": v.value, "value_id": str(v.pk)} for v in rows]


class ProductSerializer(RichSeoMixin, TaggedSerializerMixin, TenantSerializer):
    """Produto + a lista COMPLETA de variantes (simples: uma só).

    Exemplo de produto simples:
        {"name": "Café 500g", "type": "simple",
         "variants": [{"sku": "CAF500", "price": "18.90", "barcodes": [{"code": "7891000315507"}]}]}

    Produto com grade pode mandar `grid` no lugar (ou além) das variantes. A grade
    enviada é a do produto: combinação que falta é criada e o que saiu (eixo ou
    valor) sai das variantes (ver `services/variant_grid.py`).
        {"name": "Camiseta", "type": "variable", "grid": {"Cor": ["Azul"], "Tamanho": ["P", "M"]}}
    """

    tag_scope = Tag.Scope.PRODUCT
    variants = VariantSerializer(many=True, required=False)
    images = GalleryField()
    cover = serializers.SerializerMethodField(help_text="Capa: 1ª imagem do produto ou da variante padrão.")
    grid = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField(max_length=60), min_length=1),
        write_only=True, required=False,
    )
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    brand_name = serializers.CharField(source="brand.name", read_only=True, default=None)
    sku = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField(help_text="Menor preço entre as variantes.")
    price_max = serializers.SerializerMethodField(help_text="Maior preço (igual ao `price` sem grade).")
    variant_count = serializers.SerializerMethodField()
    stock_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, required=False)

    class Meta:
        model = Product
        fields = "__all__"

    def get_cover(self, obj):
        return media.cover(obj)

    def _variants(self, obj):
        return [v for v in obj.variants.all() if v.deleted_at is None]

    def get_sku(self, obj):
        default = obj.default_variant
        return default.sku if default else ""

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_price(self, obj):
        prices = [v.price for v in self._variants(obj)]
        return str(min(prices)) if prices else None

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_price_max(self, obj):
        prices = [v.price for v in self._variants(obj)]
        return str(max(prices)) if prices else None

    @extend_schema_field(OpenApiTypes.INT)
    def get_variant_count(self, obj):
        return len(self._variants(obj))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None and not attrs.get("variants") and not attrs.get("grid"):
            raise serializers.ValidationError({"variants": "Informe ao menos uma variante (SKU e preço) ou a grade."})
        if attrs.get("type") == Product.Type.SERVICE:
            attrs.setdefault("purpose", Product.Purpose.SERVICE)
        if "metafields" in attrs:
            from starrp.services import metafields

            category = attrs.get("category", getattr(self.instance, "category", None))
            attrs["metafields"] = metafields.clean(self.context["request"].account.pk, "product",
                                                   attrs["metafields"], category=category)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        rows, grid = validated_data.pop("variants", None), validated_data.pop("grid", None)
        images = validated_data.pop("gallery", None)
        return self._save_children(super().create(validated_data), rows, grid, images)

    @transaction.atomic
    def update(self, instance, validated_data):
        rows, grid = validated_data.pop("variants", None), validated_data.pop("grid", None)
        images = validated_data.pop("gallery", None)
        return self._save_children(super().update(instance, validated_data), rows, grid, images)

    def _save_children(self, product, rows, grid, images=None):
        user = self.context["request"].user
        before = {v.pk: v.display_name for v in product.variants.filter(deleted_at__isnull=True)}
        if images is not None:
            media.sync_gallery(product, None, images, user)
        if rows:
            plain = _plain(rows)
            for row, variant in zip(plain, catalog.save_variants(product, plain, user), strict=True):
                if "gallery" in row:  # galeria da variante (a camiseta azul de frente, de costas...)
                    media.sync_gallery(product, variant, row["gallery"], user)
        elif rows is not None and not grid:
            catalog.save_variants(product, [], user)  # lista vazia: o serviço recusa com a mensagem certa
        if grid is not None:  # {} = tirou todos os eixos (as variantes viram uma só)
            variant_grid.generate_variants(product, grid, user)
        # Relê com as variantes novas (o prefetch da view é de antes do salvar).
        saved = Product.all_objects.prefetch_related(
            "tags", "variants__barcodes", "variants__volumes", "variants__variant_values__value__attribute",
            "images__image", "variants__images__image",
        ).get(pk=product.pk)
        after = {v.pk for v in saved.variants.all() if v.deleted_at is None}
        created, removed = len(after - set(before)), [name for pk, name in before.items() if pk not in after]
        if created or removed:  # vira a anotação da linha no histórico
            saved.history_note = "Variantes: " + ", ".join(filter(None, [
                f"{created} criada(s)" if created else "", f"saíram {', '.join(removed[:6])}" if removed else ""]))
        return saved


def _plain(rows):
    """Validado do DRF -> linhas do serviço (valores viram ids)."""
    return [{**row, **({"values": [v.pk for v in row["values"]]} if "values" in row else {})} for row in rows]


class VariantListSerializer(TenantSerializer):
    """Variante solta (busca do PDV, seleção em documentos e promoções)."""

    product_name = serializers.CharField(source="product.name", read_only=True)
    display_name = serializers.CharField(read_only=True)
    product_type = serializers.CharField(source="product.type", read_only=True)
    category = serializers.UUIDField(source="product.category_id", read_only=True, allow_null=True)
    category_name = serializers.CharField(source="product.category.name", read_only=True, default=None)
    unit = serializers.CharField(read_only=True)
    sold_by_weight = serializers.BooleanField(read_only=True)
    barcodes = BarcodeSerializer(many=True, read_only=True)
    volume_count = serializers.SerializerMethodField()
    stock_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, required=False)
    image = serializers.SerializerMethodField(help_text="Foto da variante; sem ela, a capa do produto.")

    class Meta:
        model = ProductVariant
        fields = ["id", "product", "product_name", "product_type", "category", "category_name", "name", "display_name",
                  "sku", "price", "image",
                  "promotional_price", "unit", "sold_by_weight", "barcodes", "volume_count", "is_active",
                  "is_default", "stock_quantity"]
        read_only_fields = fields

    def get_image(self, obj):
        own = media.gallery(obj.images.all(), obj.pk)
        return own[0]["url"] if own else media.cover(obj.product)

    @extend_schema_field(OpenApiTypes.INT)
    def get_volume_count(self, obj):
        return len([v for v in obj.volumes.all() if v.deleted_at is None])


class VariantGridSerializer(serializers.Serializer):
    """Gera as variações a partir dos eixos: {"Tamanho": ["P","M"], "Cor": ["Azul"]}."""

    attributes = serializers.DictField(child=serializers.ListField(child=serializers.CharField(), min_length=1))
    price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)


class ServiceRuleSerializer(TenantSerializer):
    """Regra do serviço: a quais produtos ele vale e por quanto (padrão do StarHub)."""

    service_name = serializers.CharField(source="service.name", read_only=True)
    default_price = serializers.SerializerMethodField(help_text="Preço padrão do serviço (variante padrão).")
    categories = TenantPrimaryKeyField(Category, many=True, required=False)
    products = TenantPrimaryKeyField(Product, many=True, required=False)

    class Meta:
        model = ServiceRule
        fields = "__all__"

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_default_price(self, obj):
        variant = obj.service.default_variant
        return str(variant.price) if variant else None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        merged = {f: attrs.get(f, getattr(self.instance, f, None)) for f in ("service", "kind", "price_min", "price_max")}
        if merged["service"] is not None and merged["service"].type != Product.Type.SERVICE:
            raise serializers.ValidationError({"service": "Escolha um produto do tipo Serviço."})
        low, high = merged["price_min"], merged["price_max"]
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError({"price_max": "O mínimo da faixa passa do máximo."})
        products = attrs["products"] if "products" in attrs else (
            list(self.instance.products.all()) if self.instance else [])
        categories = attrs["categories"] if "categories" in attrs else (
            list(self.instance.categories.all()) if self.instance else [])
        if merged["kind"] == ServiceRule.Kind.PRODUCT and not products:
            raise serializers.ValidationError({"products": "Adicione ao menos um produto: regra por produto sem "
                                                           "produto não vale para nenhum."})
        if merged["kind"] != ServiceRule.Kind.PRODUCT and not categories and low is None and high is None:
            raise serializers.ValidationError({"categories": "Adicione ao menos uma categoria (ou a faixa de preço): "
                                                             "sem isso valeria para o catálogo inteiro."})
        if any(p.type == Product.Type.SERVICE for p in products):
            raise serializers.ValidationError({"products": "Serviço não recebe outro serviço."})
        # Regra é de um tipo só: o critério do outro tipo sai ao salvar.
        if merged["kind"] == ServiceRule.Kind.PRODUCT:
            attrs.update(categories=[], price_min=None, price_max=None)
        else:
            attrs["products"] = []
        return attrs
