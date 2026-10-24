"""Promoções (preço de vitrine) e cupons (direito de uma pessoa).

Regras preservadas do StarChef:
- a tabela agrupa regras que começam e terminam juntas; a janela da tabela é o
  teto das regras; entre tabelas, a mais antiga vence;
- dentro da tabela, a posição é a prioridade (o topo ganha);
- o cupom nunca abate mais que a base, e o mínimo não conta frete.

O escopo de loja é SÓ da tabela (antes a regra e o vínculo carregavam um
`restaurant` herdado que podia divergir dela).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

from starrp.models.base import MoneyField, TenantModel, alive, optional_store_fk

CENTS = Decimal("0.01")


def to_cents(value):
    value = Decimal(value or 0).quantize(CENTS, rounding=ROUND_HALF_UP)
    return value if value > 0 else Decimal("0.00")


class ScheduledMixin(models.Model):
    """Interruptor manual + janela de validade. `is_active` é calculado: uma
    promoção que termina às 18h para às 18h, sem tarefa periódica."""

    is_enabled = models.BooleanField(default=True, db_index=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def _within_window(self):
        now = timezone.now()
        return not ((self.starts_at and now < self.starts_at) or (self.ends_at and now > self.ends_at))

    @property
    def is_active(self):
        return self.is_enabled and self.deleted_at is None and self._within_window()


class DiscountTable(ScheduledMixin, TenantModel):
    store_lookup = "store"
    store_shared_when_null = True

    store = optional_store_fk()
    name = models.CharField(max_length=140)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]  # a ordem É a prioridade entre tabelas
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_discount_table"),
        ]

    def __str__(self):
        return self.name


class Promotion(ScheduledMixin, TenantModel):
    store_lookup = "table__store"
    store_shared_when_null = True

    class Target(models.TextChoices):
        PRODUCTS = "products", "Produtos escolhidos"
        CATEGORIES = "categories", "Categorias"
        BRANDS = "brands", "Marcas"
        ALL = "all", "Todo o catálogo"

    class Kind(models.TextChoices):
        PERCENT = "percent", "Percentual sobre o preço"
        AMOUNT = "amount", "Valor abatido"
        FIXED = "fixed", "Preço fixo"

    table = models.ForeignKey(DiscountTable, related_name="rules", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    position = models.PositiveIntegerField(default=1)
    target = models.CharField(max_length=12, choices=Target.choices, default=Target.PRODUCTS)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PERCENT)
    value = MoneyField()
    products = models.ManyToManyField(
        "starrp.Product", through="starrp.PromotionProduct", related_name="promotions", blank=True
    )
    categories = models.ManyToManyField("starrp.Category", related_name="promotions", blank=True)
    brands = models.ManyToManyField("starrp.Brand", related_name="promotions", blank=True)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["table", "position"], condition=alive(), name="uniq_promotion_position"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return super().is_active and self.table.is_active

    def price_for(self, base, link=None):
        """Preço que esta regra cobra sobre `base`. O "por" digitado no
        vínculo vence o tipo de desconto. Nunca negativo."""
        base = Decimal(base or 0)
        if link is not None and link.promotional_price is not None:
            return to_cents(link.promotional_price)
        if self.kind == self.Kind.FIXED:
            return to_cents(self.value)
        if self.kind == self.Kind.AMOUNT:
            return to_cents(base - self.value)
        return to_cents(base * (Decimal(100) - self.value) / Decimal(100))


class PromotionProduct(TenantModel):
    """Vínculo regra ↔ produto com o "de/por" do encarte."""

    store_lookup = "promotion__table__store"
    store_shared_when_null = True

    promotion = models.ForeignKey(Promotion, related_name="product_links", on_delete=models.CASCADE)
    product = models.ForeignKey("starrp.Product", related_name="promotion_links", on_delete=models.CASCADE)
    promotional_price = MoneyField(null=True, blank=True, default=None, help_text='O "por".')
    compare_at_price = MoneyField(null=True, blank=True, default=None, help_text='O "de" exibido riscado.')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["promotion", "product"], condition=alive(), name="uniq_promotion_product"),
        ]


class Coupon(ScheduledMixin, TenantModel):
    store_lookup = "store"
    store_shared_when_null = True

    class Kind(models.TextChoices):
        PERCENT = "percent", "Percentual sobre o subtotal"
        AMOUNT = "amount", "Valor em reais"
        FREE_SHIPPING = "free_shipping", "Frete grátis"

    store = optional_store_fk()
    code = models.CharField(max_length=40, help_text="Guardado em MAIÚSCULAS.")
    name = models.CharField(max_length=140, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.PERCENT)
    value = MoneyField()
    max_discount = MoneyField(null=True, blank=True, default=None, help_text="Teto do percentual.")
    min_subtotal = MoneyField(help_text="Mínimo em produtos, sem frete.")
    usage_limit = models.PositiveIntegerField(default=0, help_text="0 = ilimitado.")
    usage_limit_per_customer = models.PositiveIntegerField(default=0, help_text="0 = ilimitado.")
    first_purchase_only = models.BooleanField(default=False)
    requires_document = models.BooleanField(default=False, help_text="Exige CPF/CNPJ na venda.")
    customer_groups = models.ManyToManyField("starrp.CustomerGroup", related_name="coupons", blank=True)
    customers = models.ManyToManyField("starrp.Customer", related_name="coupons", blank=True)
    channels = models.JSONField(default=list, blank=True, help_text="Canais de venda aceitos. Vazio = todos.")
    combines_with_promotions = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["account", "code"], condition=alive(), name="uniq_coupon")]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def discount_for(self, subtotal, freight=Decimal("0.00")):
        subtotal = Decimal(subtotal or 0)
        if self.kind == self.Kind.FREE_SHIPPING:
            return to_cents(freight)
        if self.kind == self.Kind.AMOUNT:
            return to_cents(min(self.value, subtotal))
        gross = subtotal * self.value / Decimal(100)
        if self.max_discount is not None:
            gross = min(gross, self.max_discount)
        return to_cents(min(gross, subtotal))


class CouponRedemption(TenantModel):
    """Prova de uso. Tabela (e não contador) porque "um por CPF" pergunta QUEM
    usou, e cancelar a venda devolve o direito apagando o resgate."""

    store_lookup = "sale__store"

    coupon = models.ForeignKey(Coupon, related_name="redemptions", on_delete=models.CASCADE)
    sale = models.ForeignKey("starrp.Sale", related_name="coupon_redemptions", on_delete=models.CASCADE)
    customer = models.ForeignKey(
        "starrp.Customer", null=True, blank=True, related_name="coupon_redemptions", on_delete=models.SET_NULL
    )
    document = models.CharField(max_length=18, blank=True, db_index=True)
    amount = MoneyField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["coupon", "sale"], condition=alive(), name="uniq_coupon_redemption"),
        ]
