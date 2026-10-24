"""Documento fiscal de saída (NFC-e/NF-e) e seus itens com a tributação por linha.

Aponta para a venda por FK: uma nota rejeitada/cancelada pode ser reemitida
(o OneToOne do StarChef impedia).
"""
from django.db import models
from django.db.models import Q

from starrp.models.base import MoneyField, PercentField, QuantityField, StoreModel, TenantModel
from starrp.models.fiscal import DocumentModel, Environment, FiscalSeries

class Invoice(StoreModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        PROCESSING = "processing", "Em processamento"
        AUTHORIZED = "authorized", "Autorizada"
        REJECTED = "rejected", "Rejeitada"
        CANCELLED = "cancelled", "Cancelada"
        ERROR = "error", "Erro de comunicação"

    class EmissionType(models.TextChoices):
        NORMAL = "1", "Normal"
        OFFLINE = "9", "Contingência offline"

    sale = models.ForeignKey("starrp.Sale", null=True, blank=True, related_name="invoices", on_delete=models.PROTECT)
    sale_return = models.ForeignKey(
        "starrp.SaleReturn", null=True, blank=True, related_name="invoices", on_delete=models.PROTECT
    )
    fiscal_config = models.ForeignKey(
        "starrp.FiscalConfig", null=True, blank=True, related_name="invoices", on_delete=models.PROTECT,
        help_text="Emitente (dados fiscais) da nota.",
    )
    series_ref = models.ForeignKey(FiscalSeries, null=True, blank=True, related_name="+", on_delete=models.PROTECT)
    document_model = models.CharField(max_length=2, choices=DocumentModel.choices, default=DocumentModel.NFCE)
    series = models.PositiveIntegerField(null=True, blank=True)
    number = models.PositiveIntegerField(null=True, blank=True)
    environment = models.CharField(max_length=1, choices=Environment.choices, default=Environment.HOMOLOGATION)
    emission_type = models.CharField(max_length=1, choices=EmissionType.choices, default=EmissionType.NORMAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    provider = models.CharField(max_length=20, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    access_key = models.CharField(max_length=44, blank=True, db_index=True)

    recipient_document = models.CharField(max_length=18, blank=True)
    recipient_name = models.CharField(max_length=180, blank=True)
    products_total = MoneyField()
    discount_total = MoneyField()
    freight_total = MoneyField()
    approx_tax_total = MoneyField()
    total = MoneyField()

    protocol = models.CharField(max_length=60, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    digest_value = models.CharField(max_length=64, blank=True)
    qr_code_data = models.TextField(blank=True)
    consult_url = models.URLField(blank=True)
    danfe_url = models.URLField(blank=True)
    xml = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True, help_text="Retrato do emitente e dos dados enviados.")
    error_message = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_protocol = models.CharField(max_length=60, blank=True)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "document_model", "series", "number"],
                condition=Q(number__isnull=False),
                name="uniq_invoice_number",
            ),
            # No máximo uma nota viva por venda e modelo.
            models.UniqueConstraint(
                fields=["sale", "document_model"],
                condition=Q(sale__isnull=False, status__in=["draft", "processing", "authorized"]),
                name="uniq_live_invoice_per_sale",
            ),
        ]

    def __str__(self):
        return f"{self.get_document_model_display()} {self.number or '-'}"


class InvoiceItem(TenantModel):
    store_lookup = "invoice__store"

    invoice = models.ForeignKey(Invoice, related_name="items", on_delete=models.CASCADE)
    sale_item = models.ForeignKey("starrp.SaleItem", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    variant = models.ForeignKey("starrp.ProductVariant", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    line_number = models.PositiveIntegerField(default=1)
    code = models.CharField(max_length=60, blank=True)
    barcode = models.CharField(max_length=32, blank=True)
    description = models.CharField(max_length=180)
    ncm = models.CharField(max_length=8, blank=True)
    cest = models.CharField(max_length=7, blank=True)
    cfop = models.CharField(max_length=4, blank=True)
    csosn = models.CharField(max_length=3, blank=True)
    cst_icms = models.CharField(max_length=2, blank=True)
    origin = models.CharField(max_length=1, default="0")
    unit = models.CharField(max_length=6, default="UN")
    quantity = QuantityField(default=1)
    unit_price = MoneyField()
    discount = MoneyField()
    total = MoneyField()
    icms_base = MoneyField()
    icms_rate = PercentField()
    icms_value = MoneyField()
    pis_cst = models.CharField(max_length=2, default="49")
    pis_rate = PercentField()
    pis_value = MoneyField()
    cofins_cst = models.CharField(max_length=2, default="49")
    cofins_rate = PercentField()
    cofins_value = MoneyField()
    approx_tax_value = MoneyField()

    class Meta:
        ordering = ["line_number"]
