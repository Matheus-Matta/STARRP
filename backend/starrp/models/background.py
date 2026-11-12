"""Tarefas em segundo plano (Configurações → Tarefas): as rodando agora e as antigas, com o progresso.

O estado fica aqui, e não no result backend do Celery, porque precisa valer por conta, sobreviver ao fim da tarefa como
histórico e funcionar sem Redis. Uma rodada é vários lotes (várias tarefas do Celery) e uma tarefa só para quem olha.
"""
from django.db import models
from django.utils import timezone

from starrp.models.base import TenantModel, alive, user_fk


class BackgroundTask(TenantModel):
    class Kind(models.TextChoices):
        PRICE_ROUND = "price_round", "Precificação: leitura do mercado"
        SEO_ROUND = "seo_round", "Analítico de SEO: análise dos produtos"
        PRICE_READ = "price_read", "Precificação: leitura de um produto"
        SEO_READ = "seo_read", "Analítico de SEO: análise de um produto"

    class Status(models.TextChoices):
        RUNNING = "running", "Em andamento"
        COMPLETED = "completed", "Concluída"
        FAILED = "failed", "Falha"
        STOPPED = "stopped", "Parada"

    ROUNDS = (Kind.PRICE_ROUND, Kind.SEO_ROUND)

    kind = models.CharField("Tarefa", max_length=20, choices=Kind.choices, db_index=True)
    status = models.CharField("Situação", max_length=10, choices=Status.choices, default=Status.RUNNING, db_index=True)
    done = models.PositiveIntegerField("Feitos", default=0)
    total = models.PositiveIntegerField("Total", default=0)
    error = models.CharField("Motivo", max_length=300, blank=True, help_text="Vai para a tela: nunca nome de API, chave ou detalhe técnico.")
    started_by = user_fk("+")
    started_at = models.DateTimeField("Início", default=timezone.now, db_index=True)
    finished_at = models.DateTimeField("Fim", null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # Uma rodada por conta e tipo: o banco garante, mesmo com dois cliques ao mesmo tempo.
            models.UniqueConstraint(fields=["account", "kind"], name="uniq_running_round",
                                    condition=alive() & models.Q(status="running", kind__in=["price_round", "seo_round"])),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.get_status_display()})"

    @property
    def percent(self):
        return min(self.done * 100 // self.total, 100) if self.total else 0

    @property
    def can_stop(self):
        return self.status == self.Status.RUNNING and self.kind in self.ROUNDS
