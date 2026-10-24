from django.db import transaction

from starrp.models.system import NumberSequence


@transaction.atomic
def next_number(store, key):
    """Próximo número de `key` na loja. Chame dentro da transação que grava."""
    seq, _ = NumberSequence.objects.select_for_update().get_or_create(
        account_id=store.account_id, store=store, key=key
    )
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    return seq.last_value
