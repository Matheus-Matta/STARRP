"""Analítico de SEO no worker (ver services/seo/analyzer.py)."""
from celery import shared_task
from django.db import connections

from starrp.services import background
from starrp.services.seo import analyzer


@shared_task(name="starrp.seo_read")
def seo_read(account_id, product_ids, task_id=None):
    try:
        done = analyzer.read_products(account_id, product_ids)
        if task_id:
            background.complete(task_id, done)
        return {"checked": done}
    except Exception:
        if task_id:
            background.fail(task_id)
        raise
    finally:
        connections.close_all()  # sem Redis roda numa thread, que não devolve a conexão sozinha
