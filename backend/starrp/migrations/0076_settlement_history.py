"""Baixas que já existem viram linha própria (na data que a parcela tem) e o crédito usado que veio de lançamento com
categoria deixa de ficar negativo (a regra passou a ser "só sem categoria")."""
from decimal import Decimal

from django.db import migrations
from django.db.models import Sum

ZERO = Decimal("0")


def fill(apps, _schema_editor):
    Installment, Settlement = apps.get_model("starrp", "Installment"), apps.get_model("starrp", "InstallmentSettlement")
    rows = []
    paid = Installment._base_manager.filter(paid_at__isnull=False, paid_amount__gt=0, deleted_at__isnull=True,
                                            settlements__isnull=True)  # rodada de novo, não duplica
    for part in paid.iterator(chunk_size=500):
        rows.append(Settlement(account_id=part.account_id, installment_id=part.pk, date=part.paid_at,
                               amount=part.paid_amount - part.credit_used, interest=part.interest, fine=part.fine,
                               discount=part.discount, credit=part.credit_used))
        if len(rows) >= 500:
            Settlement._base_manager.bulk_create(rows)
            rows = []
    Settlement._base_manager.bulk_create(rows)


def settle_credit(apps, _schema_editor):
    Installment, Tx = apps.get_model("starrp", "Installment"), apps.get_model("starrp", "FinancialTransaction")
    for field, given in (("customer_id", "in"), ("supplier_id", "out")):
        used = (Installment._base_manager.filter(credit_used__gt=0, deleted_at__isnull=True)
                .exclude(**{f"title__{field}": None}).order_by().values_list(f"title__{field}").annotate(t=Sum("credit_used")))
        for party, total in list(used):
            free = Tx._base_manager.filter(**{field: party}, installment__isnull=True, category__isnull=True,
                                           deleted_at__isnull=True)
            have = sum((a if kind == given else -a for kind, a in free.values_list("kind", "amount")), ZERO)
            excess = total - max(have, ZERO)
            parts = Installment._base_manager.filter(**{f"title__{field}": party}, credit_used__gt=0, deleted_at__isnull=True)
            for part in parts.order_by("paid_at", "created_at"):
                if excess <= 0:
                    break
                cut = min(part.credit_used, excess)
                Installment._base_manager.filter(pk=part.pk).update(credit_used=part.credit_used - cut)
                excess -= cut


class Migration(migrations.Migration):

    dependencies = [("starrp", "0075_installment_settlement")]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop),
                  migrations.RunPython(settle_credit, migrations.RunPython.noop)]
