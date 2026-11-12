"""Cosmos, a assistente de IA da retaguarda (OpenAI), e a supervisão da equipe.

Não confundir com `Integration.Provider.COSMOS` (Bluesoft Cosmos, catálogo de GTIN).

- `CosmosConversation`: uma conversa do usuário no widget (cada um vê só as suas).
- `CosmosMessage`: as falas, na ordem. `blocks` leva o que a tela desenha além do texto
  (relatório com gráfico, botões, cartão de confirmação); `tool_calls`/`tool_call_id`
  guardam o vaivém com o modelo para a conversa continuar de onde parou.
- `CosmosAction`: uma gravação que a Cosmos PROPÔS (criar produto, mudar preço...). Nada é
  gravado sem o usuário clicar em Confirmar; ao confirmar, ela roda pela API normal, como o
  próprio usuário (mesmas permissões, validação, auditoria e histórico).
- `CosmosAttachment`: planilha/CSV/texto mandado na conversa, já lido (linhas e colunas).
- `CosmosReport`: relatório montado na conversa (formato do livro de relatórios), para baixar.
- `CosmosUsage`: tokens gastos por conta e por DIA; semana e mês são a soma (limites na conta, só no admin).
- `CosmosFinding`: o que a supervisão achou de errado (cadastro incompleto, desconto fora do
  padrão...) e quem fez. `fingerprint` impede avisar duas vezes a mesma coisa.
"""
from django.conf import settings
from django.db import models

from starrp.models.base import TenantModel, TimeStampedModel, alive, user_fk


class CosmosConversation(TenantModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="cosmos_conversations", on_delete=models.CASCADE)
    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL,
                              help_text="Filial ativa quando a conversa começou.")
    title = models.CharField(max_length=120, default="Nova conversa")
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Conversa aberta a partir de um alerta da supervisão (o alerta vira o assunto).
    finding = models.ForeignKey("starrp.CosmosFinding", null=True, blank=True, related_name="conversations",
                                on_delete=models.SET_NULL)
    # Resumo diário da equipe (quem supervisiona recebe um por dia): o dia resumido.
    digest_day = models.DateField(null=True, blank=True)
    # Memória longa barata: o que saiu da janela do histórico, resumido pelo modelo leve.
    summary = models.TextField(blank=True)
    summary_until = models.PositiveIntegerField(default=0, help_text="Última posição já resumida.")

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "digest_day"], condition=models.Q(digest_day__isnull=False),
                                    name="uniq_cosmos_digest_day"),
        ]

    def __str__(self):
        return self.title


class CosmosMessage(TenantModel):
    class Role(models.TextChoices):
        USER = "user", "Usuário"
        ASSISTANT = "assistant", "Cosmos"
        TOOL = "tool", "Ferramenta"
        EVENT = "event", "Acontecimento"  # confirmação/recusa de ação: vai ao modelo como fala do sistema

    conversation = models.ForeignKey(CosmosConversation, related_name="messages", on_delete=models.CASCADE)
    # Ordem na conversa. A hora sozinha empata (duas falas no mesmo instante, relógio do Windows) e a
    # conversa iria embaralhada ao modelo. A rodada segura a conversa (`cosmos:busy`), então não há disputa.
    position = models.PositiveIntegerField(default=0, db_index=True)
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField(blank=True)
    blocks = models.JSONField(default=list, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    tool_call_id = models.CharField(max_length=80, blank=True)
    tool_name = models.CharField(max_length=60, blank=True)
    tokens = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]

    def save(self, *args, **kwargs):
        if self._state.adding and not self.position:
            last = (CosmosMessage.all_objects.filter(conversation_id=self.conversation_id)
                    .aggregate(m=models.Max("position"))["m"])
            self.position = (last or 0) + 1
        super().save(*args, **kwargs)


