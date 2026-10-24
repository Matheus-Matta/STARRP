"""Formas de pagamento e pagamentos da venda.

Débito e crédito passam a ser formas distintas (antes era `card` + um
`card_subtype` obrigatório só às vezes). Cada forma carrega o código `tPag`
da NFC-e e diz se gera título no financeiro (crediário, boleto, cartão D+30).
"""
from django.db import models

from starrp.models.base import MoneyField, PercentField, StoreModel, TenantModel, alive, optional_store_fk


class PaymentMethod(TenantModel):
    store_lookup = "store"
    store_shared_when_null = True

    class Kind(models.TextChoices):
        CASH = "cash", "Dinheiro"
        CREDIT_CARD = "credit_card", "Cartão de crédito"
        DEBIT_CARD = "debit_card", "Cartão de débito"
        PIX = "pix", "PIX"
        VOUCHER = "voucher", "Vale-alimentação/refeição"
        STORE_CREDIT = "store_credit", "Vale-troca"
        INSTALLMENT_PLAN = "installment_plan", "Crediário"
        BANK_SLIP = "bank_slip", "Boleto"
        OTHER = "other", "Outro"

    # Código do meio de pagamento na NFC-e/NF-e (tag tPag).
    FISCAL_CODES = {
        Kind.CASH: "01", Kind.CREDIT_CARD: "03", Kind.DEBIT_CARD: "04", Kind.STORE_CREDIT: "05",
        Kind.VOUCHER: "10", Kind.BANK_SLIP: "15", Kind.PIX: "17", Kind.INSTALLMENT_PLAN: "05", Kind.OTHER: "99",
    }

    store = optional_store_fk()
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    requires_reference = models.BooleanField(default=False, help_text="Pede NSU/autorização/txid.")
    max_installments = models.PositiveSmallIntegerField(default=1)
    fee_percent = PercentField(help_text="Taxa da adquirente, lançada no financeiro.")
    settlement_days = models.PositiveSmallIntegerField(default=0, help_text="Dias até o dinheiro cair (D+N).")
    opens_drawer = models.BooleanField(default=False)
    financial_account = models.ForeignKey(
        "starrp.FinancialAccount", null=True, blank=True, related_name="payment_methods", on_delete=models.SET_NULL
    )
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_payment_method"),
        ]

    def __str__(self):
        return self.name

    @property
    def fiscal_code(self):
        return self.FISCAL_CODES.get(self.kind, "99")

    @property
    def allows_change(self):
        return self.kind == self.Kind.CASH

    @property
    def generates_receivable(self):
        return self.kind in {self.Kind.INSTALLMENT_PLAN, self.Kind.BANK_SLIP} or self.settlement_days > 0


class Payment(StoreModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando (TEF/PIX)"
        APPROVED = "approved", "Aprovado"
        CANCELLED = "cancelled", "Cancelado"
        REFUNDED = "refunded", "Estornado"

    sale = models.ForeignKey("starrp.Sale", related_name="payments", on_delete=models.PROTECT)
    method = models.ForeignKey(PaymentMethod, related_name="payments", on_delete=models.PROTECT)
    cash_session = models.ForeignKey(
        "starrp.CashSession", null=True, blank=True, related_name="payments", on_delete=models.PROTECT
    )
    amount = MoneyField(help_text="Valor que abate a venda (sem o troco).")
    tendered_amount = MoneyField(help_text="Valor entregue pelo cliente (dinheiro).")
    change_amount = MoneyField()
    installments = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.APPROVED, db_index=True)
    card_brand = models.CharField(max_length=30, blank=True)
    authorization_code = models.CharField(max_length=40, blank=True)
    nsu = models.CharField(max_length=40, blank=True)
    reference = models.CharField(max_length=120, blank=True, help_text="txid do PIX ou outra referência.")
    idempotency_key = models.CharField(max_length=120, null=True, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_payment_idempotency",
            ),
        ]
        indexes = [models.Index(fields=["store", "paid_at"]), models.Index(fields=["sale", "status"])]

    def __str__(self):
        return f"{self.method} {self.amount}"
