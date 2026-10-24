"""Fiscal de saída: perfil tributário, configuração da loja, numeração e notas.

Mudanças em relação ao StarChef:
- `FiscalConfig` são os "Dados fiscais" do emitente (CNPJ, IE, regime, endereço,
  certificado), cadastro próprio da conta: uma ou mais lojas apontam para ele
  (`Store.fiscal_config`). O mesmo CNPJ serve a emissão e a busca de notas de
  entrada na SEFAZ (DF-e);
- numeração em `FiscalSeries` (uma linha por modelo + série + origem), no lugar
  de `series`/`next_number`/`cloud_series`/`cloud_next_number` soltos — a loja
  emite NFC-e no PDV e NF-e para empresa, e a nuvem usa série própria;
- `certificate_ref` e `provider_token` saíram (duplicavam arquivo e tokens);
- `Invoice` aponta para a venda por FK: uma nota rejeitada/cancelada pode ser
  reemitida, o que o OneToOne antigo impedia.
"""
from django.core.exceptions import ValidationError
from django.db import models

from starrp.models.base import PercentField, TenantModel, alive
from starrp.models.company import AddressFields


class DocumentModel(models.TextChoices):
    NFCE = "65", "NFC-e (modelo 65)"
    NFE = "55", "NF-e (modelo 55)"


class Environment(models.TextChoices):
    PRODUCTION = "1", "Produção"
    HOMOLOGATION = "2", "Homologação"


class FiscalProfile(TenantModel):
    """Regra de tributação reutilizável (o NCM é do produto). A conta cria os seus; os
    pré-prontos (`is_system`, `services/system_data.FISCAL_PROFILES`) não são excluídos."""

    name = models.CharField(max_length=120)
    is_system = models.BooleanField(default=False, help_text="Pré-pronto do sistema: ajusta, mas não exclui.")
    cfop = models.CharField(max_length=4, default="5102")
    cfop_interstate = models.CharField(max_length=4, blank=True, help_text="CFOP para outra UF (ex.: 6102).")
    csosn = models.CharField(max_length=3, blank=True, help_text="Simples Nacional (ex.: 102).")
    cst_icms = models.CharField(max_length=2, blank=True, help_text="Regime normal.")
    icms_rate = PercentField()
    pis_cst = models.CharField(max_length=2, default="49")
    pis_rate = PercentField()
    cofins_cst = models.CharField(max_length=2, default="49")
    cofins_rate = PercentField()
    approx_tax_rate = PercentField(help_text="Tributos aproximados (Lei 12.741) em %.")
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_fiscal_profile"),
        ]

    def __str__(self):
        return self.name


