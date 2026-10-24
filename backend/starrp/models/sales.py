"""Venda (PDV desktop, PDV móvel, retaguarda) e comissão de vendedor.

Quatro situações, como no pedido do StarHub:

- `status` — o documento no caixa: aberta → (guardada) → concluída | cancelada. "Concluída"
  aqui é "fechada e paga no caixa"; é ela que trava a venda (`lock_open`).
- `payment_status` — o dinheiro: aguardando, pago em parte, pago, estorno parcial,
  estornado, cancelado. Sai de `paid_amount`, `total` e `refunded_amount`.
- `fulfillment_status` — a mercadoria: pendente → separado → saiu para entrega → entregue,
  ou retirado na loja (venda de balcão), devolvido, cancelado.
- `overall_status` — o reflexo de tudo, até o produto chegar no cliente: em atendimento,
  aguardando separação, pronto para entrega, em rota, CONCLUÍDO (entregue ou retirado),
  cancelado, devolvido.

As três últimas são derivadas em `save()` (`derive_statuses`): nenhum fluxo esquece de
atualizar. A entrega avança pela ação `fulfillment` (`services/sales.advance_fulfillment`).
"""
from django.conf import settings
from django.db import models

from starrp.models.base import MoneyField, PercentField, QuantityField, StoreModel, TenantModel, UnitCostField, user_fk


class SaleChannel(models.TextChoices):
    POS = "pos", "PDV desktop"
    MOBILE = "mobile", "PDV móvel"
    BACKOFFICE = "backoffice", "Retaguarda"
    ECOMMERCE = "ecommerce", "Loja virtual"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Aguardando pagamento"
    PARTIAL = "partial", "Pago em parte"
    PAID = "paid", "Pago"
    PARTIALLY_REFUNDED = "partially_refunded", "Estorno parcial"
    REFUNDED = "refunded", "Estornado"
    CANCELLED = "cancelled", "Cancelado"


class FulfillmentStatus(models.TextChoices):
    PENDING = "pending", "Pendente"
    READY = "ready", "Separado"
    SHIPPED = "shipped", "Saiu para entrega"
    DELIVERED = "delivered", "Entregue"
    PICKED_UP = "picked_up", "Retirado na loja"
    RETURNED = "returned", "Devolvido"
    CANCELLED = "cancelled", "Cancelado"


class OverallStatus(models.TextChoices):
    DRAFT = "draft", "Pedido guardado"
    OPEN = "open", "Em atendimento"
    AWAITING_PAYMENT = "awaiting_payment", "Pagamento em andamento"
    AWAITING_PICKING = "awaiting_picking", "Aguardando separação"
    READY = "ready", "Pronto para entrega"
    IN_TRANSIT = "in_transit", "Em rota de entrega"
    COMPLETED = "completed", "Concluído"
    RETURNED = "returned", "Devolvido"
    CANCELLED = "cancelled", "Cancelado"


def derive_statuses(sale):
    """Pagamento, entrega e status geral a partir dos campos da venda (usada também na migração)."""
    total, paid, refunded = sale.total or 0, sale.paid_amount or 0, sale.refunded_amount or 0
    cancelled = sale.status == "cancelled"
    if refunded and refunded >= total:
        payment = PaymentStatus.REFUNDED
    elif refunded:
        payment = PaymentStatus.PARTIALLY_REFUNDED
    elif cancelled:
        payment = PaymentStatus.CANCELLED
    elif total and paid >= total:
        payment = PaymentStatus.PAID
    elif paid:
        payment = PaymentStatus.PARTIAL
    else:
        payment = PaymentStatus.PENDING

    fulfillment = sale.fulfillment_status or FulfillmentStatus.PENDING
    if cancelled:
        fulfillment = FulfillmentStatus.CANCELLED
    elif fulfillment != FulfillmentStatus.RETURNED:
        delivers = bool(sale.shipping_address_id)
        if not delivers and fulfillment != FulfillmentStatus.PICKED_UP:
            # Balcão: o cliente leva na hora em que a venda fecha.
            fulfillment = FulfillmentStatus.PICKED_UP if sale.status == "completed" else FulfillmentStatus.PENDING
        elif delivers and fulfillment == FulfillmentStatus.PICKED_UP:
            fulfillment = FulfillmentStatus.PENDING  # virou entrega

    if cancelled:
        overall = OverallStatus.CANCELLED
    elif fulfillment == FulfillmentStatus.RETURNED or payment == PaymentStatus.REFUNDED:
        overall = OverallStatus.RETURNED
    elif sale.status == "draft":
        overall = OverallStatus.DRAFT
    elif sale.status == "open":
        overall = OverallStatus.AWAITING_PAYMENT if paid else OverallStatus.OPEN
    else:
        overall = {
            FulfillmentStatus.PENDING: OverallStatus.AWAITING_PICKING,
            FulfillmentStatus.READY: OverallStatus.READY,
            FulfillmentStatus.SHIPPED: OverallStatus.IN_TRANSIT,
        }.get(fulfillment, OverallStatus.COMPLETED)
    return {"payment_status": payment, "fulfillment_status": fulfillment, "overall_status": overall}


