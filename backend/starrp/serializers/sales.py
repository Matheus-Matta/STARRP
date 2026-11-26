"""Venda: leitura completa e as entradas de cada ação do PDV.

A venda NÃO é editada por PATCH genérico: cada mudança é uma ação com regra
(lançar item, desconto, cupom, pagar, concluir, cancelar). O StarChef tinha
as duas portas abertas, e o PATCH genérico contornava as regras.
"""
from decimal import Decimal

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from starrp.core.costs import HideCostFieldsMixin
from starrp.core.serializers import TenantPrimaryKeyField, TenantSerializer
from starrp.models import Commission, Customer, Payment, PaymentMethod, ProductVariant, Sale, SaleChannel, SaleItem, Terminal

Money = {"max_digits": 14, "decimal_places": 2}
Qty = {"max_digits": 14, "decimal_places": 3}

ZERO, HUNDRED = Decimal("0"), Decimal("100")


class SaleItemSerializer(HideCostFieldsMixin, serializers.ModelSerializer):
    cost_fields = ("unit_cost",)

    class Meta:
        model = SaleItem
        exclude = ["account", "deleted_at", "created_by", "updated_by"]


class PaymentSerializer(serializers.ModelSerializer):
    method_name = serializers.CharField(source="method.name", read_only=True)
    method_kind = serializers.CharField(source="method.kind", read_only=True)

    class Meta:
        model = Payment
        exclude = ["account", "deleted_at", "created_by", "updated_by", "idempotency_key"]


# Ordem da nota "principal" do pedido: a autorizada vale; depois a que está andando; o resto por último.
INVOICE_RANK = {"authorized": 0, "processing": 1, "draft": 2, "error": 3, "rejected": 4, "cancelled": 5}


def invoice_summaries(sale):
    """Notas do pedido (NFC-e/NF-e), a principal primeiro: o que a tela do pedido mostra e liga."""
    rows = [i for i in sale.invoices.all() if i.deleted_at is None]
    rows.sort(key=lambda i: (INVOICE_RANK.get(i.status, 9), -(i.created_at.timestamp())))
    return [{
        "id": str(i.pk), "document_model": i.document_model, "model_label": "NFC-e" if i.document_model == "65" else "NF-e",
        "number": i.number, "series": i.series, "status": i.status, "status_label": i.get_status_display(),
        "access_key": i.access_key, "protocol": i.protocol, "authorized_at": i.authorized_at, "total": str(i.total),
        "environment": i.environment, "danfe_url": i.danfe_url, "consult_url": i.consult_url,
        "label": f"{'NFC-e' if i.document_model == '65' else 'NF-e'} {i.number or 's/ nº'}"
                 + (f" · série {i.series}" if i.series is not None else ""),
    } for i in rows]


