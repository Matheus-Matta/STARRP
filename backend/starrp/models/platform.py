"""Plataforma SaaS: planos, contas (tenants), assinatura e integrações.

Antes, a assinatura vivia em dois lugares (`Account.plan`/`subscription_status`
e `Subscription`), e cada integração externa tinha a sua tabela
(`FocusNfeConfig`, `CosmosConfig`). Aqui: o plano e o status moram só na
assinatura, e toda integração é uma linha de `Integration`.
"""
from django.db import models

from starrp.models.base import MoneyField, TimeStampedModel

MODULE_BASE = "base"


class Module(models.TextChoices):
    BASE = MODULE_BASE, "Base (PDV, vendas, produtos, clientes)"
    STOCK = "stock", "Estoque e compras"
    FINANCE = "finance", "Financeiro"
    FISCAL = "fiscal", "Fiscal (NFC-e/NF-e)"
    INBOUND_NFE = "inbound_nfe", "NF-e de entrada (DF-e)"
    ASSETS = "assets", "Patrimônio"
    SYNC = "sync", "Servidor local (loja offline)"


class Plan(TimeStampedModel):
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    monthly_price = MoneyField()
    # 0 = ilimitado em todos os limites.
    max_stores = models.PositiveIntegerField(default=1)
    max_users = models.PositiveIntegerField(default=5)
    max_terminals = models.PositiveIntegerField(default=2)
    modules = models.JSONField(default=list, blank=True, help_text="Módulos opcionais incluídos no plano.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Account(TimeStampedModel):
    """A empresa cliente da plataforma. Tudo de negócio pertence a uma conta."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        SUSPENDED = "suspended", "Suspensa"
        CANCELED = "canceled", "Cancelada"

    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    document = models.CharField(max_length=18, blank=True, help_text="CNPJ/CPF do titular da conta.")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    timezone = models.CharField(max_length=50, default="America/Sao_Paulo")
    currency = models.CharField(max_length=3, default="BRL")
    # Módulos extras liberados além dos do plano (cortesia, piloto).
    extra_modules = models.JSONField(default=list, blank=True)
    # Logo da empresa: quadrado 1080×1080 (o envio já ajusta). Vai no canto das impressões.
    logo = models.ForeignKey("starrp.Image", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    # Trava de cima da emissão fiscal no terminal; a de baixo é por loja
    # (`FiscalConfig.local_fiscal_enabled`). Documento fiscal emitido não se
    # apaga — ligar por engano custa nota real no CNPJ do cliente.
    local_fiscal_allowed = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def active_modules(self):
        plan_modules = []
        subscription = getattr(self, "subscription", None)
        if subscription is not None and subscription.plan_id:
            plan_modules = subscription.plan.modules or []
        return {MODULE_BASE, *plan_modules, *(self.extra_modules or [])}

    def has_module(self, module):
        return module in self.active_modules()


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "trial", "Teste"
        ACTIVE = "active", "Ativa"
        PAST_DUE = "past_due", "Em atraso"
        CANCELED = "canceled", "Cancelada"

    account = models.OneToOneField(Account, related_name="subscription", on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan, related_name="subscriptions", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.account} - {self.plan}"


class SystemSetting(TimeStampedModel):
    """Configuração global da plataforma (chave -> JSON).

    Substitui `GlobalSystemConfig` e o singleton `DFeGlobalConfig`.
    """

    key = models.SlugField(max_length=120, unique=True)
    value = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.key


class Integration(TimeStampedModel):
    """Credenciais de um serviço externo para uma conta.

    `credentials` guarda segredos (nunca vão para a API em claro); `settings`
    guarda parâmetros (URL, timeout). Chaves esperadas por provedor ficam em
    `starrp.services.integrations`.
    """

    class Provider(models.TextChoices):
        FOCUS_NFE = "focus_nfe", "Focus NFe"
        COSMOS = "cosmos", "Bluesoft Cosmos (catálogo GTIN)"

    account = models.ForeignKey(Account, related_name="integrations", on_delete=models.CASCADE)
    provider = models.CharField(max_length=30, choices=Provider.choices)
    is_active = models.BooleanField(default=False)
    credentials = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "provider"], name="uniq_integration_provider"),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} - {self.account}"