class Sale(StoreModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        # Pedido guardado no PDV para terminar depois (ou enviado pelo vendedor ao caixa).
        DRAFT = "draft", "Pedido guardado"
        COMPLETED = "completed", "Concluída"
        CANCELLED = "cancelled", "Cancelada"

    number = models.PositiveIntegerField(help_text="Sequencial por loja.")
    channel = models.CharField(max_length=12, choices=SaleChannel.choices, default=SaleChannel.POS)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    terminal = models.ForeignKey(
        "starrp.Terminal", null=True, blank=True, related_name="sales", on_delete=models.SET_NULL
    )
    cash_session = models.ForeignKey(
        "starrp.CashSession", null=True, blank=True, related_name="sales", on_delete=models.PROTECT
    )
    operator = user_fk("sales_operated", help_text="Quem registrou (caixa).")
    parked_at = models.DateTimeField(null=True, blank=True, help_text="Quando o pedido foi guardado.")
    parked_by = user_fk("+", help_text="Quem guardou o pedido (vendedor ou caixa).")
    seller = user_fk("sales_sold", help_text="Vendedor que recebe a comissão.")

    customer = models.ForeignKey(
        "starrp.Customer", null=True, blank=True, related_name="sales", on_delete=models.SET_NULL
    )
    # CPF/CNPJ na nota: pode ser informado sem cadastrar o cliente.
    customer_document = models.CharField(max_length=18, blank=True)
    customer_name = models.CharField(max_length=180, blank=True)
    shipping_address = models.ForeignKey(
        "starrp.CustomerAddress", null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )

    subtotal = MoneyField(help_text="Soma dos itens ativos, já com promoção e desconto de item.")
    discount = MoneyField(help_text="Desconto manual no total.")
    discount_approved_by = user_fk("+")
    coupon = models.ForeignKey("starrp.Coupon", null=True, blank=True, related_name="sales", on_delete=models.SET_NULL)
    # O código fica mesmo que o cupom seja apagado: explica o total.
    coupon_code = models.CharField(max_length=40, blank=True)
    coupon_discount = MoneyField()
    freight = MoneyField()
    total = MoneyField()
    paid_amount = MoneyField()
    change_amount = MoneyField()

    notes = models.TextField(blank=True)
    metafields = models.JSONField(default=dict, blank=True)

    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
                                      db_index=True)
    refunded_amount = MoneyField(help_text="Devolvido ao cliente (devoluções concluídas).")
    fulfillment_status = models.CharField(max_length=12, choices=FulfillmentStatus.choices,
                                          default=FulfillmentStatus.PENDING, db_index=True)
    overall_status = models.CharField(max_length=20, choices=OverallStatus.choices, default=OverallStatus.OPEN,
                                      db_index=True)
    # Etapas da entrega (viram "Separado · Ana", "Saiu para entrega", "Entregue" no histórico).
    ready_at = models.DateTimeField(null=True, blank=True)
    ready_by = user_fk("+")
    shipped_at = models.DateTimeField(null=True, blank=True)
    shipped_by = user_fk("+")
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivered_by = user_fk("+")
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = user_fk("+")
    cancel_approved_by = user_fk("+")
    cancel_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["store", "number"], name="uniq_sale_number"),
        ]
        indexes = [
            models.Index(fields=["store", "status", "created_at"]),
            models.Index(fields=["account", "completed_at"]),
        ]

    def __str__(self):
        return f"Venda {self.number}"

    def save(self, *args, **kwargs):
        derived = derive_statuses(self)
        changed = [f for f, v in derived.items() if getattr(self, f) != v]
        for field, value in derived.items():
            setattr(self, field, value)
        fields = kwargs.get("update_fields")
        if fields is not None and changed:
            kwargs["update_fields"] = list({*fields, *changed})
        super().save(*args, **kwargs)

    @property
    def is_locked(self):
        return self.status != self.Status.OPEN

    @property
    def balance_due(self):
        return max(self.total - self.paid_amount, 0)


class SaleItem(TenantModel):
    store_lookup = "sale__store"

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        CANCELLED = "cancelled", "Cancelado"

    sale = models.ForeignKey(Sale, related_name="items", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=1)
    variant = models.ForeignKey("starrp.ProductVariant", related_name="sale_items", on_delete=models.PROTECT)
    # Retrato no momento da venda: renomear o produto não reescreve a venda.
    description = models.CharField(max_length=255)
    sku = models.CharField(max_length=60, blank=True)
    unit = models.CharField(max_length=6, default="UN")
    quantity = QuantityField(default=1)
    list_price = MoneyField(help_text="Preço cheio cadastrado.")
    unit_price = MoneyField(help_text="Preço cobrado (após promoção).")
    discount = MoneyField(help_text="Desconto manual da linha.")
    total = MoneyField()
    unit_cost = UnitCostField(help_text="Custo médio no momento da venda (margem).")
    promotion = models.ForeignKey(
        "starrp.Promotion", null=True, blank=True, related_name="sale_items", on_delete=models.SET_NULL
    )
    seller = user_fk("sale_items_sold", help_text="Vazio = vendedor da venda.")
    # Serviço vendido junto com um item (montagem do guarda-roupa da linha 2).
    parent_item = models.ForeignKey("self", null=True, blank=True, related_name="services", on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = user_fk("+")
    cancel_reason = models.CharField(max_length=255, blank=True)
    metafields = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["position"]
        indexes = [models.Index(fields=["sale", "status"])]

    def __str__(self):
        return f"{self.quantity} x {self.description}"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


class Commission(StoreModel):
    """Comissão gerada na conclusão da venda; estorno vira linha negativa."""

    class Status(models.TextChoices):
        PENDING = "pending", "A pagar"
        PAID = "paid", "Paga"
        CANCELLED = "cancelled", "Cancelada"

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="commissions", on_delete=models.PROTECT)
    sale = models.ForeignKey(Sale, related_name="commissions", on_delete=models.CASCADE)
    sale_item = models.ForeignKey(SaleItem, null=True, blank=True, related_name="commissions", on_delete=models.CASCADE)
    sale_return = models.ForeignKey(
        "starrp.SaleReturn", null=True, blank=True, related_name="commissions", on_delete=models.CASCADE
    )
    base_amount = MoneyField()
    rate = PercentField()
    amount = MoneyField(help_text="Negativo quando estorno de devolução.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["seller", "status", "created_at"])]
