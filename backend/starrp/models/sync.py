"""Sincronização loja ⇄ nuvem: nós, outbox/inbox, cargas e conflitos.

Os VALORES das choices são o protocolo v1 e trafegam entre instalações: não
mudam sem subir `PROTOCOL_VERSION` (o outro nó pode estar na versão anterior).
A versão de cada registro sincronizado é o `updated_at` dele em microssegundos.
"""
import uuid

from django.db import models

from starrp.models.base import TimeStampedModel, UUIDModel

PROTOCOL_VERSION = 1
SCHEMA_VERSION = 1


class SyncEnvironment(models.TextChoices):
    DEVELOPMENT = "development", "Desenvolvimento"
    PRODUCTION = "production", "Produção"


class NodeType(models.TextChoices):
    LOCAL = "LOCAL", "Servidor da loja"
    CLOUD = "CLOUD", "Servidor da nuvem"


class NodeStatus(models.TextChoices):
    PENDING = "PENDING", "Aguardando primeiro handshake"
    ACTIVE = "ACTIVE", "Ativo"
    OFFLINE = "OFFLINE", "Sem conexão"
    BLOCKED = "BLOCKED", "Bloqueado"
    REVOKED = "REVOKED", "Revogado"


class Direction(models.TextChoices):
    INBOUND = "INBOUND", "Recebido"
    OUTBOUND = "OUTBOUND", "Enviado"


class Operation(models.TextChoices):
    CREATE = "CREATE", "Criação"
    UPDATE = "UPDATE", "Atualização"
    DELETE = "DELETE", "Exclusão"
    UPSERT = "UPSERT", "Upsert"
    SNAPSHOT = "SNAPSHOT", "Snapshot"


class EventStatus(models.TextChoices):
    PENDING = "PENDING", "Na fila"
    PROCESSING = "PROCESSING", "Em processamento"
    SENT = "SENT", "Enviado, sem confirmação"
    RECEIVED = "RECEIVED", "Recebido pelo destino"
    APPLIED = "APPLIED", "Aplicado no destino"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Confirmado na origem"
    FAILED = "FAILED", "Falhou, vai tentar de novo"
    DEAD = "DEAD", "Desistiu; exige reprocessamento manual"


class RunType(models.TextChoices):
    BOOTSTRAP = "BOOTSTRAP", "Dados essenciais"
    FULL = "FULL", "Tudo"
    INCREMENTAL = "INCREMENTAL", "Incremental"


class RunStatus(models.TextChoices):
    PENDING = "PENDING", "Na fila"
    PREPARING = "PREPARING", "Preparando"
    RUNNING = "RUNNING", "Enviando"
    VALIDATING = "VALIDATING", "Validando"
    COMPLETED = "COMPLETED", "Concluída"
    FAILED = "FAILED", "Falhou"
    CANCELLED = "CANCELLED", "Cancelada"


class ConflictResolution(models.TextChoices):
    CLOUD_WINS = "CLOUD_WINS", "Nuvem vence"
    LOCAL_WINS = "LOCAL_WINS", "Loja vence"
    LAST_VERSION = "LAST_VERSION", "Maior versão vence"
    MANUAL = "MANUAL", "Revisão manual"
    IGNORED = "IGNORED", "Ignorado"


class ConflictStatus(models.TextChoices):
    OPEN = "OPEN", "Aberto"
    RESOLVED = "RESOLVED", "Resolvido"
    IGNORED = "IGNORED", "Ignorado"


def _account_fk(related_name, **kwargs):
    kwargs.setdefault("on_delete", models.PROTECT)
    return models.ForeignKey("starrp.Account", related_name=related_name, **kwargs)


def _node_fk(related_name):
    return models.ForeignKey("starrp.SyncNode", related_name=related_name, on_delete=models.PROTECT)


class SyncNode(TimeStampedModel):
    """Uma ponta do vínculo. Os dois lados compartilham `pair_id`."""

    pair_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    account = _account_fk("sync_nodes")
    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="sync_nodes", on_delete=models.PROTECT)
    node_type = models.CharField(max_length=8, choices=NodeType.choices, db_index=True)
    environment = models.CharField(max_length=12, choices=SyncEnvironment.choices, default=SyncEnvironment.DEVELOPMENT)
    name = models.CharField(max_length=120)
    endpoint = models.URLField(blank=True, help_text="URL WSS que o nó local procura.")
    allowed_ip = models.GenericIPAddressField(null=True, blank=True)
    credential_hash = models.CharField(max_length=128, blank=True)
    credential_rotated_at = models.DateTimeField(null=True, blank=True)
    encryption_key_id = models.CharField(max_length=64, blank=True)
    secret_fingerprint = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=NodeStatus.choices, default=NodeStatus.PENDING)
    app_version = models.CharField(max_length=32, blank=True)
    schema_version = models.PositiveIntegerField(default=0)
    protocol_version = models.PositiveIntegerField(default=0)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    offline_since = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sent_cursor = models.BigIntegerField(default=0)
    last_received_cursor = models.BigIntegerField(default=0)
    sequence_counter = models.BigIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_self = models.BooleanField(default=False, help_text="Esta instalação.")
    peer = models.ForeignKey("self", null=True, blank=True, related_name="peers", on_delete=models.SET_NULL)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["account", "node_type", "name"]
        constraints = [models.UniqueConstraint(fields=["pair_id", "node_type"], name="uniq_sync_node_per_pair")]

    def __str__(self):
        return f"{self.name} ({self.get_node_type_display()})"

    @property
    def can_connect(self):
        return self.is_active and self.status in {NodeStatus.PENDING, NodeStatus.ACTIVE, NodeStatus.OFFLINE}

    @property
    def group_name(self):
        return f"sync.account.{self.account_id}.node.{self.id}"


class SyncEvent(UUIDModel):
    """Evento durável, gravado na MESMA transação do dado que o gerou."""

    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = _account_fk("sync_events")
    source_node = _node_fk("events_sent")
    target_node = _node_fk("events_received")
    run = models.ForeignKey("starrp.SyncRun", null=True, blank=True, related_name="events", on_delete=models.SET_NULL)
    direction = models.CharField(max_length=8, choices=Direction.choices, db_index=True)
    sequence = models.BigIntegerField()
    entity_type = models.CharField(max_length=80, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)
    operation = models.CharField(max_length=10, choices=Operation.choices)
    entity_version = models.BigIntegerField(default=1)
    protocol_version = models.PositiveIntegerField(default=PROTOCOL_VERSION)
    schema_version = models.PositiveIntegerField(default=SCHEMA_VERSION)
    payload = models.JSONField(default=dict)
    payload_checksum = models.CharField(max_length=64)
    status = models.CharField(max_length=14, choices=EventStatus.choices, default=EventStatus.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sequence", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source_node", "direction", "sequence"], name="uniq_sync_sequence"),
        ]
        indexes = [
            models.Index(fields=["target_node", "status"]),
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["status", "next_attempt_at"]),
        ]

    def __str__(self):
        return f"{self.entity_type}/{self.entity_id} #{self.sequence} [{self.status}]"

    @property
    def is_terminal(self):
        return self.status in {EventStatus.ACKNOWLEDGED, EventStatus.DEAD}
