"""Registros auxiliares da sincronização: cargas, conflitos, descartes, marcas de
trigger, transferência de arquivo e bilhete de matrícula.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from starrp.models.base import UUIDModel, user_fk
from starrp.models.sync import (
    ConflictResolution, ConflictStatus, RunStatus, RunType, SyncEvent, SyncNode, _account_fk, _node_fk,
)

class SyncRun(UUIDModel):
    """Carga completa ou de bootstrap, com progresso auditável."""

    account = _account_fk("sync_runs")
    source_node = _node_fk("runs_as_source")
    target_node = _node_fk("runs_as_target")
    run_type = models.CharField(max_length=12, choices=RunType.choices)
    status = models.CharField(max_length=12, choices=RunStatus.choices, default=RunStatus.PENDING)
    snapshot_cursor = models.BigIntegerField(default=0)
    manifest = models.JSONField(default=dict, blank=True)
    current_entity = models.CharField(max_length=80, blank=True)
    total_records = models.BigIntegerField(default=0)
    processed_records = models.BigIntegerField(default=0)
    failed_records = models.BigIntegerField(default=0)
    initiated_by = user_fk("+")
    reason = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def progress_percent(self):
        if not self.total_records:
            return 0
        return min(100, round(self.processed_records * 100 / self.total_records))


class SyncConflict(UUIDModel):
    """Dado financeiro/fiscal nunca é resolvido em silêncio: cai aqui."""

    account = _account_fk("sync_conflicts")
    event = models.ForeignKey(SyncEvent, null=True, blank=True, related_name="conflicts", on_delete=models.SET_NULL)
    entity_type = models.CharField(max_length=80, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)
    source_node = _node_fk("conflicts_as_source")
    target_node = _node_fk("conflicts_as_target")
    local_version = models.BigIntegerField(default=0)
    remote_version = models.BigIntegerField(default=0)
    local_payload = models.JSONField(default=dict, blank=True)
    remote_payload = models.JSONField(default=dict, blank=True)
    resolution = models.CharField(max_length=14, choices=ConflictResolution.choices, default=ConflictResolution.MANUAL)
    status = models.CharField(max_length=10, choices=ConflictStatus.choices, default=ConflictStatus.OPEN)
    resolved_by = user_fk("+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class SyncDiscard(UUIDModel):
    """O que chegou e foi IGNORADO (versão mais velha, reenvio): guardado para
    conferir e recuperar. Nomes de campo em inglês, como o resto do projeto."""

    class Source(models.TextChoices):
        API = "api", "Requisição da API"
        SYNC = "sync", "Sincronização"

    class Reason(models.TextChoices):
        OLDER_VERSION = "older_version", "Versão mais velha que a gravada"
        RESEND = "resend", "Reenvio do que já existe"
        OLDER_DELETE = "older_delete", "Exclusão mais velha que uma edição"
        DELETED_LATER = "deleted_later", "Registro apagado aqui depois"

    account = _account_fk("sync_discards", null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=8, choices=Source.choices, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices, db_index=True)
    entity_type = models.CharField(max_length=80, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)
    data = models.JSONField(default=dict, blank=True)
    received_version = models.BigIntegerField(default=0)
    local_version = models.BigIntegerField(default=0)
    event = models.ForeignKey(SyncEvent, null=True, blank=True, related_name="discards", on_delete=models.SET_NULL)
    user = user_fk("+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class SyncDirty(UUIDModel):
    """Marca deixada pela trigger quando o ORM foi contornado (update/bulk)."""

    table_name = models.CharField(max_length=120, db_index=True)
    row_id = models.CharField(max_length=64, db_index=True)
    operation = models.CharField(max_length=10)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    event = models.ForeignKey(SyncEvent, null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["changed_at"]
        indexes = [models.Index(fields=["processed_at", "changed_at"])]


class SyncFileTransfer(UUIDModel):
    """Binário (imagem, XML, PDF) enviado em pedaços, retomável por offset."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Aguardando o primeiro pedaço"
        RECEIVING = "RECEIVING", "Recebendo"
        VALIDATING = "VALIDATING", "Conferindo checksum"
        COMPLETED = "COMPLETED", "Concluída"
        FAILED = "FAILED", "Falhou"

    account = _account_fk("sync_transfers")
    source_node = _node_fk("transfers_sent")
    target_node = _node_fk("transfers_received")
    entity_type = models.CharField(max_length=80, db_index=True)
    entity_id = models.CharField(max_length=64, db_index=True)
    field_name = models.CharField(max_length=80)
    storage_path = models.CharField(max_length=500)
    content_type = models.CharField(max_length=120, blank=True)
    total_bytes = models.BigIntegerField()
    received_bytes = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    temp_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["target_node", "storage_path", "checksum"],
                condition=models.Q(status__in=["PENDING", "RECEIVING", "VALIDATING"]),
                name="uniq_open_sync_transfer",
            ),
        ]


class SyncEnrollmentTicket(UUIDModel):
    """Convite de matrícula de UMA loja: vale uma vez e por pouco tempo."""

    DEFAULT_VALIDITY_MINUTES = 30

    account = _account_fk("sync_enrollment_tickets", on_delete=models.CASCADE)
    store = models.ForeignKey("starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    code_hash = models.CharField(max_length=64, unique=True, editable=False)
    label = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by_node = models.ForeignKey(SyncNode, null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    used_from_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self):
        return self.used_at is None and timezone.now() < self.expires_at
