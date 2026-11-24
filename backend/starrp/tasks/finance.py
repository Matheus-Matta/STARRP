"""Tarefas do financeiro: as contas recorrentes geram o título do mês sozinhas."""
from celery import shared_task

from starrp.services import recurring


@shared_task(name="starrp.recurring_titles")
def recurring_titles():
    return {"created": recurring.generate_all()}
