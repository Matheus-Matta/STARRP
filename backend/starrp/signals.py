"""Sinais do app. Regra de negócio NÃO mora aqui (fica em `services`)."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from starrp.models import Account, Customer, Product, ProductVariant, Sale, Supplier


@receiver(post_save, sender=Account, dispatch_uid="starrp.account_system_data")
def account_created(sender, instance, created, **kwargs):
    """Conta nova já nasce com os dados fixos do sistema (formas de pagamento, perfis fiscais)."""
    if created:
        from starrp.services.system_data import ensure_system_data

        ensure_system_data(instance)


@receiver(post_save, dispatch_uid="starrp.cosmos_supervision")
def cosmos_supervision(sender, instance, raw=False, **kwargs):
    """Supervisão da Cosmos: confere o registro depois que a gravação vingar (ver `services/cosmos/supervision`)."""
    if raw or sender not in (Customer, Supplier, Product, ProductVariant, Sale):
        return
    from starrp.services.cosmos.supervision import check_instance

    transaction.on_commit(lambda: check_instance(instance), robust=True)
