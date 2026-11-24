"""Lançamentos controlados da carteira de crédito do cliente."""
from django.db import transaction

from starrp.models import Customer, CustomerCredit


@transaction.atomic
def grant(customer, user, *, amount, reason):
    """Concede crédito avulso; a permissão específica é conferida pela API."""
    customer = Customer.all_objects.select_for_update().get(pk=customer.pk)
    return CustomerCredit.all_objects.create(
        account_id=customer.account_id,
        customer=customer,
        kind=CustomerCredit.Kind.ADJUSTMENT,
        amount=amount,
        notes=reason,
        created_by=user,
        updated_by=user,
    )
