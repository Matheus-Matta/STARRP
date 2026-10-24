"""Patrimônio: o bem individual (com série), onde ele está e a baixa.

O local do bem é um `Warehouse` (mesmo cadastro de locais do estoque).
`warranty_start_date` + `warranty_months` + `warranty_end_date` viraram só
`warranty_until`: as três podiam discordar.
"""
import secrets

from django.db import models

from starrp.models.base import MoneyField, StoreModel, TenantModel, alive, user_fk


def new_qr_token():
    return secrets.token_urlsafe(24)


class Asset(StoreModel):
    class Status(models.TextChoices):
        IN_STOCK = "in_stock", "Em estoque"
        IN_USE = "in_use", "Em uso"
        MAINTENANCE = "maintenance", "Em manutenção"
        LOANED = "loaned", "Emprestado"
        BROKEN = "broken", "Quebrado"
        DISPOSED = "disposed", "Baixado"
        LOST = "lost", "Extraviado"

    code = models.CharField(max_length=40, help_text="Código patrimonial impresso na plaqueta.")
    description = models.CharField(max_length=180)
    product = models.ForeignKey("starrp.Product", null=True, blank=True, related_name="assets", on_delete=models.PROTECT)
    serial_number = models.CharField(max_length=120, blank=True, db_index=True)
    brand = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=120, blank=True)
    supplier = models.ForeignKey("starrp.Supplier", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    inbound_nfe = models.ForeignKey(
        "starrp.InboundNFe", null=True, blank=True, related_name="assets", on_delete=models.SET_NULL
    )
    stock_document_item = models.ForeignKey(
        "starrp.StockDocumentItem", null=True, blank=True, related_name="assets", on_delete=models.SET_NULL
    )
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = MoneyField()
    location = models.ForeignKey("starrp.Warehouse", null=True, blank=True, related_name="assets", on_delete=models.PROTECT)
    responsible = user_fk("assets_responsible")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_STOCK, db_index=True)
    warranty_until = models.DateField(null=True, blank=True, db_index=True)
    warranty_provider = models.CharField(max_length=180, blank=True)
    installed_at = models.DateField(null=True, blank=True)
    useful_life_months = models.PositiveIntegerField(null=True, blank=True)
    qr_token = models.CharField(max_length=64, unique=True, default=new_qr_token, editable=False)
    # A nota de origem foi cancelada pelo fornecedor depois do recebimento.
    source_nfe_cancelled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["account", "code"], condition=alive(), name="uniq_asset_code")]

    def __str__(self):
        return f"{self.code} - {self.description}"


class AssetMovement(TenantModel):
    store_lookup = "asset__store"

    asset = models.ForeignKey(Asset, related_name="movements", on_delete=models.CASCADE)
    from_location = models.ForeignKey(
        "starrp.Warehouse", null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    to_location = models.ForeignKey("starrp.Warehouse", related_name="+", on_delete=models.PROTECT)
    moved_by = user_fk("+")
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]


class AssetDisposal(TenantModel):
    store_lookup = "asset__store"

    class Kind(models.TextChoices):
        SCRAPPED = "scrapped", "Sucateado"
        SOLD = "sold", "Vendido"
        DONATED = "donated", "Doado"
        LOST = "lost", "Extraviado"
        STOLEN = "stolen", "Roubado"
        OTHER = "other", "Outro"

    asset = models.OneToOneField(Asset, related_name="disposal", on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    sale_value = MoneyField()
    authorized_by = user_fk("+")
    reason = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
