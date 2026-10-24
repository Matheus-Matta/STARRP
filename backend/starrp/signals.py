"""Sinais do app. Regra de negócio NÃO mora aqui (fica em `services`)."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from starrp.models import Account


@receiver(post_save, sender=Account, dispatch_uid="starrp.account_system_data")
def account_created(sender, instance, created, **kwargs):
    """Conta nova já nasce com os dados fixos do sistema (formas de pagamento, perfis fiscais)."""
    if created:
        from starrp.services.system_data import ensure_system_data

        ensure_system_data(instance)