class FiscalConfig(AddressFields, TenantModel):
    """Dados fiscais de um emitente (um CNPJ). As lojas se vinculam a ele."""

    class Provider(models.TextChoices):
        MANUAL = "manual", "Manual (sem transmissão)"
        FOCUS_NFE = "focus_nfe", "Focus NFe"
        ACBRLIB = "acbrlib", "ACBrLib (comunicador próprio)"

    class Crt(models.TextChoices):
        SIMPLES = "1", "Simples Nacional"
        SIMPLES_EXCESS = "2", "Simples Nacional - excesso de sublimite"
        NORMAL = "3", "Regime Normal"

    class ProviderSync(models.TextChoices):
        NOT_CONFIGURED = "not_configured", "Não configurado"
        PENDING = "pending", "Aguardando"
        SYNCED = "synced", "Sincronizado"
        ERROR = "error", "Erro"

    name = models.CharField(max_length=120, help_text="Como aparece nas listas (ex.: Matriz).")
    legal_name = models.CharField(max_length=180, help_text="Razão social.")
    trade_name = models.CharField(max_length=160, blank=True, help_text="Nome fantasia.")
    cnpj = models.CharField(max_length=18)
    state_registration = models.CharField(max_length=20, blank=True, help_text="Inscrição estadual (IE).")
    municipal_registration = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)

    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MANUAL)
    environment = models.CharField(max_length=1, choices=Environment.choices, default=Environment.HOMOLOGATION)
    crt = models.CharField(max_length=1, choices=Crt.choices, default=Crt.SIMPLES)
    default_profile = models.ForeignKey(
        FiscalProfile, null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    strict_fiscal_profile = models.BooleanField(default=False, help_text="Recusa item com perfil incompleto.")
    # Contingência offline da NFC-e (tpEmis=9). Documento emitido não se apaga.
    offline_contingency = models.BooleanField(default=False)
    # Emissão no próprio terminal: exige `Account.local_fiscal_allowed`.
    local_fiscal_enabled = models.BooleanField(default=False)
    local_fiscal_contingency = models.BooleanField(default=False)
    local_fiscal_url = models.CharField(max_length=255, blank=True)

    csc_id = models.CharField(max_length=6, blank=True)
    csc_token = models.CharField(max_length=64, blank=True)
    qr_base_url = models.URLField(blank=True)
    portal_url = models.URLField(blank=True)
    certificate_file = models.FileField(upload_to="certificates/", null=True, blank=True)
    certificate_password = models.CharField(max_length=255, blank=True)
    certificate_valid_until = models.DateTimeField(null=True, blank=True)
    certificate_cnpj = models.CharField(max_length=18, blank=True)
    certificate_name = models.CharField(max_length=255, blank=True)

    # Provedor externo (Focus NFe): cadastro da empresa lá e seus tokens.
    provider_company_id = models.CharField(max_length=80, blank=True)
    provider_token_production = models.CharField(max_length=255, blank=True)
    provider_token_homologation = models.CharField(max_length=255, blank=True)
    provider_sync_status = models.CharField(
        max_length=20, choices=ProviderSync.choices, default=ProviderSync.NOT_CONFIGURED
    )
    provider_sync_error = models.TextField(blank=True)
    provider_synced_at = models.DateTimeField(null=True, blank=True)
    provider_data = models.JSONField(default=dict, blank=True)

    # Notas de entrada (DF-e): o que a SEFAZ tem emitido contra este CNPJ.
    dfe_enabled = models.BooleanField(default=True, help_text="Busca na SEFAZ as notas emitidas para este CNPJ.")
    dfe_auto_science = models.BooleanField(
        default=True, help_text="Dá ciência da operação sozinho para baixar o XML com os itens.")
    dfe_auto_entry = models.BooleanField(
        default=True, help_text="Nota com todos os itens vinculados já vira entrada de estoque (rascunho).")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "cnpj"], condition=alive(), name="uniq_fiscal_config_cnpj"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.local_fiscal_contingency and not self.local_fiscal_enabled:
            errors["local_fiscal_contingency"] = "Contingência local exige a emissão local ligada."
        if self.local_fiscal_enabled and not getattr(self.account, "local_fiscal_allowed", False):
            errors["local_fiscal_enabled"] = "A conta não está autorizada a emitir no terminal."
        if self.local_fiscal_enabled and self.provider == self.Provider.MANUAL:
            errors["local_fiscal_enabled"] = "O provedor Manual não transmite nada."
        if errors:
            raise ValidationError(errors)

    @property
    def is_ready(self):
        if self.provider == self.Provider.FOCUS_NFE:
            token = (
                self.provider_token_production
                if self.environment == Environment.PRODUCTION
                else self.provider_token_homologation
            )
            return bool(self.cnpj and self.state and token)
        return bool(self.cnpj and self.state and self.csc_token and self.certificate_file)


class FiscalSeries(TenantModel):
    """Um contador de numeração. Loja e nuvem nunca dividem série: offline,
    as duas repetiriam número na SEFAZ."""

    class Origin(models.TextChoices):
        STORE = "store", "Loja / terminal"
        CLOUD = "cloud", "Nuvem"

    config = models.ForeignKey(FiscalConfig, related_name="series", on_delete=models.CASCADE)
    document_model = models.CharField(max_length=2, choices=DocumentModel.choices, default=DocumentModel.NFCE)
    series = models.PositiveIntegerField(default=1)
    origin = models.CharField(max_length=5, choices=Origin.choices, default=Origin.STORE)
    next_number = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["config", "document_model", "series"], condition=alive(), name="uniq_fiscal_series"
            ),
        ]

    def __str__(self):
        return f"{self.get_document_model_display()} série {self.series} ({self.origin})"
