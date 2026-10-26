"""Avaliações (padrão do StarHub) pela retaguarda e pelo link público do cliente.

    GET  /reviews/                    lista (filtros: tipo, situação, nota, produto, cliente, venda)
    POST /reviews/                    registra uma avaliação contada pelo cliente (balcão, telefone)
    POST /reviews/{id}/approve/       aprova (passa a contar como pública)
    POST /reviews/{id}/reject/        rejeita {reason} (o cliente pode avaliar de novo)
    GET  /reviews/link/?sale=<id>     link assinado para o cliente avaliar a compra (e o texto do WhatsApp)
    GET  /public/reviews/<token>/     o que o cliente vê no link (sem login)
    POST /public/reviews/<token>/     o cliente envia {data: JSON} + fotos `photos_<produto>`
"""
import json

from django.conf import settings
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.errors import BusinessError
from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer
from starrp.core.text import decimals_as_text
from starrp.core.viewsets import TenantViewSet
from starrp.models import Customer, Product, Review, Sale
from starrp.services import reviews


class ReviewSerializer(TenantSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True, default=None)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    sale_number = serializers.IntegerField(source="sale.number", read_only=True, default=None)
    store_name = serializers.CharField(source="store.name", read_only=True)
    moderated_by_name = serializers.CharField(source="moderated_by.get_full_name", read_only=True, default=None)
    photo_urls = serializers.SerializerMethodField()
    product = TenantPrimaryKeyField(Product, required=False, allow_null=True)
    sale = TenantPrimaryKeyField(Sale, required=False, allow_null=True)
    customer = TenantPrimaryKeyField(Customer, required=False, allow_null=True)

    class Meta:
        model = Review
        exclude = ["photos"]
        read_only_fields = ["public_name", "status", "rejection_reason", "moderated_at", "moderated_by",
                            "verified_purchase", "origin", "store"]

    def get_photo_urls(self, obj):
        return [image.file.url for image in obj.photos.all()]


class ReviewViewSet(TenantViewSet):
    model = Review
    serializer_class = ReviewSerializer
    permission_code = "sales"
    http_method_names = ["get", "post", "delete", "head", "options"]
    select_related = ("product", "customer", "sale", "store", "moderated_by")
    prefetch_related = ("photos",)
    filterset_fields = {"kind": ["exact"], "status": ["exact"], "rating": ["exact", "gte", "lte"], "product": ["exact"],
                        "customer": ["exact"], "sale": ["exact"], "verified_purchase": ["exact"],
                        "created_at": ["gte", "lte"]}
    search_fields = ["public_name", "comment", "product__name", "customer__name"]
    action_permissions = {"link": "sales.view"}

    def create(self, request, *args, **kwargs):
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        if request.store is None:
            raise BusinessError("Selecione a filial (X-Store-ID) para registrar a avaliação.", code="store_required")
        review = reviews.create(account_id=request.account.pk, store_id=request.store.pk, kind=data.get("kind", "product"),
                                rating=data.get("rating"), comment=data.get("comment", ""), product=data.get("product"),
                                sale=data.get("sale"), customer=data.get("customer"), user=request.user,
                                origin=Review.Origin.BACKOFFICE)
        return Response(self.get_serializer(review).data, status=201)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(self.get_serializer(reviews.moderate(self.get_object(), Review.Status.APPROVED, request.user)).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        review = reviews.moderate(self.get_object(), Review.Status.REJECTED, request.user, str(request.data.get("reason", "")))
        return Response(self.get_serializer(review).data)

    @action(detail=False, methods=["get"])
    def link(self, request):
        sale = Sale.objects.filter(pk=request.query_params.get("sale")).select_related("store", "customer").first()
        if sale is None:
            raise BusinessError("Venda não encontrada.", code="not_found")
        url = f"{settings.FRONTEND_URL.rstrip('/')}/avaliar/{reviews.link_token(sale)}"
        name = reviews.public_name(sale.customer.name if sale.customer_id else sale.customer_name).split(" ")[0]
        text = (f"Olá{', ' + name if name != 'Cliente' else ''}! Obrigado pela compra na {sale.store.name}. "
                f"Conta pra gente o que achou dos produtos{' e da entrega' if sale.shipping_address_id else ''}? "
                f"Leva menos de 1 minuto: {url}")
        phone = "".join(ch for ch in (sale.customer.phone if sale.customer_id else "") if ch.isdigit())
        return Response({"url": url, "text": text, "phone": phone})


class PublicReviewView(APIView):
    """O cliente avalia a compra pelo link (sem login). Só o que o link assinado permite."""

    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, token):
        return Response(decimals_as_text(reviews.public_view(reviews.sale_from_token(token))))

    def post(self, request, token):
        sale = reviews.sale_from_token(token)
        raw = request.data.get("data")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or request.data)
        except ValueError:
            raise BusinessError("Dados da avaliação inválidos.") from None
        created = reviews.submit(sale, payload, request.FILES)
        return Response({"created": len(created), "view": decimals_as_text(reviews.public_view(sale))}, status=201)
