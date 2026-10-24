from django.core.management.base import BaseCommand

from starrp.models import Account, Store
from starrp.services.finance_setup import ensure_defaults, vault_for
from starrp.services.provisioning import ensure_system_roles, sync_permissions


class Command(BaseCommand):
    help = (
        "Atualiza o catálogo de permissões, os cargos de sistema e os padrões do financeiro "
        "(plano de contas, banco, adquirente e cofre de cada loja) de todas as contas. Idempotente."
    )

    def handle(self, *args, **options):
        sync_permissions()
        for account in Account.objects.all():
            ensure_system_roles(account)
            ensure_defaults(account)
            for store in Store.all_objects.filter(account=account, deleted_at__isnull=True):
                vault_for(store)
        self.stdout.write(self.style.SUCCESS("Permissões, cargos e padrões do financeiro atualizados."))
