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
    PRICING = "pricing", "Precificação (preço × mercado)"
    SEO = "seo", "Analítico de SEO"
    COSMOS = "cosmos", "Cosmos (assistente de IA)"


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


def default_price_sources():
    return ["manual", "brightdata", "serpapi"]  # sem chave, a fonte fica de fora da leitura sozinha


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
    # Cosmos (IA): controle da PLATAFORMA, só pelo admin do Django — a conta não vê nem altera.
    # Três limites independentes de tokens (entrada + saída); 0 = sem limite naquele período.
    # Use um, dois ou os três (ex.: 50 mil por dia E 1 milhão por mês). Consumo em `CosmosUsage`.
    cosmos_enabled = models.BooleanField("Cosmos ligada", default=True)
    cosmos_daily_tokens = models.PositiveIntegerField(
        "Limite de tokens por dia", default=0, help_text="0 = sem limite diário.")
    cosmos_weekly_tokens = models.PositiveIntegerField(
        "Limite de tokens por semana", default=0, help_text="Semana de segunda a domingo. 0 = sem limite semanal.")
    cosmos_monthly_tokens = models.PositiveIntegerField(
        "Limite de tokens por mês", default=1_000_000, help_text="Mês civil. 0 = sem limite mensal.")
    cosmos_daily_digest = models.BooleanField(
        "Resumo diário da equipe", default=True,
        help_text="Quem supervisiona recebe na Cosmos, toda manhã, o resumo do dia anterior (não gasta tokens).")
    # A Cosmos nas telas, em segundo plano. A conta desliga para economizar tokens (ver services/cosmos/light.py).
    cosmos_seo_ai = models.BooleanField("Cosmos no Analítico de SEO", default=True, help_text="Sugere nome, título e resumo com os pontos e os termos.")
    cosmos_pricing_ai = models.BooleanField("Cosmos na Precificação", default=True, help_text="Confere se as ofertas são mesmo o mesmo produto.")
    cosmos_stock_advice = models.BooleanField("Cosmos no estoque", default=True,
                                              help_text="Recomenda como organizar os endereços e avisa de entregas paradas. Não gasta tokens.")
    # Precificação (Configurações da conta → Cosmos): o preço de cada produto comparado com o
    # mercado. A conta liga e ajusta a margem e a frequência; as fontes são da plataforma (admin do Django).
    # Nada muda no cadastro sem aprovação (ver models/market.py).
    class SearchMode(models.TextChoices):
        FALLBACK = "fallback", "Só se a anterior falhar"
        ALL = "all", "Todas sempre"

    price_tracking_enabled = models.BooleanField("Rastrear preços no mercado", default=False)
    price_sources = models.JSONField("Fontes de preço", default=default_price_sources, blank=True,
                                     help_text="Só no admin do Django. Em ordem: é a fila de execução. Ver services/market/sources.py.")
    price_search_mode = models.CharField(
        "Com mais de uma fonte de busca", max_length=10, choices=SearchMode.choices, default=SearchMode.FALLBACK,
        help_text="Falhar = erro, bloqueio, limite ou nenhuma oferta aceita.")
    price_tracking_hours = models.PositiveIntegerField(
        "Frequência da leitura (horas)", default=24, help_text="De quanto em quanto tempo cada produto é relido.")
    price_min_margin = models.DecimalField(
        "Margem mínima (%)", max_digits=5, decimal_places=2, default=20,
        help_text="Sobre o preço de venda. Sugestão nunca deixa a margem abaixo disto.")
    price_band = models.DecimalField(
        "Faixa do mercado (%)", max_digits=5, decimal_places=2, default=10,
        help_text="Até esta distância da mediana o preço está 'no mercado'.")
    price_min_competitors = models.PositiveIntegerField(
        "Mínimo de concorrentes", default=3, help_text="Menos ofertas pareadas que isto: só informa, não sugere.")
    price_match_min = models.PositiveIntegerField(
        "Confiança mínima do pareamento (%)", default=85,
        help_text="Oferta abaixo desta nota não conta como o mesmo produto.")
    price_scope = models.JSONField(
        "Regras da precificação", default=dict, blank=True,
        help_text="Quais produtos a leitura automática pega (ver services/market/scope.py). Vazio = todos.")
    seo_scope = models.JSONField(
        "Regras do Analítico de SEO", default=dict, blank=True,
        help_text="Quais produtos a análise pega (ver services/market/scope.py). Vazio = todos.")
    # Controle da PLATAFORMA, só pelo admin do Django. O módulo é `Module.SEO`; a credencial, `SeoCredential`.
    seo_monthly_requests = models.PositiveIntegerField(
        "Limite de consultas de busca (SEO) por mês", default=500,
        help_text="Consultas de palavras-chave, com a credencial global ou a da conta. Termo já guardado não conta. Mês civil. 0 = sem limite.")
    # Controle da PLATAFORMA, só pelo admin do Django (como os limites da Cosmos). O módulo é `Module.PRICING`.
    price_monthly_requests = models.PositiveIntegerField(
        "Limite de consultas de preço por mês", default=500,
        help_text="Consultas às fontes com chave (Google Shopping, SerpApi, Bright Data, Bluesoft), com a chave global ou a da conta. "
                  "Mês civil. 0 = sem limite.")

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

    @property
    def cosmos_active(self):
        """A conta pode usar a Cosmos: tem o módulo e não foi desligada no admin. Sem isto, nem widget nem acesso."""
        return self.cosmos_enabled and self.has_module(Module.COSMOS)

    def session_modules(self):
        """O que a tela usa para mostrar ou esconder. `cosmos_stock` é uma tela que depende de dois módulos e de um interruptor."""
        modules = self.active_modules()
        if not self.cosmos_active:
            modules = modules - {Module.COSMOS.value}
        elif self.cosmos_stock_advice and Module.STOCK.value in modules:
            modules = {*modules, "cosmos_stock"}
        return sorted(modules)


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
