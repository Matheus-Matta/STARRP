"""Plataforma SaaS: planos, contas (tenants), assinatura e integrações.

Antes, a assinatura vivia em dois lugares (`Account.plan`/`subscription_status`
e `Subscription`), e cada integração externa tinha a sua tabela
(`FocusNfeConfig`, `CosmosConfig`). Aqui: o plano e o status moram só na
assinatura, e toda integração é uma linha de `Integration`.
"""
from django.db import models

from starrp.core.secrets import EncryptedJSONField
from starrp.models.base import MoneyField, TenantModel, TimeStampedModel, alive

MODULE_BASE = "base"


class Module(models.TextChoices):
    BASE = MODULE_BASE, "Base (PDV, vendas, produtos, clientes e fiscal NFC-e/NF-e)"
    STOCK = "stock", "Estoque e compras"
    FINANCE = "finance", "Financeiro"
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
    cosmos_voice_enabled = models.BooleanField(
        "Entrada por voz", default=False,
        help_text="Permite falar com a Cosmos em vez de digitar; as respostas continuam em texto.")
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


class Integration(TenantModel):
    """Uma integração da conta com um serviço externo (Asaas, Shopify...).

    O TIPO (`kind`) é uma classe em `starrp.services.integrations` que declara as configurações (nomes
    fixos, obrigatórias, segredos) e o que a integração pode fazer. Aqui ficam só os valores:
    - `fields`: {nome da configuração: valor}. Segredos (chave da API, tokens) nunca voltam para a tela;
    - `purposes`: o que a conta ligou (ex.: ["receivable_boleto", "auto_settle"]).
    A conta pode ter várias do mesmo tipo (duas contas do Asaas): `name` as distingue e `is_default`
    diz qual usar quando o título não escolhe.
    """

    kind = models.CharField("Tipo", max_length=40)
    name = models.CharField("Nome", max_length=120, help_text="Ex.: Asaas — Empresa A.")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False, help_text="A usada quando há mais de uma do mesmo tipo.")
    fields = EncryptedJSONField(default=dict, blank=True)  # cifrado: leva chave da API e tokens
    purposes = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    last_check_at = models.DateTimeField(null=True, blank=True)
    last_check_ok = models.BooleanField(null=True, blank=True)
    last_check_message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "name"], condition=alive(), name="uniq_integration_name"),
        ]

    def __str__(self):
        return self.name  # nunca os valores


class IntegrationWebhookEvent(TimeStampedModel):
    """Entrega recebida de um provedor, persistida antes da resposta HTTP 200.

    O identificador do provedor é único por integração para que reenvios sejam
    confirmados sem executar a regra de negócio novamente.
    """

    class Status(models.TextChoices):
        RECEIVED = "received", "Recebido"
        PROCESSED = "processed", "Processado"
        IGNORED = "ignored", "Ignorado"
        FAILED = "failed", "Falhou"

    account = models.ForeignKey(Account, related_name="+", on_delete=models.PROTECT)
    integration = models.ForeignKey(Integration, related_name="webhook_events", on_delete=models.PROTECT)
    provider = models.CharField(max_length=40, db_index=True)
    provider_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=120, db_index=True)
    payload = models.JSONField(default=dict)
    headers = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "provider_event_id"], name="uniq_integration_webhook_event"
            ),
        ]

    def __str__(self):
        return f"{self.provider}: {self.event_type} ({self.provider_event_id})"
