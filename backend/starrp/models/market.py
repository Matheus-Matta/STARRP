"""Precificação: o preço de cada produto comparado com o mercado (várias fontes).

Liga em Configurações da conta → Cosmos, onde a conta escolhe as fontes (`services/market/sources.py`).
A varredura (Celery, de hora em hora) pega os produtos que estão na vez, procura o MESMO produto nas
ofertas (GTIN primeiro; sem ele, título + marca + modelo + medidas), tira os preços fora da curva e
calcula a referência.

- `PriceCheck`: o processo de UM produto (variante) — a última leitura do mercado, o que o
  custo permite e a sugestão de preço esperando alguém aprovar. O novo preço fica aqui até a
  decisão: nada muda no cadastro sem um clique em Aprovar. O histórico (django-simple-history)
  guarda cada leitura anterior.
- `MarketOffer`: cada oferta encontrada na última leitura, com a nota do pareamento
  (o "porquê" da referência: dá para conferir se é mesmo o mesmo produto).
- `CompetitorPrice`: preço de concorrente que a equipe informou (tela ou planilha): a fonte grátis,
  e a única que enxerga a loja da esquina.
- `PriceSourceToken`: chave própria da conta numa fonte (vale no lugar da global do `.env`). Só no admin do
  Django: sem API e sem histórico, para o segredo não ficar copiado.
- `PriceUsage`: consultas por conta, mês e fonte, para o limite mensal (`Account.price_monthly_requests`).
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone

from starrp.models.base import TenantModel, TimeStampedModel, alive, user_fk
from starrp.models.fields import MoneyField, PercentField, UnitCostField


READ_TIMEOUT = timedelta(minutes=10)  # passou disto sem terminar: o worker caiu ou não está rodando


class PriceSourceToken(TimeStampedModel):
    class Source(models.TextChoices):
        GOOGLE_SHOPPING = "google_shopping", "Google Shopping (ferramenta própria)"
        SERPAPI = "serpapi", "SerpApi"
        BRIGHTDATA = "brightdata", "Bright Data"
        COSMOS = "cosmos", "Bluesoft Cosmos"

    account = models.ForeignKey("starrp.Account", related_name="price_tokens", on_delete=models.CASCADE)
    source = models.CharField("Fonte", max_length=30, choices=Source.choices)
    token = models.CharField("Chave", max_length=255)
    option = models.CharField("Zona ou endereço", max_length=255, blank=True,
                              help_text="Bright Data: a zona. Google Shopping: o endereço da ferramenta. Vazio = o global.")

    class Meta:
        ordering = ["source"]
        verbose_name = "Chave própria de fonte de preço"
        verbose_name_plural = "Chaves próprias das fontes de preço (no lugar das globais do .env)"
        constraints = [models.UniqueConstraint(fields=["account", "source"], name="uniq_price_token_source")]

    def __str__(self):
        return f"{self.account} · {self.get_source_display()}"  # nunca a chave


class PriceUsage(TimeStampedModel):
    account = models.ForeignKey("starrp.Account", related_name="price_usage", on_delete=models.CASCADE)
    month = models.DateField("Mês", help_text="Sempre o dia 1.")
    source = models.CharField("Fonte", max_length=30)
    requests = models.PositiveIntegerField("Consultas", default=0)

    class Meta:
        ordering = ["-month", "source"]
        verbose_name = "Consumo das fontes de preço"
        verbose_name_plural = "Consumo das fontes de preço (por mês)"
        constraints = [models.UniqueConstraint(fields=["account", "month", "source"], name="uniq_price_usage_month")]

    def __str__(self):
        return f"{self.account} · {self.month:%m/%Y} · {self.source}: {self.requests}"


class PriceCheck(TenantModel):
    class Position(models.TextChoices):
        ABOVE = "above", "Acima do mercado"
        INSIDE = "inside", "No preço do mercado"
        BELOW = "below", "Abaixo do mercado"
        UNKNOWN = "unknown", "Sem dados suficientes"

    class Status(models.TextChoices):
        NONE = "none", "Sem sugestão"
        PENDING = "pending", "Aguardando aprovação"
        APPLIED = "applied", "Preço aplicado"
        REJECTED = "rejected", "Recusada"

    variant = models.ForeignKey("starrp.ProductVariant", related_name="price_checks", on_delete=models.CASCADE)
    checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reading_since = models.DateTimeField(null=True, blank=True, help_text="Leitura na fila do worker, desde quando.")
    source = models.CharField(max_length=120, blank=True, help_text="Fontes que trouxeram ofertas na última leitura.")
    error = models.CharField(max_length=300, blank=True, help_text="Falha da última leitura (fonte fora do ar...).")
    ai_note = models.CharField(max_length=200, blank=True, help_text="O que a Cosmos mudou no pareamento da última leitura.")
    searches = models.JSONField(default=list, blank=True,
                                help_text="O que a última leitura pesquisou: [{source, query, offers, matched}].")

    # O produto na hora da leitura.
    current_price = MoneyField()
    cost = UnitCostField(help_text="Custo médio (ou o último, sem média) usado na conta.")
    current_margin = PercentField(null=True, blank=True, default=None, max_digits=7)

    # O mercado: só as ofertas pareadas com confiança, sem as fora da curva.
    competitors = models.PositiveIntegerField(default=0)
    offers_found = models.PositiveIntegerField(default=0)
    market_min = MoneyField(null=True, blank=True, default=None)
    market_p25 = MoneyField(null=True, blank=True, default=None)
    market_median = MoneyField(null=True, blank=True, default=None)
    market_p75 = MoneyField(null=True, blank=True, default=None)
    market_avg = MoneyField(null=True, blank=True, default=None)
    market_max = MoneyField(null=True, blank=True, default=None)
    market_rank = models.PositiveIntegerField(null=True, blank=True, help_text="Nosso lugar do mais barato ao mais caro, entre os concorrentes (1 = o mais barato).")
    price_index = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True,
                                      help_text="Seu preço ÷ mediana do mercado (1,000 = igual).")
    dispersion = PercentField(null=True, blank=True, default=None, max_digits=7,
                              help_text="Espalhamento do mercado (P75 − P25) ÷ mediana.")
    confidence = PercentField(null=True, blank=True, default=None, help_text="Nota média do pareamento.")
    position = models.CharField(max_length=10, choices=Position.choices, default=Position.UNKNOWN, db_index=True)

    # A sugestão (o "novo preço no processo") e se o custo deixa valer a pena.
    suggested_price = MoneyField(null=True, blank=True, default=None)
    suggested_margin = PercentField(null=True, blank=True, default=None, max_digits=7)
    floor_price = MoneyField(null=True, blank=True, default=None,
                             help_text="Menor preço que ainda dá a margem mínima com este custo.")
    worth_it = models.BooleanField(null=True, blank=True, default=None,
                                   help_text="Vale a pena aderir? Vazio = sem custo para decidir.")
    needs_review = models.BooleanField(default=False, help_text="Mercado muito espalhado ou pareamento fraco.")
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NONE, db_index=True)

    decided_by = user_fk("+")
    decided_at = models.DateTimeField(null=True, blank=True)
    applied_price = MoneyField(null=True, blank=True, default=None)
    previous_price = MoneyField(null=True, blank=True, default=None)

    # O nome real da fonte fica para a plataforma: o feed de histórico da conta não mostra (ver services/history.py).
    history_hidden = ("source", "error", "reading_since", "ai_note")

    class Meta:
        ordering = ["-checked_at"]
        constraints = [models.UniqueConstraint(fields=["variant"], condition=alive(), name="uniq_price_check_variant")]

    def __str__(self):
        return f"Precificação de {self.variant}"

    @property
    def standing(self):
        """ "2º de 6": o nosso preço conta como um dos seis."""
        return f"{self.market_rank}º de {self.competitors + 1}" if self.market_rank else ""

    @property
    def reading(self):
        return bool(self.reading_since) and timezone.now() - self.reading_since < READ_TIMEOUT

    @property
    def reading_stalled(self):
        return bool(self.reading_since) and not self.reading


class MarketOffer(TenantModel):
    price_check = models.ForeignKey(PriceCheck, related_name="offers", on_delete=models.CASCADE)
    source = models.CharField(max_length=30)
    query = models.CharField(max_length=300, blank=True, help_text="A busca que trouxe esta oferta.")
    observed_at = models.DateTimeField(null=True, blank=True, help_text="Quando a fonte trouxe esta oferta.")
    external_id = models.CharField(max_length=60)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=500, blank=True)
    seller = models.CharField(max_length=120, blank=True)
    price = MoneyField()
    free_shipping = models.BooleanField(default=False)
    match_score = PercentField(help_text="Nota do pareamento (0 a 100).")
    match_reason = models.CharField(max_length=200, blank=True)
    used = models.BooleanField(default=False, help_text="Entrou na referência (pareada e dentro da curva).")

    class Meta:
        ordering = ["-used", "-match_score", "price"]

    def __str__(self):
        return self.title


class CompetitorPrice(TenantModel):
    variant = models.ForeignKey("starrp.ProductVariant", related_name="competitor_prices", on_delete=models.CASCADE)
    competitor = models.CharField(max_length=120, help_text="Loja ou site concorrente.")
    price = MoneyField()
    observed_on = models.DateField(default=timezone.localdate, help_text="Dia em que o preço foi visto.")
    url = models.URLField(max_length=500, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-observed_on", "-created_at"]
        indexes = [models.Index(fields=["variant", "observed_on"])]

    def __str__(self):
        return f"{self.competitor}: {self.price}"
