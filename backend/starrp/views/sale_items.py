"""Itens vendidos para consulta (somente leitura): vendas de um produto, compras de um cliente."""
from starrp.core.viewsets import ReadOnlyTenantViewSet
from starrp.models import SaleItem
from starrp.serializers import sales as s


class SaleItemViewSet(ReadOnlyTenantViewSet):
    """Itens vendidos: `?variant__product=<id>&sale__status=completed` = vendas do produto;
    `?sale__customer=<id>` = o que o cliente comprou."""

    model = SaleItem
    serializer_class = s.SaleItemReportSerializer
    permission_code = "sales"
    select_related = ("sale__seller", "seller", "variant")
    filterset_fields = {"variant": ["exact"], "variant__product": ["exact"], "sale": ["exact"], "status": ["exact"],
                        "sale__customer": ["exact"], "sale__cash_session": ["exact"], "sale__status": ["exact"],
                        "sale__completed_at": ["gte", "lte"]}
    search_fields = ["description", "sku", "sale__customer_name"]
    ordering_map = {"sale_number": "sale__number", "completed_at": "sale__completed_at",
                    "customer_name": "sale__customer_name", "seller_name": "sale__seller__first_name"}
