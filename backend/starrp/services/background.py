"""O registro das tarefas em segundo plano (ver models/background.py): nasce, anda, termina, falha ou é parada."""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from starrp.core.errors import StateConflict
from starrp.models import BackgroundTask

Status = BackgroundTask.Status
STALE_MIN = timedelta(minutes=15)  # sem sinal há mais tempo que isto: o worker caiu
STALLED = "O processo parou sem terminar. Inicie de novo; se repetir, confira se o worker está rodando."
FAILED = "A tarefa falhou. Tente de novo; se repetir, fale com o suporte."


def begin(account, kind, total, user=None):
    """Cria a tarefa. `None`: já existe uma rodada desse tipo em andamento na conta."""
    expire(account)
    try:
        with transaction.atomic():
            return BackgroundTask.all_objects.create(account_id=account.pk, kind=kind, total=total, started_by=user)
    except IntegrityError:
        return None


def expire(account):
    """Quem parou de dar sinal não fica "em andamento" para sempre nem trava uma rodada nova."""
    limit = timezone.now() - max(STALE_MIN, timedelta(seconds=settings.PRICE_BATCH_PAUSE * 3))
    BackgroundTask.all_objects.filter(account_id=account.pk, status=Status.RUNNING, updated_at__lt=limit, deleted_at__isnull=True).update(
        status=Status.FAILED, error=STALLED, finished_at=timezone.now(), updated_at=timezone.now())


def active(account, kind):
    expire(account)
    return BackgroundTask.all_objects.filter(account_id=account.pk, kind=kind, status=Status.RUNNING, deleted_at__isnull=True).first()


def advance(task_id, done):
    """O progresso e o sinal de vida. Atualiza mesmo se pararam a tarefa: conta o que este lote já fez."""
    BackgroundTask.all_objects.filter(pk=task_id).update(done=done, updated_at=timezone.now())


def note(task_id, text):
    """Um aviso que não para a tarefa: fica no campo do motivo."""
    BackgroundTask.all_objects.filter(pk=task_id).update(error=text[:300], updated_at=timezone.now())


def _end(task_id, status, **fields):
    """Só quem ainda está em andamento muda: quem já foi parada continua parada."""
    return BackgroundTask.all_objects.filter(pk=task_id, status=Status.RUNNING).update(
        status=status, finished_at=timezone.now(), updated_at=timezone.now(), **fields)


def complete(task_id, done=None):
    fields = {} if done is None else {"done": done}
    _end(task_id, Status.COMPLETED, **fields)


def fail(task_id, error=FAILED):
    _end(task_id, Status.FAILED, error=error[:300])


def stop(task):
    """Vale na hora: o lote em andamento termina, e o próximo não começa."""
    if not task.can_stop:
        raise StateConflict("Esta tarefa não está em andamento ou não pode ser parada.")
    _end(task.pk, Status.STOPPED)
    task.refresh_from_db()
    return task
