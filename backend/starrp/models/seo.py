"""Analítico de SEO: o cadastro de cada produto avaliado, com nota, problemas e sugestões.

Mesma ideia da precificação: nada muda no cadastro sem alguém aprovar, sugestão por sugestão.

- `SeoCheck`: a análise de UM produto. A nota mede a qualidade do preenchimento; não promete posição no Google.
- `KeywordMetric`: volume de busca por termo, região e idioma. Vale para todas as contas (é dado público do mercado,
  sem nada da conta) e fica guardado porque o Google só atualiza esses números uma vez por mês.
- `SeoCredential`: credenciais próprias da conta na API de busca (no lugar das globais do `.env`). Só no admin do
  Django: sem API e sem histórico, para o segredo não ficar copiado.
- `SeoUsage`: consultas por conta e mês, para o limite mensal (`Account.seo_monthly_requests`).
"""
from django.db import models

from starrp.models.base import TenantModel, TimeStampedModel, alive, user_fk
from starrp.models.market import READ_TIMEOUT


class SeoCredential(TimeStampedModel):
    account = models.OneToOneField("starrp.Account", related_name="seo_credential", on_delete=models.CASCADE)
    client_id = models.CharField("OAuth client ID", max_length=255)
    client_secret = models.CharField("OAuth client secret", max_length=255)
    refresh_token = models.CharField("Refresh token", max_length=512)
    customer_id = models.CharField("Conta do Google Ads (customer ID)", max_length=12, help_text="Só os dígitos.")
    login_customer_id = models.CharField("Conta administradora (login-customer-id)", max_length=12, blank=True,
                                         help_text="Só se o acesso for por uma conta administradora.")
    developer_token = models.CharField("Developer token", max_length=255, blank=True,
                                       help_text="Só para projeto antigo: o Google descontinuou em setembro de 2026.")

    class Meta:
        verbose_name = "Credencial própria da busca de palavras-chave"
        verbose_name_plural = "Credencial própria da busca de palavras-chave (no lugar da global do .env)"

    def __str__(self):
        return f"{self.account} · busca de palavras-chave"  # nunca o segredo


class SeoUsage(TimeStampedModel):
    account = models.ForeignKey("starrp.Account", related_name="seo_usage", on_delete=models.CASCADE)
    month = models.DateField("Mês", help_text="Sempre o dia 1.")
    requests = models.PositiveIntegerField("Consultas", default=0)

    class Meta:
        ordering = ["-month"]
        verbose_name = "Consumo da busca de palavras-chave"
        verbose_name_plural = "Consumo da busca de palavras-chave (por mês)"
        constraints = [models.UniqueConstraint(fields=["account", "month"], name="uniq_seo_usage_month")]

    def __str__(self):
        return f"{self.account} · {self.month:%m/%Y}: {self.requests}"


class KeywordMetric(TimeStampedModel):
    term = models.CharField(max_length=200)
    geo = models.CharField(max_length=20, default="2076", help_text="Região no Google (2076 = Brasil).")
    language = models.CharField(max_length=20, default="1014", help_text="Idioma no Google (1014 = português).")
    avg_monthly_searches = models.PositiveIntegerField(null=True, blank=True, help_text="Vazio = o Google não informou.")
    competition = models.CharField(max_length=12, blank=True, help_text="Concorrência em anúncios: não é dificuldade de SEO.")
    fetched_at = models.DateTimeField()

    class Meta:
        verbose_name = "Volume de busca"
        verbose_name_plural = "Volumes de busca"
        constraints = [models.UniqueConstraint(fields=["term", "geo", "language"], name="uniq_keyword_metric")]

    def __str__(self):
        return f"{self.term}: {self.avg_monthly_searches}"


class SeoCheck(TenantModel):
    class Status(models.TextChoices):
        NONE = "none", "Sem sugestão"
        PENDING = "pending", "Aguardando aprovação"
        APPLIED = "applied", "Sugestões aplicadas"
        REJECTED = "rejected", "Recusada"

    product = models.ForeignKey("starrp.Product", related_name="seo_checks", on_delete=models.CASCADE)
    checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reading_since = models.DateTimeField(null=True, blank=True, help_text="Análise na fila do worker, desde quando.")
    error = models.CharField(max_length=300, blank=True, help_text="Falha na última consulta dos dados de busca.")
    score = models.PositiveSmallIntegerField("Nota", null=True, blank=True, db_index=True, help_text="0 a 100: qualidade do cadastro.")
    has_search_data = models.BooleanField(default=False, help_text="A nota considerou o volume de busca do Google.")
    breakdown = models.JSONField(default=list, blank=True, help_text="[{key, label, points, max}]")
    issues = models.JSONField(default=list, blank=True, help_text="[{field, severity, message, origin}]")
    keywords = models.JSONField(default=list, blank=True, help_text="[{term, avg_monthly_searches, competition, origin}]")
    suggested_name = models.CharField(max_length=180, blank=True)
    suggested_seo_title = models.CharField(max_length=70, blank=True)
    suggested_seo_description = models.CharField(max_length=160, blank=True)
    suggested_slug = models.SlugField(max_length=180, blank=True)
    ai_signature = models.CharField(max_length=64, blank=True, help_text="O que a Cosmos analisou: igual, não gasta token de novo.")
    ai_result = models.JSONField(default=dict, blank=True, help_text="A última resposta da Cosmos, já validada.")
    status = models.CharField("Situação", max_length=10, choices=Status.choices, default=Status.NONE, db_index=True)
    decided_by = user_fk("+")
    decided_at = models.DateTimeField(null=True, blank=True)

    # O feed mostra a nota e a situação; as sugestões em si estão na tela, e o que foi aplicado, no histórico do produto.
    history_hidden = ("error", "reading_since", "has_search_data", "suggested_name", "suggested_seo_title",
                      "suggested_seo_description", "suggested_slug", "decided_by", "decided_at", "ai_signature")

    class Meta:
        ordering = ["score", "-checked_at"]
        constraints = [models.UniqueConstraint(fields=["product"], condition=alive(), name="uniq_seo_check_product")]

    def __str__(self):
        return f"SEO de {self.product}"

    @property
    def reading(self):
        from django.utils import timezone

        return bool(self.reading_since) and timezone.now() - self.reading_since < READ_TIMEOUT

    @property
    def reading_stalled(self):
        return bool(self.reading_since) and not self.reading
