"""Garante os dados fixos (formas de pagamento, perfis fiscais) em TODAS as contas.

Conta nova já recebe pelo sinal; este comando cobre as que existiam antes e é
seguro rodar sempre (só cria o que falta, não mexe no que a loja ajustou).
"""
from django.core.management.base import BaseCommand

from starrp.models import Account
from starrp.services.system_data import ensure_system_data


class Command(BaseCommand):
    help = "Cria as formas de pagamento e os perfis fiscais que faltam em cada conta."

    def handle(self, *args, **options):
        for account in Account.objects.all():
            ensure_system_data(account)
            self.stdout.write(f"{account.name}: ok")
