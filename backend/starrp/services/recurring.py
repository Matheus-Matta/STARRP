"""Contas recorrentes: um título por vencimento, gerado sozinho (Celery, todo dia) ou pelo botão "Gerar agora".

Os vencimentos seguem a mesma regra das parcelas (`finance.due_dates`): todo mês no `due_day`, toda
semana no `due_weekday` ou todo dia, a partir de `start_date`. Cada título nasce `lead_days` antes do
vencimento, com competência (`issue_date`) na data do vencimento; o par (recorrência, vencimento) é
único: rodar de novo nunca duplica. `next_period` guarda o próximo vencimento a gerar.
"""
import logging
from datetime import timedelta
from itertools import islice

from django.db import IntegrityError, transaction
from django.utils import timezone

from starrp.models import Account, FinancialTitle, RecurringTitle
from starrp.services import finance
from starrp.services.store_access import scope_to_allowed


logger = logging.getLogger(__name__)
MAX_PER_RUN = 120


def _dates(rec):
    start = rec.next_period or rec.start_date
    for due in finance.due_dates(start, frequency=rec.frequency, due_day=rec.due_day, due_weekday=rec.due_weekday):
        if rec.end_date and due > rec.end_date:
            return
        yield due


def _label(rec, due):
    return f"{due:%m/%Y}" if rec.frequency == "monthly" else f"{due:%d/%m/%Y}"


@transaction.atomic
def generate_one(rec, today=None, user=None):
    """Gera os títulos que já estão na janela (`lead_days` antes do vencimento). Devolve os criados."""
    rec = RecurringTitle.all_objects.select_for_update().get(pk=rec.pk)
    today = today or timezone.localdate()
    created, next_due = [], None
    if not rec.is_active or rec.deleted_at is not None:
        return created
    for due in _dates(rec):
        if len(created) >= MAX_PER_RUN:  # o resto sai na próxima rodada (data antiga demais não trava o banco)
            next_due = due
            break
        if due - timedelta(days=rec.lead_days) > today:
            next_due = due
            break
        if not FinancialTitle.all_objects.filter(recurring=rec, recurring_period=due, deleted_at__isnull=True).exists():
            try:
                with transaction.atomic():
                    created.append(finance.create_title(
                        store=rec.store, kind=rec.kind, total=rec.amount, first_due=due, user=user or rec.created_by,
                        description=f"{rec.description} - {_label(rec, due)}", customer=rec.customer,
                        supplier=rec.supplier, category=rec.category, recurring=rec, recurring_period=due,
                        issue_date=due, due_time=rec.due_time, fine_percent=rec.fine_percent,
                        interest_percent=rec.interest_percent,
                    ))
            except IntegrityError:
                pass  # outro processo gerou o mesmo vencimento
        next_due = due + timedelta(days=1)
    rec.next_period = next_due
    if next_due is None:  # passou do fim
        rec.is_active = False
    rec.save(update_fields=["next_period", "is_active", "updated_at"])
    return created


def generate_all(account=None, today=None):
    """Todas as recorrências ativas (da conta, ou de todas): o que a tarefa diária chama."""
    qs = RecurringTitle.all_objects.filter(is_active=True, deleted_at__isnull=True,
                                                  account__status=Account.Status.ACTIVE)
    if account is not None:
        qs = scope_to_allowed(qs.filter(account=account))  # pela tela: só as filiais de quem pediu (M-12)
    total = 0
    for rec in qs:
        try:  # o erro de uma recorrência não pode parar as seguintes (nem as de outras contas)
            total += len(generate_one(rec, today))
        except Exception:  # noqa: BLE001
            logger.exception("Recorrência %s não gerada", rec.pk)
    return total


def upcoming(rec, count=3):
    """Os próximos vencimentos (para a tela mostrar o que vem)."""
    return list(islice(_dates(rec), count))
