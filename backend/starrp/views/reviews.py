"""Avaliações (padrão do StarHub) pela retaguarda e pelo link público do cliente.

    GET  /reviews/                    lista (filtros: tipo, situação, nota, produto, cliente, venda)
    POST /reviews/                    registra uma avaliação contada pelo cliente (balcão, telefone)
    POST /reviews/{id}/approve/       aprova (passa a contar como pública)
    POST /reviews/{id}/reject/        rejeita {reason} (o cliente pode avaliar de novo)
    GET  /reviews/links/?sale=<id>    os links da venda por tipo (pedido, entrega) e a situação de cada
    POST /reviews/links/              gera {sale, kind: order|delivery, days} (um valendo é devolvido igual)
    GET  /public/reviews/<token>/     o que o cliente vê no link (sem login)
    POST /public/reviews/<token>/     o cliente envia {data: JSON} + fotos `photos_<produto>`; o link fica usado
"""
import json

from django.conf import settings
from django.utils import timezone
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
from starrp.models import Customer, Product, Review, ReviewLink, Sale
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
    action_permissions = {"links": "sales.view"}

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

    @action(detail=False, methods=["get", "post"])
    def links(self, request):
        """GET: um item por tipo que a venda pode avaliar, com o link atual (se houver).
        POST {sale, kind, days}: gera o link do tipo (ou devolve o que ainda vale)."""
        source = request.data if request.method == "POST" else request.query_params
        sale = Sale.objects.filter(pk=source.get("sale")).select_related("store", "customer").first()
        if sale is None:
            raise BusinessError("Venda não encontrada.", code="not_found")
        if request.method == "POST":
            reviews.generate_link(sale, str(source.get("kind", "")), request.user, source.get("days") or reviews.LINK_DAYS)
        now = timezone.now()
        latest = {}
        for link in ReviewLink.all_objects.filter(sale=sale, deleted_at__isnull=True).order_by("created_at"):
            latest[link.kind] = link  # o mais novo de cada tipo
        return Response([_link_row(sale, kind, latest.get(kind), now) for kind in reviews.kinds_of(sale)])


def _link_row(sale, kind, link, now):
    reviewed = reviews.already_reviewed(sale, kind)
    row = {"kind": kind, "label": ReviewLink.Kind(kind).label, "reviewed": reviewed,
           "state": "used" if reviewed else reviews.link_state(link, now) if link else "none"}
    if link is None:
        return row
    url = f"{settings.FRONTEND_URL.rstrip('/')}/avaliar/{link.token}"
    name = reviews.public_name(sale.customer.name if sale.customer_id else sale.customer_name).split(" ")[0]
    what = "da entrega" if kind == ReviewLink.Kind.DELIVERY else "dos produtos"
    text = (f"Olá{', ' + name if name != 'Cliente' else ''}! Obrigado pela compra na {sale.store.name} "
            f"(pedido {sale.number}). Conta pra gente o que achou {what}? Leva menos de 1 minuto: {url}")
    phone = "".join(ch for ch in (sale.customer.phone if sale.customer_id else "") if ch.isdigit())
    return {**row, "url": url, "text": text, "phone": phone, "expires_at": link.expires_at, "used_at": link.used_at,
            "created_at": link.created_at}


class PublicReviewView(APIView):
    """O cliente avalia pelo link (sem login): só o tipo do link, uma vez, até a data limite."""

    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, token):
        return Response(decimals_as_text(reviews.public_view(reviews.link_from_token(token))))

    def post(self, request, token):
        raw = request.data.get("data")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or request.data)
        except ValueError:
            raise BusinessError("Dados da avaliação inválidos.") from None
        link, created = reviews.submit(token, payload, request.FILES)
        return Response({"created": len(created), "kind": link.kind}, status=201)
