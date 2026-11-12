"""Precificação no worker: a varredura de hora em hora e as leituras pedidas pela tela (ver services/market/tracker.py)."""
from celery import shared_task
from django.db import connections

from starrp.services import background
from starrp.services.market import tracker


@shared_task(name="starrp.price_tracking")
def price_tracking():
    return {"checked": tracker.run()}


@shared_task(name="starrp.price_read")
def price_read(account_id, variant_ids, task_id=None):
    try:
        done = tracker.read_variants(account_id, variant_ids)
        if task_id:
            background.complete(task_id, done)
        return {"checked": done}
    except Exception:
        if task_id:
            background.fail(task_id)
        raise
    finally:
        connections.close_all()  # sem Redis roda numa thread, que não devolve a conexão sozinha
