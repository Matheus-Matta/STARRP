"""Pagamento de comissões: fecha as pendentes de um vendedor até uma data.

Marca as comissões como pagas e lança UMA saída na conta escolhida, categoria
"Comissões". Estornos de devolução (linhas negativas) entram na conta: paga-se
o líquido.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.models import Commission
from starrp.services import ledger


@transaction.atomic
def pay(account, seller, financial_account, user, *, until=None, store=None):
    until = until or timezone.localdate()
    pending = Commission.all_objects.select_for_update().filter(
        account=account, seller=seller, status=Commission.Status.PENDING, created_at__date__lte=until
    )
    if store is not None:
        pending = pending.filter(store=store)
    total = pending.aggregate(t=Sum("amount"))["t"] or Decimal("0")
    if total <= 0:
        raise BusinessError("Não há comissão a pagar para este vendedor no período.")
    ids = list(pending.values_list("pk", flat=True))
    name = seller.get_full_name() or seller.username
    tx = ledger.post(financial_account, ledger.OUT, total, category_key="commissions", user=user,
                     description=f"Comissões de {name} até {until:%d/%m/%Y}",
                     source_key=f"commission_payout:{seller.pk}:{until}:{len(ids)}:{ids[0]}")
    Commission.all_objects.filter(pk__in=ids).update(status=Commission.Status.PAID, paid_at=timezone.now())
    return {"seller": name, "count": len(ids), "total": total, "transaction": str(tx.pk)}
