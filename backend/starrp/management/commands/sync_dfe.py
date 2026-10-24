"""Busca as notas de entrada na SEFAZ sem Celery (cron): `python manage.py sync_dfe`."""
from django.core.management.base import BaseCommand

from starrp.services import dfe


class Command(BaseCommand):
    help = "Busca na SEFAZ (DF-e) as notas emitidas contra os CNPJs dos dados fiscais."

    def handle(self, *args, **options):
        for config, result in dfe.sync_all().items():
            self.stdout.write(f"{config}: {result}")
