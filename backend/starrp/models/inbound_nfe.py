"""NF-e de entrada: distribuição DF-e da SEFAZ, manifestação e conferência.

Simplificações em relação ao StarChef:
- o `status` de fluxo da nota era derivável de quatro outros status
  (xml/fiscal/manifestação/recebimento) e saiu: vira a propriedade `stage`;
- `NFeEvent` e `NFeManifestation` viraram um só `NFeEvent`, com direção
  (recebido da SEFAZ ou enviado por nós);
- o item mapeia só para `Product` (não há mais `Ingredient`), e o vínculo
  com o estoque é o `StockDocumentItem.nfe_item`;
- a configuração global de cooldown vai para `SystemSetting("dfe")`;
- o cursor da distribuição (NSU) é por CNPJ, isto é, por `FiscalConfig`
  ("Dados fiscais"), não por loja: a nota cai na loja vinculada a esse CNPJ.
"""
from django.db import models

from starrp.models.base import MoneyField, QuantityField, StoreModel, TenantModel, UnitCostField, alive, user_fk
from starrp.models.fiscal import Environment


class DFeSyncState(TenantModel):
    """Cursor da distribuição DF-e por CNPJ (dados fiscais) e ambiente."""

    config = models.ForeignKey("starrp.FiscalConfig", related_name="dfe_states", on_delete=models.CASCADE)
    environment = models.CharField(max_length=1, choices=Environment.choices, default=Environment.PRODUCTION)
    last_nsu = models.CharField(max_length=15, default="0")
    max_nsu = models.CharField(max_length=15, default="0")
    last_cstat = models.CharField(max_length=3, blank=True)
    last_reason = models.TextField(blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_allowed_at = models.DateTimeField(null=True, blank=True, help_text="Cooldown exigido pela SEFAZ.")
    is_syncing = models.BooleanField(default=False)
    error_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["config", "environment"], condition=alive(), name="uniq_dfe_state"),
        ]


class DFeDocument(TenantModel):
    """Documento bruto recebido na distribuição (resumo, nota ou evento)."""

    config = models.ForeignKey("starrp.FiscalConfig", related_name="dfe_documents", on_delete=models.CASCADE)
    class DocType(models.TextChoices):
        RES_NFE = "resNFe", "Resumo de NF-e"
        PROC_NFE = "procNFe", "NF-e completa"
        RES_EVENT = "resEvento", "Resumo de evento"
        PROC_EVENT = "procEventoNFe", "Evento"
        UNKNOWN = "unknown", "Desconhecido"

    class Processing(models.TextChoices):
        PENDING = "pending", "Pendente"
        OK = "ok", "Processado"
        ERROR = "error", "Erro"
        SKIPPED = "skipped", "Ignorado"

    nsu = models.CharField(max_length=15)
    schema = models.CharField(max_length=60, blank=True)
    access_key = models.CharField(max_length=44, blank=True, db_index=True)
    doc_type = models.CharField(max_length=16, choices=DocType.choices, default=DocType.UNKNOWN)
    xml = models.TextField()
    processing = models.CharField(max_length=10, choices=Processing.choices, default=Processing.PENDING)
    processing_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-nsu"]
        constraints = [models.UniqueConstraint(fields=["config", "nsu"], name="uniq_dfe_document_nsu")]