class SaleSerializer(TenantSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    balance_due = serializers.DecimalField(read_only=True, **Money)
    customer_credit_balance = serializers.SerializerMethodField(
        help_text="Saldo atual da carteira do cliente; zero quando a venda não tem cliente.")
    store_credit_refund_allowed = serializers.SerializerMethodField(
        help_text="A regra da filial permite devolver itens como crédito na carteira.")
    seller_name = serializers.SerializerMethodField()
    shipping_address_detail = serializers.SerializerMethodField()
    addresses = serializers.SerializerMethodField(help_text="Endereços do pedido: entrega e cobrança (herdados do cliente).")
    invoices = serializers.SerializerMethodField(help_text="Notas fiscais do pedido, a principal primeiro.")

    class Meta:
        model = Sale
        fields = "__all__"
        read_only_fields = [f.name for f in Sale._meta.fields]

    def get_seller_name(self, obj):
        return (obj.seller.get_full_name() or obj.seller.username) if obj.seller_id else ""

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_customer_credit_balance(self, obj):
        if obj.customer_id is None:
            return "0.00"
        from starrp.services.checkout import credit_balance

        return str(credit_balance(obj.customer))

    def get_store_credit_refund_allowed(self, obj) -> bool:
        return bool(obj.store.rule.allow_store_credit_refund)


    def get_addresses(self, obj) -> dict:
        from starrp.services import sale_addresses

        return sale_addresses.as_dict(obj)

    def get_invoices(self, obj):
        return invoice_summaries(obj)

    def get_shipping_address_detail(self, obj):
        a = obj.shipping_address
        if a is None:
            return None
        line = ", ".join(filter(None, [a.street, a.number, a.complement]))
        place = " - ".join(filter(None, [a.district, a.city, a.state]))
        zip_code = f"{a.zip_code[:5]}-{a.zip_code[5:]}" if len(a.zip_code or "") == 8 else a.zip_code
        return {"id": str(a.pk), "label": a.label, "line": line, "place": place, "zip_code": zip_code,
                "reference": a.reference, "text": " · ".join(filter(None, [line, place, zip_code]))}

class SaleListSerializer(TenantSerializer):
    seller_name = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = ["id", "number", "channel", "status", "customer", "customer_name", "customer_document", "seller",
                  "seller_name", "item_count", "subtotal", "discount", "total", "paid_amount", "created_at",
                  "completed_at", "store", "terminal", "cash_session", "overall_status", "payment_status",
                  "fulfillment_status", "shipping_address", "refunded_amount"]

    def get_seller_name(self, obj) -> str:
        return (obj.seller.get_full_name() or obj.seller.username) if obj.seller_id else ""

    def get_item_count(self, obj) -> int:
        return sum(1 for i in obj.items.all() if i.status == SaleItem.Status.ACTIVE)


class SaleItemReportSerializer(HideCostFieldsMixin, TenantSerializer):
    """Item vendido com os dados da venda: base de "vendas do produto" e "o que o cliente comprou"."""

    cost_fields = ("unit_cost", "margin")

    sale_number = serializers.IntegerField(source="sale.number", read_only=True)
    sale_status = serializers.CharField(source="sale.status", read_only=True)
    completed_at = serializers.DateTimeField(source="sale.completed_at", read_only=True)
    customer_name = serializers.CharField(source="sale.customer_name", read_only=True)
    seller_name = serializers.SerializerMethodField()
    product = serializers.UUIDField(source="variant.product_id", read_only=True)
    margin = serializers.SerializerMethodField()

    class Meta:
        model = SaleItem
        fields = ["id", "sale", "sale_number", "sale_status", "completed_at", "customer_name", "seller_name", "variant",
                  "product", "description", "sku", "unit", "quantity", "unit_price", "discount", "total", "unit_cost",
                  "margin", "status", "cancel_reason"]
        read_only_fields = fields

    def get_seller_name(self, obj) -> str:
        seller = obj.seller or obj.sale.seller
        return (seller.get_full_name() or seller.username) if seller else ""

    def get_margin(self, obj) -> str:
        return str((obj.total - obj.unit_cost * obj.quantity).quantize(Decimal("0.01")))


class ApprovalField(serializers.DictField):
    """{"username", "password"} de um superior ou {"cash_password"}."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("child", serializers.CharField())
        super().__init__(**kwargs)


class SaleCreateSerializer(serializers.Serializer):
    # Loja virtual é da integração, nunca de quem chama a API (R4-15: liberava cupom só do site no balcão).
    channel = serializers.ChoiceField(choices=[c for c in SaleChannel.choices if c[0] != SaleChannel.ECOMMERCE],
                                      default="pos")
    terminal = TenantPrimaryKeyField(Terminal, required=False, allow_null=True)
    seller = serializers.IntegerField(required=False, allow_null=True)
    customer = TenantPrimaryKeyField(Customer, required=False, allow_null=True)
    customer_document = serializers.CharField(required=False, allow_blank=True, default="")
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")


class SaleCustomerSerializer(serializers.Serializer):
    customer = TenantPrimaryKeyField(Customer, required=False, allow_null=True)
    customer_document = serializers.CharField(required=False, allow_blank=True)
    customer_name = serializers.CharField(required=False, allow_blank=True)
    seller = serializers.IntegerField(required=False, allow_null=True)
    # Sem `freight` (M-04): o frete vem da tabela (`/delivery/`); por aqui o vendedor zerava sem autorização.
    notes = serializers.CharField(required=False, allow_blank=True)


class AddItemSerializer(serializers.Serializer):
    variant = TenantPrimaryKeyField(ProductVariant, required=False)
    code = serializers.CharField(required=False, help_text="Código de barras, SKU ou etiqueta de balança.")
    quantity = serializers.DecimalField(required=False, min_value=ZERO, **Qty)

    def validate_quantity(self, value):
        # Zero não vira 1 em silêncio: quem mandou 0 errou (sem o campo, vale 1 ou a quantidade da etiqueta).
        if value is not None and value <= 0:
            raise serializers.ValidationError("A quantidade precisa ser maior que zero.")
        return value
    discount = serializers.DecimalField(required=False, default=0, min_value=ZERO, **Money)
    unit_price = serializers.DecimalField(required=False, min_value=ZERO, **Money)
    seller = serializers.IntegerField(required=False, allow_null=True)
    approval = ApprovalField()
    metafields = serializers.DictField(required=False)
    services = TenantPrimaryKeyField(ProductVariant, many=True, required=False,
                                     help_text="Serviços (variantes de produto-serviço) lançados junto, no item.")
    service_for = serializers.UUIDField(required=False, help_text="Item da venda ao qual este serviço pertence.")

    def validate(self, attrs):
        if not attrs.get("variant") and not attrs.get("code"):
            raise serializers.ValidationError("Informe a variante ou o código.")
        return attrs


class UpdateItemSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(required=False, min_value=ZERO, **Qty)
    discount = serializers.DecimalField(required=False, min_value=ZERO, **Money)
    approval = ApprovalField()


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    approval = ApprovalField()


class DiscountSerializer(serializers.Serializer):
    amount = serializers.DecimalField(required=False, min_value=ZERO, **Money)
    percent = serializers.DecimalField(required=False, min_value=ZERO, max_value=HUNDRED, max_digits=5, decimal_places=2)
    approval = ApprovalField()


class CouponSerializer(serializers.Serializer):
    code = serializers.CharField()


class PaymentInputSerializer(serializers.Serializer):
    method = TenantPrimaryKeyField(PaymentMethod)
    amount = serializers.DecimalField(min_value=ZERO, **Money)
    tendered = serializers.DecimalField(required=False, min_value=ZERO, **Money)
    installments = serializers.IntegerField(required=False, default=1, min_value=1)
    card_brand = serializers.CharField(required=False, allow_blank=True)
    authorization_code = serializers.CharField(required=False, allow_blank=True)
    nsu = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)


class CheckoutSerializer(serializers.Serializer):
    payments = PaymentInputSerializer(many=True)


class CommissionSerializer(TenantSerializer):
    seller_name = serializers.CharField(source="seller.get_full_name", read_only=True)
    sale_number = serializers.IntegerField(source="sale.number", read_only=True)

    class Meta:
        model = Commission
        fields = "__all__"
        # Nem o status (R2-14): "paga" → "pendente" pagava de novo. Muda só por pagamento, devolução e cancelamento.
        read_only_fields = [f.name for f in Commission._meta.fields]
