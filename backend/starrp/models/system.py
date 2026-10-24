"""Registros técnicos: auditoria, idempotência, notificações e importações."""
import hashlib
import uuid

from django.conf import settings
from django.db import models

from starrp.models.base import TenantModel, user_fk


class AuditLog(TenantModel):
    store_lookup = "store"

    class Action(models.TextChoices):
        CREATED = "created", "Criado"
        UPDATED = "updated", "Alterado"
        DELETED = "deleted", "Excluído"
        CANCELLED = "cancelled", "Cancelado"
        APPROVED = "approved", "Aprovado"
        PRINTED = "printed", "Impresso"

    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    actor = user_fk("+")
    action = models.CharField(max_length=16, choices=Action.choices, db_index=True)
    entity = models.CharField(max_length=80, db_index=True)
    object_id = models.CharField(max_length=64, db_index=True)
    reason = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["entity", "object_id"])]

    def __str__(self):
        return f"{self.action} {self.entity} {self.object_id}"


def idempotency_record_id(account_id, key):
    """Id DERIVADO de (conta, chave): a mesma operação tentada na loja e na
    nuvem gera o mesmo id nos dois bancos, e a sincronização não duplica."""
    digest = hashlib.sha256(f"{account_id}:{key}".encode()).digest()
    return uuid.UUID(bytes=digest[:16], version=5)


class IdempotencyRecord(models.Model):
    """Resposta já produzida para uma `Idempotency-Key`, gravada na mesma
    transação da operação: o reenvio do PDV recebe a resposta, não executa."""

    id = models.UUIDField(primary_key=True, editable=False)
    account = models.ForeignKey("starrp.Account", related_name="+", on_delete=models.CASCADE)
    key = models.CharField(max_length=200)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    request_fingerprint = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "key"], name="uniq_idempotency_key")]

    def save(self, *args, **kwargs):
        if self.id is None:
            self.id = idempotency_record_id(self.account_id, self.key)
        super().save(*args, **kwargs)


class NumberSequence(models.Model):
    """Contador sequencial por loja e assunto ("sale", "return", "stock_document").

    Um só mecanismo para toda numeração humana, travado com
    `select_for_update` — `max()+1` dá número repetido com dois caixas.
    """

    account = models.ForeignKey("starrp.Account", related_name="+", on_delete=models.CASCADE)
    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.CASCADE)
    key = models.CharField(max_length=40)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "store", "key"], name="uniq_number_sequence")]


class Notification(TenantModel):
    class Level(models.TextChoices):
        INFO = "info", "Informação"
        SUCCESS = "success", "Sucesso"
        WARNING = "warning", "Atenção"
        ERROR = "error", "Erro"

    class Category(models.TextChoices):
        SYSTEM = "system", "Sistema"
        SALES = "sales", "Vendas"
        CASH = "cash", "Caixa"
        STOCK = "stock", "Estoque"
        FISCAL = "fiscal", "Fiscal"
        FINANCE = "finance", "Financeiro"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="notifications", on_delete=models.CASCADE,
        help_text="Vazio = todos os administradores da conta.",
    )
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.SYSTEM, db_index=True)
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    entity = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_read(self):
        return self.read_at is not None


class ImportJob(TenantModel):
    """Importação de planilha processada em segundo plano."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Na fila"
        RUNNING = "running", "Processando"
        DONE = "done", "Concluída"
        FAILED = "failed", "Falhou"

    resource = models.CharField(max_length=60, help_text="Ex.: products, customers.")
    key_field = models.CharField(max_length=60, blank=True, help_text="Campo que identifica linha existente.")
    rows = models.JSONField(default=list)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED, db_index=True)
    total = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
