"""Entrega: tabelas de frete (padrão do StarHub) e o cache de CEP → coordenada / distância.

A tabela é UMA forma de cobrar o frete:
- por distância (km por estrada a partir do CEP de origem): taxa fixa + km × preço,
  nunca abaixo do mínimo, sem entrega acima da distância máxima;
- por faixa de CEP: o valor (e o prazo) da faixa que contém o CEP — havendo mais de
  uma, a mais estreita (a mais específica).
Cotação em `services/freight.py`.
"""
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q

from starrp.models.base import MoneyField, TenantModel, alive, optional_store_fk

ZIP = RegexValidator(r"^\d{8}$", "Informe o CEP com 8 dígitos, por exemplo 01001-000.")


class FreightTable(TenantModel):
    store_lookup = "store"
    store_shared_when_null = True

    class Kind(models.TextChoices):
        DISTANCE = "distance", "Por distância (km)"
        ZIP_RANGE = "zip_range", "Por faixa de CEP"

    store = optional_store_fk("freight_tables")
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.ZIP_RANGE)
    lead_days = models.PositiveSmallIntegerField(
        default=0, help_text="Prazo em dias úteis. Por faixa: vale para a faixa sem prazo próprio.")
    # Por distância.
    origin_zip = models.CharField(max_length=8, blank=True, validators=[ZIP], help_text="De onde a entrega sai.")
    price_per_km = MoneyField(null=True, blank=True, default=None)
    fixed_fee = MoneyField(help_text="Somada a toda entrega, além do valor por km.")
    min_value = MoneyField(help_text="Entrega perto nunca sai por menos que isto.")
    max_distance_km = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True,
                                          help_text="Acima disto não entrega. Vazio = sem limite.")
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        constraints = [models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_freight_table")]

    def __str__(self):
        return self.name


class FreightZipRange(TenantModel):
    table = models.ForeignKey(FreightTable, related_name="ranges", on_delete=models.CASCADE)
    zip_start = models.CharField(max_length=8, validators=[ZIP])
    zip_end = models.CharField(max_length=8, validators=[ZIP])
    value = MoneyField()
    lead_days = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Vazio = prazo da tabela.")
    label = models.CharField(max_length=80, blank=True, help_text='Ex.: "Zona Sul", "Grande SP".')

    class Meta:
        ordering = ["zip_start"]
        constraints = [
            # CEP de 8 dígitos ordena como texto igual a como número.
            models.CheckConstraint(condition=Q(zip_start__lte=F("zip_end")), name="freight_zip_start_lte_end"),
        ]

    def __str__(self):
        return f"{self.zip_start} a {self.zip_end}"


class ZipCoordinate(models.Model):
    """Latitude/longitude de um CEP, consultada uma vez só (as APIs gratuitas têm limite).
    Dado público, igual para todas as contas."""

    zip_code = models.CharField(max_length=8, unique=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    source = models.CharField(max_length=30)
    fetched_at = models.DateTimeField(auto_now=True)


class ZipDistance(models.Model):
    """Km por estrada entre dois CEPs (rota OSRM). Estimativa em linha reta não é guardada:
    a próxima cotação tenta a rota de novo."""

    origin = models.CharField(max_length=8)
    destination = models.CharField(max_length=8)
    km = models.DecimalField(max_digits=8, decimal_places=1)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["origin", "destination"], name="uniq_zip_distance")]
