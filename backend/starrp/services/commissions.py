"""Pagamento de comissões: fecha as pendentes de um vendedor até uma data.

Marca as comissões como pagas e lança UMA saída na conta escolhida, categoria
"Comissões". Estornos de devolução (linhas negativas) entram na conta: paga-se
o líquido.
"""
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from starrp.core.errors import BusinessError
from starrp.models import Commission
from starrp.services import ledger
from starrp.services.store_access import scope_to_allowed


@transaction.atomic
def pay(account, seller, financial_account, user, *, until=None, store=None):
    until = until or timezone.localdate()
    pending = Commission.all_objects.select_for_update().filter(
        account=account, seller=seller, status=Commission.Status.PENDING, created_at__date__lte=until
    )
    # Sem filial ativa: só as filiais de quem paga (R2-04: o gerente de uma pagava as de todas).
    pending = pending.filter(store=store) if store is not None else scope_to_allowed(pending)
    # Soma as MESMAS linhas travadas (R4-19): um `aggregate` descarta a trava, e outro pagamento entrava no meio.
    rows = list(pending.order_by("pk").values_list("pk", "amount"))
    total = sum((amount for _pk, amount in rows), Decimal("0"))
    if total <= 0:
        raise BusinessError("Não há comissão a pagar para este vendedor no período.")
    ids = [pk for pk, _amount in rows]
    name = seller.get_full_name() or seller.username
    tx = ledger.post(financial_account, ledger.OUT, total, category_key="commissions", user=user,
                     description=f"Comissões de {name} até {until:%d/%m/%Y}",
                     source_key=f"commission_payout:{seller.pk}:{uuid.uuid4()}")
    Commission.all_objects.filter(pk__in=ids).update(status=Commission.Status.PAID, paid_at=timezone.now(), payout=tx)
    return {"seller": name, "count": len(ids), "total": total, "transaction": str(tx.pk)}
