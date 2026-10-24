
from django.db.models import Count, Max, Min, Q, Sum
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from starrp.core.bulk import bulk_action
from starrp.core.bulk_helpers import add_tags, related_param, set_field
from starrp.core.errors import BusinessError
from starrp.core.viewsets import ReadOnlyTenantViewSet, TenantViewSet
from starrp.models import (
    Attribute, AttributeValue, Brand, Category, Image, KitComponent, Product, ProductImage, ServiceRule,
    SupplierProduct, Tag,
)
from starrp.serializers import tags as tag_serializers
from starrp.serializers import catalog as s
from starrp.services import media, variant_grid

VARIANT_PREFETCH = ("variants__barcodes", "variants__volumes", "variants__variant_values__value__attribute",
                    "images__image", "variants__images__image")
ALIVE_VARIANT = Q(variants__deleted_at__isnull=True)


class CategoryViewSet(TenantViewSet):
    model = Category
    serializer_class = s.CategorySerializer
    tree_parent = "parent"
    permission_code = "catalog"
    filterset_fields = ["parent", "is_active"]
    search_fields = ["name"]


class ServiceRuleViewSet(TenantViewSet):
    """Serviços oferecidos com os produtos. `?product=` = as regras que pegam aquele produto."""

    model = ServiceRule
    serializer_class = s.ServiceRuleSerializer
    permission_code = "catalog"
    filterset_fields = ["service", "kind", "is_active"]
    search_fields = ["service__name"]

    def get_queryset(self):
        return super().get_queryset().select_related("service").prefetch_related(
            "service__variants", "categories", "products")


class BrandViewSet(TenantViewSet):
    model = Brand
    serializer_class = s.BrandSerializer
    permission_code = "catalog"
    filterset_fields = ["is_active"]
    search_fields = ["name"]


class AttributeViewSet(TenantViewSet):
    """Eixos da grade (Cor, Tamanho) com os valores cadastrados."""

    model = Attribute
    serializer_class = s.AttributeSerializer
    permission_code = "catalog"
    prefetch_related = ("values",)
    search_fields = ["name"]


class AttributeValueViewSet(TenantViewSet):
    model = AttributeValue
    serializer_class = s.AttributeValueSerializer
    permission_code = "catalog"
    select_related = ("attribute",)
    filterset_fields = ["attribute"]
    search_fields = ["value"]