class InboundNFe(StoreModel):
    class XmlStatus(models.TextChoices):
        SUMMARY_ONLY = "summary_only", "Só resumo"
        PENDING = "pending", "XML completo pendente"
        AVAILABLE = "available", "XML completo disponível"
        ERROR = "error", "Erro ao obter XML"

    class FiscalStatus(models.TextChoices):
        UNKNOWN = "unknown", "Desconhecida"
        AUTHORIZED = "authorized", "Autorizada"
        CANCELLED = "cancelled", "Cancelada"
        DENIED = "denied", "Denegada"

    class Manifestation(models.TextChoices):
        NONE = "none", "Sem manifestação"
        SCIENCE = "science", "Ciência da operação"
        CONFIRMED = "confirmed", "Operação confirmada"
        UNKNOWN = "unknown", "Desconhecimento"
        NOT_PERFORMED = "not_performed", "Operação não realizada"
        ERROR = "error", "Erro na manifestação"

    class Receiving(models.TextChoices):
        NOT_STARTED = "not_started", "Não iniciado"
        PARTIAL = "partial", "Parcial"
        RECEIVED = "received", "Recebido"
        DIVERGENT = "divergent", "Recebido com divergência"

    access_key = models.CharField(max_length=44)
    fiscal_config = models.ForeignKey(
        "starrp.FiscalConfig", null=True, blank=True, related_name="inbound_nfes", on_delete=models.SET_NULL,
        help_text="CNPJ (dados fiscais) que recebeu a nota.",
    )
    nsu = models.CharField(max_length=15, blank=True)
    number = models.CharField(max_length=9, blank=True)
    series = models.CharField(max_length=3, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    supplier = models.ForeignKey(
        "starrp.Supplier", null=True, blank=True, related_name="inbound_nfes", on_delete=models.SET_NULL
    )
    supplier_document = models.CharField(max_length=14, blank=True)
    supplier_name = models.CharField(max_length=180, blank=True)
    recipient_document = models.CharField(max_length=14, blank=True, help_text="CNPJ/CPF do destinatário.")
    products_total = MoneyField()
    total = MoneyField()
    # Duplicatas da nota (`cobr/dup`): viram contas a pagar no recebimento.
    installments = models.JSONField(default=list, blank=True)

    xml_status = models.CharField(max_length=14, choices=XmlStatus.choices, default=XmlStatus.SUMMARY_ONLY)
    fiscal_status = models.CharField(max_length=12, choices=FiscalStatus.choices, default=FiscalStatus.UNKNOWN)
    manifestation = models.CharField(max_length=14, choices=Manifestation.choices, default=Manifestation.NONE)
    receiving = models.CharField(max_length=12, choices=Receiving.choices, default=Receiving.NOT_STARTED)
    summary_xml = models.TextField(blank=True)
    full_xml = models.TextField(blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_protocol = models.CharField(max_length=60, blank=True)
    cancellation_reason = models.TextField(blank=True)
    last_status_check_at = models.DateTimeField(null=True, blank=True)
    last_status_cstat = models.CharField(max_length=3, blank=True)
    last_status_reason = models.TextField(blank=True)
    ignored_at = models.DateTimeField(null=True, blank=True)
    ignored_by = user_fk("+")
    ignored_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(fields=["account", "access_key"], condition=alive(), name="uniq_inbound_nfe"),
        ]
        indexes = [models.Index(fields=["store", "receiving", "fiscal_status"])]

    def __str__(self):
        return f"NF-e {self.number} - {self.supplier_name}"

    @property
    def stage(self):
        """Etapa do fluxo, derivada (antes era uma coluna que divergia)."""
        if self.ignored_at:
            return "ignored"
        if self.fiscal_status == self.FiscalStatus.CANCELLED:
            return "cancelled"
        if self.receiving in (self.Receiving.RECEIVED, self.Receiving.DIVERGENT):
            return "received"
        if self.xml_status != self.XmlStatus.AVAILABLE:
            return "summary"
        if any(i.variant_id is None and not i.ignored for i in self.items.all()):
            return "pending_mapping"
        if any(d.status == "draft" and d.deleted_at is None for d in self.stock_documents.all()):
            return "checking"
        return "pending_receipt"


class InboundNFeItem(TenantModel):
    store_lookup = "nfe__store"

    nfe = models.ForeignKey(InboundNFe, related_name="items", on_delete=models.CASCADE)
    item_number = models.PositiveIntegerField()
    supplier_code = models.CharField(max_length=60, blank=True)
    barcode = models.CharField(max_length=32, blank=True)
    taxable_barcode = models.CharField(max_length=32, blank=True)
    description = models.CharField(max_length=255)
    ncm = models.CharField(max_length=8, blank=True)
    cest = models.CharField(max_length=7, blank=True)
    cfop = models.CharField(max_length=4, blank=True)
    unit = models.CharField(max_length=6, blank=True)
    quantity = QuantityField(max_digits=18, decimal_places=4)
    unit_value = UnitCostField(max_digits=21, decimal_places=10)
    taxable_unit = models.CharField(max_length=6, blank=True)
    taxable_quantity = QuantityField(max_digits=18, decimal_places=4)
    taxable_unit_value = UnitCostField(max_digits=21, decimal_places=10)
    total = MoneyField()
    discount = MoneyField()
    freight = MoneyField()
    insurance = MoneyField()
    other_expenses = MoneyField()
    tax_data = models.JSONField(default=dict, blank=True)
    # Rastreabilidade da nota (`rastro`): [{"number", "quantity", "manufactured_at", "expires_at"}].
    lots = models.JSONField(default=list, blank=True)
    variant = models.ForeignKey(
        "starrp.ProductVariant", null=True, blank=True, related_name="inbound_nfe_items", on_delete=models.SET_NULL
    )
    conversion_factor = QuantityField(max_digits=14, decimal_places=6, default=1)
    ignored = models.BooleanField(default=False)
    ignored_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["item_number"]
        constraints = [
            models.UniqueConstraint(fields=["nfe", "item_number"], condition=alive(), name="uniq_nfe_item_number"),
        ]
