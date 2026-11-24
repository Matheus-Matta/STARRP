"""Sinais do app. Regra de negócio NÃO mora aqui (fica em `services`)."""

from django.db import transaction
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from starrp.models import Account, Customer, Product, ProductVariant, Sale, Supplier, UserProfile


@receiver(post_save, sender=Account, dispatch_uid="starrp.account_system_data")
def account_created(sender, instance, created, **kwargs):
    """Conta nova já nasce com os dados fixos do sistema (formas de pagamento, perfis fiscais)."""
    if created:
        from starrp.services.system_data import ensure_system_data

        ensure_system_data(instance)


SUPERVISED = (Customer, Supplier, Product, ProductVariant, Sale)


def _already_moved():
    """Lugar antigo de uma conferência que foi para o fim da fila (ver `cosmos_supervision`)."""


def _supervise(model, pk):
    from starrp.services.cosmos.supervision import check_instance

    # Relê do banco: o objeto do save() pode ser de um estado intermediário (a venda é salva no
    # pagamento e de novo na conclusão; o que vale é como ela terminou).
    instance = model.all_objects.select_related("account").filter(pk=pk).first()
    if instance is not None:
        check_instance(instance)


@receiver(post_save, dispatch_uid="starrp.cosmos_supervision")
def cosmos_supervision(sender, instance, raw=False, **kwargs):
    """Supervisão da Cosmos: confere o registro depois que a gravação vingar (ver `services/cosmos/supervision`).

    UMA conferência por registro e transação: antes, cada save() agendava a sua (um checkout salva a
    venda várias vezes) e cada uma olhava o objeto no estado daquele save."""
    if raw or sender not in SUPERVISED:
        return
    key = (sender, instance.pk)

    def run():
        _supervise(sender, instance.pk)

    run.supervision_key = key
    connection = transaction.get_connection()
    if connection.in_atomic_block:
        queue = connection.run_on_commit  # [(savepoints, func, robust)] — fila do Django para o commit
        for index, (savepoints, func, robust) in enumerate(queue):
            if getattr(func, "supervision_key", None) == key:
                # Já agendada: vai para o fim da fila (roda uma vez, depois das outras gravações),
                # mantendo os savepoints da primeira (desfazer um savepoint posterior não a perde).
                queue[index] = (savepoints, _already_moved, robust)
                queue.append((savepoints, run, robust))
                return
    transaction.on_commit(run, robust=True)


@receiver(m2m_changed, sender=UserProfile.extra_roles.through, dispatch_uid="starrp.profile_roles_changed")
@receiver(m2m_changed, sender=UserProfile.extra_permissions.through, dispatch_uid="starrp.profile_perms_changed")
def profile_access_changed(sender, instance, action, **kwargs):
    """Cargos/permissões extras mudaram: o perfil recalcula na próxima checagem."""
    if action.startswith("post_") and isinstance(instance, UserProfile):
        instance.clear_access_cache()
