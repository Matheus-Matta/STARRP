from django.core.management.base import BaseCommand

from starrp.models.platform import Module
from starrp.services.provisioning import create_account


class Command(BaseCommand):
    help = "Cria uma conta pronta para vender: loja, depósito, caixa, formas de pagamento e admin."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--admin", required=True, help="Usuário administrador.")
        parser.add_argument("--password", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument("--store", default=None, help="Nome da primeira loja (padrão: nome da conta).")
        parser.add_argument("--document", default="")
        parser.add_argument("--all-modules", action="store_true",
                            help="Liga todos os módulos opcionais (conta de demonstração/teste).")

    def handle(self, *args, **options):
        account, store, user = create_account(
            name=options["name"], admin_username=options["admin"], admin_password=options["password"],
            admin_email=options["email"], store_name=options["store"], document=options["document"],
        )
        if options["all_modules"]:
            account.extra_modules = [m.value for m in Module if m != Module.BASE]
            account.save(update_fields=["extra_modules", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Conta {account.slug} ({account.id}), loja {store.id}, admin {user}."))
