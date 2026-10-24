"""Busca periódica das notas de entrada na SEFAZ (a cada hora, o mínimo que a SEFAZ aceita)."""
from celery import shared_task

from starrp.services import dfe


@shared_task(name="starrp.sync_dfe")
def sync_dfe():
    return {key: {k: str(v) for k, v in value.items()} for key, value in dfe.sync_all().items()}
