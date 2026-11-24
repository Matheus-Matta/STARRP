"""Limpeza diária das tabelas que só crescem (ver `services/housekeeping.py`)."""
from celery import shared_task

from starrp.services import housekeeping


@shared_task(name="starrp.housekeeping")
def housekeeping_task():
    return housekeeping.run()
