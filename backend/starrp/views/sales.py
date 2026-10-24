"""Venda: leitura + uma rota por ação do PDV.

    POST /sales/                         abre venda
    POST /sales/{id}/items/              lança item (produto ou código lido)
    PATCH/DELETE /sales/{id}/items/{item}/   altera / cancela item
    POST /sales/{id}/customer/           cliente, CPF na nota, vendedor, frete
    POST /sales/{id}/discount/           desconto no total
    POST|DELETE /sales/{id}/coupon/      aplica / remove cupom
    POST /sales/{id}/payments/           registra pagamento
    DELETE /sales/{id}/payments/{pay}/   estorna pagamento (venda aberta)
    POST /sales/{id}/checkout/           paga e conclui numa transação
    POST /sales/{id}/complete/           conclui (já paga)
    POST /sales/{id}/cancel/             cancela
    POST /sales/{id}/returns/            abre devolução
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import BusinessError
from starrp.core.viewsets import TenantViewSet
from starrp.models import CustomerAddress, FreightTable, Payment, Sale, SaleItem
from starrp.serializers import operations as ops
from starrp.serializers import sales as s
from starrp.services import checkout, returns, sales
from starrp.services.barcodes import resolve_code
from starrp.services.cash import session_for_user
from starrp.services.store_access import sellers_of

User = get_user_model()


def _seller(store, user_id):
    """Vendedor precisa ter acesso à loja da venda (não vende em filial alheia)."""
    if not user_id:
        return None
    profile = sellers_of(store).filter(user_id=user_id).first()
    if profile is None:
        raise BusinessError("Vendedor não encontrado nesta loja.", code="seller_not_found")
    return profile.user


class SaleViewSet(TenantViewSet):
    model = Sale
    permission_code = "sales"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    select_related = ("seller", "customer")
    prefetch_related = ("items", "payments__method", "invoices")
    filterset_fields = {"status": ["exact", "in"], "overall_status": ["exact", "in"], "payment_status": ["exact", "in"],
                        "fulfillment_status": ["exact", "in"], "channel": ["exact"], "seller": ["exact"], "customer": ["exact"],
                        "terminal": ["exact"], "cash_session": ["exact"], "completed_at": ["gte", "lte"],
                        "created_by": ["exact"], "parked_by": ["exact"], "created_at": ["gte", "lte"]}
    search_fields = ["number", "customer_name", "customer_document"]
    ordering_map = {"seller_name": "seller__first_name"}
    ordering_fields = ["created_at", "completed_at", "total", "number"]
    # Receber é do CAIXA: o vendedor monta e guarda o pedido; quem cobra tem `cash.manage`.
    action_permissions = {"cancel": "sales.view", "returns": "sales.view", "payments": "cash.manage",
                          "payment_detail": "cash.manage", "checkout_action": "cash.manage", "complete": "cash.manage",
                          "fulfillment": "logistics.manage"}

    def get_serializer_class(self):
        return s.SaleListSerializer if self.action == "list" else s.SaleSerializer

    def _respond(self, sale, status=200):
        sale = Sale.all_objects.prefetch_related("items", "payments__method", "invoices").get(pk=sale.pk)
        return Response(s.SaleSerializer(sale, context=self.get_serializer_context()).data, status=status)

    def _body(self, serializer_class):
        body = serializer_class(data=self.request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        return body.validated_data

    def create(self, request, *args, **kwargs):
        if request.store is None:
            raise BusinessError("Selecione a loja (header X-Store-ID).", code="store_required")
        data = self._body(s.SaleCreateSerializer)
        sale = sales.create(
            request.store, request.user, channel=data["channel"], terminal=data.get("terminal"),
            seller=_seller(request.store, data.get("seller")), customer=data.get("customer"),
            customer_document=data["customer_document"], customer_name=data["customer_name"],
            cash_session=session_for_user(request.store, request.user),
        )
        return self._respond(sale, status=201)

    def partial_update(self, request, *args, **kwargs):
        raise BusinessError("Use as ações da venda (itens, desconto, cupom, pagamento).", code="use_actions")

    def destroy(self, request, *args, **kwargs):
        raise BusinessError("Venda não é excluída: use /cancel/.", code="use_cancel")

    @action(detail=True, methods=["post"])
    def items(self, request, pk=None):
        sale = self.get_object()
        data = self._body(s.AddItemSerializer)
        variant, quantity = data.get("variant"), data.get("quantity")
        if variant is None:
            found = resolve_code(request.account.id, data["code"])
            if found is None:
                raise BusinessError("Produto não encontrado para este código.", code="product_not_found")
            variant, quantity = found.variant, quantity or found.quantity
        parent = None
        if data.get("service_for"):
            parent = get_object_or_404(SaleItem.all_objects, pk=data["service_for"], sale=sale)
        seller = _seller(sale.store, data.get("seller"))
        with transaction.atomic():  # produto + serviços escolhidos: entra tudo ou nada
            item = sales.add_item(
                sale, variant, quantity or (parent.quantity if parent else Decimal("1")), request.user, seller=seller,
                discount=data["discount"], unit_price=data.get("unit_price"), approval=data.get("approval"),
                metafields=data.get("metafields"), parent_item=parent,
            )
            for service in data.get("services") or []:
                sales.add_item(sale, service, item.quantity, request.user, seller=seller, parent_item=item)
        return self._respond(sale, status=201)

    @action(detail=True, methods=["post", "delete"])
    def delivery(self, request, pk=None):
        """POST {"address", "table"}: entrega com frete. DELETE: retirada na loja."""
        sale = self.get_object()
        if request.method == "DELETE":
            sales.clear_delivery(sale, request.user)
            return self._respond(sale)
        address = get_object_or_404(CustomerAddress.all_objects, pk=request.data.get("address"),
                                    account=request.account, deleted_at__isnull=True)
        table = get_object_or_404(FreightTable.all_objects, pk=request.data.get("table"),
                                  account=request.account, deleted_at__isnull=True)
        sales.set_delivery(sale, request.user, address, table)
        return self._respond(sale)

    @action(detail=True, methods=["post"])
    def fulfillment(self, request, pk=None):
        """POST {"status": "ready"|"shipped"|"delivered", "note"}: anda (ou volta, com motivo) a entrega."""
        sales.advance_fulfillment(self.get_object(), request.user, str(request.data.get("status", "")),
                                  str(request.data.get("note", "")))
        return self._respond(self.get_object())

    @action(detail=True, methods=["post"], url_path="metafields")
    def set_metafields(self, request, pk=None):
        sales.set_metafields(self.get_object(), request.user, request.data.get("metafields"))
        return self._respond(self.get_object())

    @items.mapping.get
    def list_items(self, request, pk=None):
        return Response(s.SaleItemSerializer(self.get_object().items.all(), many=True).data)

    @action(detail=True, methods=["patch", "delete"], url_path=r"items/(?P<item_id>[^/.]+)")
    def item_detail(self, request, pk=None, item_id=None):
        sale = self.get_object()
        item = get_object_or_404(SaleItem.all_objects, pk=item_id, sale=sale)
        if request.method == "DELETE":
            data = self._body(s.ReasonSerializer)
            sales.cancel_item(item, request.user, data["reason"], data.get("approval"))
        else:
            data = self._body(s.UpdateItemSerializer)
            sales.update_item(item, request.user, quantity=data.get("quantity"), discount=data.get("discount"),
                              approval=data.get("approval"))
        return self._respond(sale)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def customer(self, request, pk=None):
        sale = sales.lock_open(self.get_object())
        data = self._body(s.SaleCustomerSerializer)
        for field in ("customer", "customer_document", "customer_name", "freight", "notes"):
            if field in data:
                setattr(sale, field, data[field])
        if data.get("customer") and not data.get("customer_document"):
            sale.customer_document, sale.customer_name = data["customer"].document, data["customer"].name
        if "seller" in data:
            sale.seller = _seller(sale.store, data["seller"])
        sale.save()
        sales.recalculate(sale)
        return self._respond(sale)

    @action(detail=True, methods=["post"])
    def discount(self, request, pk=None):
        sale = self.get_object()
        data = self._body(s.DiscountSerializer)
        amount = data.get("amount")
        if amount is None:
            amount = sales.cents(sale.subtotal * data.get("percent", Decimal("0")) / 100)
        sales.set_discount(sale, request.user, amount, data.get("approval"))
        return self._respond(sale)

    @action(detail=True, methods=["post", "delete"])
    def coupon(self, request, pk=None):
        sale = self.get_object()
        if request.method == "DELETE":
            sales.remove_coupon(sale)
        else:
            sales.apply_coupon(sale, self._body(s.CouponSerializer)["code"])
        return self._respond(sale)

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        sale = self.get_object()
        data = dict(self._body(s.PaymentInputSerializer))
        checkout.add_payment(sale, data.pop("method"), data.pop("amount"), request.user,
                             idempotency_key=request.headers.get("Idempotency-Key"), **data)
        return self._respond(sale, status=201)

    @action(detail=True, methods=["delete"], url_path=r"payments/(?P<payment_id>[^/.]+)")
    def payment_detail(self, request, pk=None, payment_id=None):
        sale = self.get_object()
        checkout.remove_payment(get_object_or_404(Payment.all_objects, pk=payment_id, sale=sale), request.user)
        return self._respond(sale)

    @action(detail=True, methods=["post"], url_path="checkout")
    def checkout_action(self, request, pk=None):
        sale = self.get_object()
        checkout.checkout(sale, request.user, self._body(s.CheckoutSerializer)["payments"])
        return self._respond(sale)

    @action(detail=True, methods=["post"])
    def park(self, request, pk=None):
        """Guarda o pedido (ou envia ao caixa): {"note": "cliente volta às 15h"}."""
        return self._respond(sales.park(self.get_object(), request.user, str(request.data.get("note", ""))[:255]))

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        """Retoma um pedido guardado, no turno de caixa de quem retomou."""
        sale = self.get_object()
        return self._respond(sales.resume(sale, request.user, session_for_user(sale.store, request.user)))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._respond(checkout.complete(self.get_object(), request.user))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        data = self._body(s.ReasonSerializer)
        return self._respond(checkout.cancel(self.get_object(), request.user, data["reason"], data.get("approval")))

    @action(detail=True, methods=["post"], url_path="returns")
    def returns(self, request, pk=None):
        data = self._body(ops.ReturnCreateSerializer)
        sale_return = returns.create(self.get_object(), request.user, data["items"],
                                     refund_method=data["refund_method"], reason=data["reason"],
                                     approval=data.get("approval"))
        return Response(ops.SaleReturnSerializer(sale_return).data, status=201)