class CosmosAction(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando confirmação"
        EXECUTED = "executed", "Executada"
        FAILED = "failed", "Falhou"
        REJECTED = "rejected", "Recusada"
        EXPIRED = "expired", "Expirada"

    conversation = models.ForeignKey(CosmosConversation, related_name="actions", on_delete=models.CASCADE)
    message = models.ForeignKey(CosmosMessage, null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    tool_call_id = models.CharField(max_length=80, blank=True)
    method = models.CharField(max_length=6)
    path = models.CharField(max_length=300)
    body = models.JSONField(default=dict, blank=True)
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    preview = models.JSONField(default=list, blank=True, help_text='[{"label", "value"}] mostrados ao usuário.')
    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    result = models.JSONField(default=dict, blank=True)
    decided_by = user_fk("+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class CosmosAttachment(TenantModel):
    """Arquivo que o usuário mandou na conversa (planilha, CSV, texto). Guarda só o conteúdo lido
    (`rows`/`text`), não o arquivo: a Cosmos lê pelas ferramentas (`ler_anexo`)."""

    class Kind(models.TextChoices):
        SHEET = "sheet", "Planilha"
        TEXT = "text", "Texto"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="+", on_delete=models.CASCADE)
    # Vazio até a mensagem ser enviada (o envio do arquivo vem antes da mensagem).
    conversation = models.ForeignKey(CosmosConversation, null=True, blank=True, related_name="attachments",
                                     on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    size = models.PositiveIntegerField(default=0)
    sheet = models.CharField(max_length=120, blank=True, help_text="Aba lida (planilha).")
    columns = models.JSONField(default=list, blank=True)
    rows = models.JSONField(default=list, blank=True, help_text="Linhas como listas, na ordem das colunas.")
    row_count = models.PositiveIntegerField(default=0, help_text="Linhas no arquivo (pode passar do que foi guardado).")
    text = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.name


class CosmosReport(TenantModel):
    conversation = models.ForeignKey(CosmosConversation, null=True, blank=True, related_name="reports",
                                     on_delete=models.SET_NULL)
    slug = models.SlugField(max_length=80, blank=True, help_text="Relatório do livro que originou (vazio = montado).")
    title = models.CharField(max_length=200)
    data = models.JSONField(default=dict, help_text="Relatório no formato do livro (kpis + blocos).")
    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]


class CosmosFinding(TenantModel):
    store_lookup = "store"
    store_shared_when_null = True

    class Severity(models.TextChoices):
        INFO = "info", "Informação"
        WARNING = "warning", "Atenção"
        CRITICAL = "critical", "Grave"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        RESOLVED = "resolved", "Resolvido"
        DISMISSED = "dismissed", "Descartado"

    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    actor = user_fk("+", help_text="Quem fez o que foi apontado.")
    rule = models.CharField(max_length=60, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    title = models.CharField(max_length=200)
    detail = models.TextField(blank=True)
    entity = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    endpoint = models.CharField(max_length=120, blank=True, help_text="Recurso da API (a tela abre o cadastro).")
    fingerprint = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolved_by = user_fk("+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["account", "fingerprint"], condition=alive(status="open"),
                                    name="uniq_open_cosmos_finding"),
        ]

    def __str__(self):
        return self.title


class CosmosUsage(TimeStampedModel):
    """Consumo da OpenAI de uma conta num dia: somado a cada chamada ao modelo. Só a plataforma vê (admin)."""

    account = models.ForeignKey("starrp.Account", related_name="cosmos_usage", on_delete=models.CASCADE)
    day = models.DateField("Dia")
    requests = models.PositiveIntegerField("Chamadas ao modelo", default=0)
    prompt_tokens = models.PositiveBigIntegerField("Tokens de entrada", default=0)
    cached_tokens = models.PositiveBigIntegerField(
        "Entrada em cache", default=0, help_text="Parte da entrada servida do cache da OpenAI (cobrada com desconto).")
    completion_tokens = models.PositiveBigIntegerField("Tokens de saída", default=0)
    total_tokens = models.PositiveBigIntegerField("Total de tokens", default=0)

    class Meta:
        ordering = ["-day"]
        verbose_name = "Consumo da Cosmos"
        verbose_name_plural = "Consumo da Cosmos"
        constraints = [models.UniqueConstraint(fields=["account", "day"], name="uniq_cosmos_usage_day")]

    def __str__(self):
        return f"{self.account} · {self.day:%d/%m/%Y} · {self.total_tokens} tokens"
