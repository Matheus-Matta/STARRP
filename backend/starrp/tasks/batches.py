"""As rodadas em lotes no worker (ver services/batches.py). Cada lote agenda o próximo depois da pausa."""
from celery import shared_task
from django.conf import settings

from starrp.services import batches


@shared_task(name="starrp.batch_step")
def batch_step(task_id):
    if batches.step(task_id):
        batch_step.apply_async((task_id,), countdown=settings.PRICE_BATCH_PAUSE)
