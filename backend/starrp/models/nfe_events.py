"""Eventos de NF-e (recebidos da SEFAZ ou manifestações enviadas) e pendências
que exigem decisão humana.
"""
from django.db import models

from starrp.models.base import TenantModel, alive, user_fk
from starrp.models.inbound_nfe import InboundNFe

class NFeEvent(TenantModel):
    """Evento de NF-e: recebido da SEFAZ (cancelamento, CC-e) ou enviado por nós
    (manifestação do destinatário)."""

    store_lookup = "nfe__store"
    store_shared_when_null = True

    class Direction(models.TextChoices):
        RECEIVED = "received", "Recebido"
        SENT = "sent", "Enviado"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SENT = "sent", "Enviado"
        ACCEPTED = "accepted", "Aceito / processado"
        REJECTED = "rejected", "Rejeitado"
        IGNORED = "ignored", "Ignorado"
        ERROR = "error", "Erro"

    nfe = models.ForeignKey(InboundNFe, null=True, blank=True, related_name="events", on_delete=models.CASCADE)
    access_key = models.CharField(max_length=44, db_index=True)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    event_code = models.CharField(max_length=6, help_text="110111 cancelamento, 210200 confirmação...")
    description = models.CharField(max_length=120, blank=True)
    sequence = models.PositiveIntegerField(default=1)
    event_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    protocol = models.CharField(max_length=60, blank=True)
    cstat = models.CharField(max_length=3, blank=True)
    reason = models.TextField(blank=True)
    nsu = models.CharField(max_length=15, blank=True)
    request_xml = models.TextField(blank=True)
    xml = models.TextField(blank=True)
    history = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "access_key", "event_code", "sequence", "direction"],
                condition=alive(),
                name="uniq_nfe_event",
            ),
        ]


class NFeIssue(TenantModel):
    """Pendência que exige decisão humana (ex.: nota cancelada já recebida)."""

    store_lookup = "nfe__store"

    class Kind(models.TextChoices):
        CANCELLED_AFTER_RECEIPT = "cancelled_after_receipt", "Cancelada após o recebimento"
        CANCELLED_WITH_ASSETS = "cancelled_with_assets", "Cancelada com patrimônio gerado"
        STATUS_INCONSISTENCY = "status_inconsistency", "Status inconsistente"

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        RESOLVED = "resolved", "Resolvida"
        IGNORED = "ignored", "Ignorada"

    nfe = models.ForeignKey(InboundNFe, related_name="issues", on_delete=models.CASCADE)
    kind = models.CharField(max_length=30, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    description = models.TextField()
    resolved_by = user_fk("+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
