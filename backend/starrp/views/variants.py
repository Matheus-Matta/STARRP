"""Variantes e volumes para LEITURA: busca do PDV, seleção em documentos de
estoque, NF-e e promoções, etiquetas e conferência. Cadastro e alteração são
pelo produto (`/catalog/products/`), que grava a lista completa de variantes."""
from django.db.models import Sum
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import ReadOnlyTenantViewSet
from starrp.models import ProductVariant, ProductVolume
from starrp.serializers import catalog as s
from starrp.services import pricing
from starrp.services.barcodes import resolve_code


class VariantViewSet(ReadOnlyTenantViewSet):
    model = ProductVariant
    serializer_class = s.VariantListSerializer
    permission_code = "catalog"
    select_related = ("product__category",)
    prefetch_related = ("barcodes", "volumes", "images__image", "product__images__image", "product__variants")
    filterset_fields = ["product", "is_active", "product__is_active", "product__type", "product__category", "product__brand"]
    search_fields = ["product__name", "name", "sku", "barcodes__code"]
    ordering_fields = ["product__name", "sku", "price"]

    def get_queryset(self):
        qs = super().get_queryset().filter(product__deleted_at__isnull=True)
        if self.request.query_params.get("with_stock") in {"1", "true"}:
            qs = qs.annotate(stock_quantity=Sum("balances__quantity"))
        return qs.distinct() if self.request.query_params.get("search") else qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # Preço vigente (com promoção) de cada linha, em poucas consultas.
        rows = response.data.get("results", response.data) if isinstance(response.data, dict) else response.data
        variants = list(ProductVariant.all_objects.filter(pk__in=[row["id"] for row in rows]).select_related("product"))
        offers = {str(pk): o for pk, o in pricing.offers_for(variants, getattr(request.store, "pk", None)).items()}
        for row in rows:
            offer = offers.get(str(row["id"]))
            row["current_price"] = str(offer.price) if offer else row["promotional_price"] or row["price"]
        return response

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        """PDV: lê código de barras, SKU, etiqueta de balança ou de volume e devolve o preço vigente."""
        result = resolve_code(request.account.id, request.query_params.get("code", ""))
        if result is None:
            raise BusinessError("Produto não encontrado para este código.", code="product_not_found")
        quote = pricing.quote(result.variant, getattr(request.store, "pk", None))
        data = s.VariantListSerializer(result.variant, context={"request": request}).data
        data.update({"current_price": str(quote.unit_price), "list_price": str(quote.list_price),
                     "promotion": str(quote.promotion.pk) if quote.promotion else None,
                     "scale_quantity": str(result.quantity) if result.quantity is not None else None,
                     "volume": result.volume.number if result.volume else None})
        return Response(data)


class ProductVolumeViewSet(ReadOnlyTenantViewSet):
    """Caixas cadastradas (para etiquetas e conferência)."""

    model = ProductVolume
    serializer_class = s.VolumeSerializer
    permission_code = "catalog"
    select_related = ("variant__product",)
    filterset_fields = ["variant", "variant__product"]
    search_fields = ["barcode", "variant__sku", "variant__product__name"]
