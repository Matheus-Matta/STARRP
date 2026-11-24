from django.apps import AppConfig


class StarrpConfig(AppConfig):
    name = "starrp"
    verbose_name = "Starrp ERP"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from starrp import signals  # noqa: F401
        from starrp.core import dry_run

        dry_run.install()  # ensaio da Cosmos sem efeito externo (S-05)
        from starrp.core import schema  # noqa: F401