class ProductViewSet(TenantViewSet):
    """Produto com as variantes aninhadas. Venda e estoque usam /catalog/variants/."""

    model = Product
    serializer_class = s.ProductSerializer
    permission_code = "catalog"
    select_related = ("category", "brand", "fiscal_profile")
    prefetch_related = (*VARIANT_PREFETCH, "tags")
    filterset_fields = {"type": ["exact", "in"], "purpose": ["exact"], "sale_method": ["exact"], "brand": ["exact"],
                        "is_active": ["exact"], "track_stock": ["exact"]}
    search_fields = ["name", "reference", "variants__sku", "variants__barcodes__code"]
    # Colunas que vêm das variantes: ordenam por um valor calculado (ver core/ordering.py).
    ordering_annotations = {
        "sku": Max("variants__sku", filter=ALIVE_VARIANT & Q(variants__is_default=True)),
        "price": Min("variants__price", filter=ALIVE_VARIANT),
        "price_max": Max("variants__price", filter=ALIVE_VARIANT),
        "variant_count": Count("variants", filter=ALIVE_VARIANT),
    }

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get("category")
        if category:  # a categoria e as de dentro dela (até 3 níveis)
            ids, level = {category}, {category}
            for _ in range(3):
                level = set(map(str, Category.objects.filter(parent__in=level).values_list("pk", flat=True)))
                ids |= level
            qs = qs.filter(category__in=ids)
        if self.request.query_params.get("with_stock") in {"1", "true"}:
            qs = qs.annotate(stock_quantity=Sum("variants__balances__quantity"))
        qs = filter_by_tag(qs, self.request)
        # A busca por SKU/código passa pelas variantes: sem distinct, o produto se repetiria.
        return qs.distinct() if self.request.query_params.get("search") else qs

    @bulk_action("Definir categoria", icon="pi pi-sitemap", params=[
        {"name": "category", "label": "Categoria", "type": "relation", "required": True, "creatable": True,
         "relation": {"endpoint": "/catalog/categories/"}}])
    def bulk_set_category(self, request, queryset, params):
        category = related_param(request, params, "category", Category, "a categoria")
        return set_field(self, request, queryset, "category", category)

    @bulk_action("Definir marca", icon="pi pi-tag", params=[
        {"name": "brand", "label": "Marca", "type": "relation", "required": True, "creatable": True,
         "relation": {"endpoint": "/catalog/brands/"}}])
    def bulk_set_brand(self, request, queryset, params):
        brand = related_param(request, params, "brand", Brand, "a marca")
        return set_field(self, request, queryset, "brand", brand)

    @bulk_action("Adicionar tags", icon="pi pi-hashtag", params=[
        {"name": "tags", "label": "Tags", "type": "tags", "required": True,
         "tagSource": {"endpoint": "/tags/", "params": {"scope": "product"}}}])
    def bulk_add_tags(self, request, queryset, params):
        return add_tags(self, request, queryset, params, Tag.Scope.PRODUCT)

    @action(detail=True, methods=["post"], url_path="generate-variants")
    def generate_variants(self, request, pk=None):
        """Cria as combinações que faltam: {"attributes": {"Cor": ["Azul"], "Tamanho": ["P", "M"]}}."""
        product = self.get_object()
        body = s.VariantGridSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        variant_grid.generate_variants(product, body.validated_data["attributes"], request.user,
                                  price=body.validated_data.get("price"))
        product = Product.all_objects.prefetch_related(*VARIANT_PREFETCH).get(pk=product.pk)
        return Response(self.get_serializer(product).data, status=201)


def filter_by_tag(qs, request):
    """`?tag=verão` filtra pela tag (sem diferença de maiúscula)."""
    tag = request.query_params.get("tag", "").strip()
    return qs.filter(tags__normalized=tag.casefold()).distinct() if tag else qs


class TagViewSet(ReadOnlyTenantViewSet):
    """Sugestões para o campo de tags: `?scope=product&search=ver`. Grava-se pelo registro."""

    model = Tag
    serializer_class = tag_serializers.TagSerializer
    filterset_fields = ["scope"]
    search_fields = ["name"]


class KitComponentViewSet(TenantViewSet):
    model = KitComponent
    serializer_class = s.KitComponentSerializer
    permission_code = "catalog"
    select_related = ("component__product",)
    filterset_fields = ["kit", "component"]

    def perform_create(self, serializer):
        if serializer.validated_data["kit"].type != Product.Type.KIT:
            raise BusinessError("Componentes só se ligam a produto do tipo Kit.")
        super().perform_create(serializer)


class ProductImageViewSet(TenantViewSet):
    model = ProductImage
    serializer_class = s.ProductImageSerializer
    permission_code = "catalog"
    filterset_fields = ["product", "variant"]


class SupplierProductViewSet(TenantViewSet):
    model = SupplierProduct
    serializer_class = s.SupplierProductSerializer
    permission_code = "catalog"
    filterset_fields = ["supplier", "variant", "confirmed"]
    search_fields = ["supplier_code", "supplier_barcode", "supplier_description"]


class ImageViewSet(TenantViewSet):
    model = Image
    serializer_class = s.ImageSerializer
    permission_code = "catalog"
    parser_classes = [MultiPartParser, FormParser]

    def initial(self, request, *args, **kwargs):
        # Upload é multipart, não JSON: pula a checagem de corpo-objeto da base.
        super(TenantViewSet, self).initial(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Envio (multipart `file`): confere, reduz se for enorme e reaproveita o mesmo arquivo."""
        upload = request.FILES.get("file")
        if upload is None:
            raise BusinessError("Envie o arquivo no campo `file`.")
        image = media.store_upload(request.account, request.user, upload, alt=str(request.data.get("alt", "")))
        return Response(self.get_serializer(image).data, status=201)
