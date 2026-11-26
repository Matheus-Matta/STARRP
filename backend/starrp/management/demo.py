"""Dados de demonstração nunca entram em produção (R4-26): criam usuários com senha pública (o código é aberto)."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class DemoCommand(BaseCommand):
    def execute(self, *args, **options):
        if not settings.DEBUG and settings.ENVIRONMENT == "production":
            raise CommandError("Comando de demonstração: não roda em produção (DJANGO_ENV=production).")
        return super().execute(*args, **options)
