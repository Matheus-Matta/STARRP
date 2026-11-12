"""Rodadas no worker: tudo o que está dentro das regras, em lotes, com uma pausa entre eles (ver `settings.PRICE_BATCH_*`).

Quem clica em "Ler o mercado agora" ou "Analisar agora" não espera: a rodada vira uma tarefa (`BackgroundTask`, em
Configurações → Tarefas), os itens vão sendo criados na lista a cada lote e dá para parar. A pausa evita bloqueio nas
fontes externas. Uma rodada por conta e tipo: o segundo clique só mostra a que está em andamento.

Sem Redis não há worker: a rodada roda numa thread, para a tela funcionar igual em desenvolvimento.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.db import connections
from django.utils import timezone
from kombu.exceptions import OperationalError

from starrp.core.errors import BusinessError
from starrp.models import Account, BackgroundTask
from starrp.services import background

logger = logging.getLogger(__name__)

IDLE = {"running": False, "done": 0, "total": 0, "task": None}
Kind = BackgroundTask.Kind


@dataclass(frozen=True)
class Job:
    total: Callable  # (conta, início) → quantos itens entram nesta rodada
    next: Callable  # (conta, início, tamanho) → os próximos itens
    process: Callable  # (conta, itens) → cria os processos e lê
    before: Callable = None  # (conta, início) → o que se faz uma vez, antes do 1º lote; devolve um aviso, se houver
    after: Callable = None  # (conta, tarefa) → o que se faz uma vez, quando a rodada termina inteira


def _jobs():
    from starrp.services.market import tracker
    from starrp.services.seo import analyzer

    return {Kind.PRICE_ROUND: Job(tracker.batch_total, tracker.batch_next, tracker.batch_process),
            Kind.SEO_ROUND: Job(analyzer.batch_total, analyzer.batch_next, analyzer.batch_process, analyzer.batch_before, analyzer.batch_after)}


def _state(task):
    return {"running": True, "done": task.done, "total": task.total, "task": str(task.pk)}


def status(kind, account):
    task = background.active(account, kind)
    return _state(task) if task else dict(IDLE)


def _dispatch(task):
    from starrp.tasks.batches import batch_step

    if settings.PRICE_READ_IN_THREAD:
        threading.Thread(target=_loop, args=(str(task.pk),), daemon=True).start()
    else:
        batch_step.delay(str(task.pk))


def _loop(task_id):
    try:
        while step(task_id):
            time.sleep(settings.PRICE_BATCH_PAUSE)
    finally:
        connections.close_all()


def start(kind, account, cap=None, user=None):
    """Começa a rodada da conta. Já em andamento: devolve a que está rodando. Nada na vez: `total` zero."""
    running = status(kind, account)
    if running["running"]:
        return running
    total = _jobs()[kind].total(account, timezone.now())
    total = min(total, cap) if cap else total
    if not total:
        return dict(IDLE)
    task = background.begin(account, kind, total, user)
    if task is None:  # outro clique chegou antes
        return status(kind, account)
    state = _state(task)  # o que começou, mesmo que já termine antes da resposta
    try:
        _dispatch(task)
    except OperationalError as error:
        background.fail(task.pk, "A fila está fora do ar. Tente de novo em instantes.")
        logger.exception("Rodada %s: fila fora do ar", kind)
        raise BusinessError("A fila está fora do ar. Tente de novo em instantes.", code="batch_queue_down") from error
    return state


def step(task_id):
    """Um lote. Devolve se ainda há o que fazer. Parada ou com erro, a rodada termina aqui e a conta não fica presa."""
    task = BackgroundTask.all_objects.filter(pk=task_id, status=BackgroundTask.Status.RUNNING).first()
    if task is None:
        return False
    try:
        job, account = _jobs()[task.kind], Account.objects.get(pk=task.account_id)
        if job.before and not task.done:
            warning = job.before(account, task.started_at)
            if warning:
                background.note(task.pk, warning)
        rows = job.next(account, task.started_at, min(settings.PRICE_BATCH_SIZE, task.total - task.done))
        if not rows:
            background.complete(task.pk)
            return False
        job.process(account, rows)
    except Exception:  # noqa: BLE001
        logger.exception("Rodada %s: falha", task_id)
        background.fail(task.pk)
        return False
    done = task.done + len(rows)  # conta quem falhou também: a rodada sempre termina
    background.advance(task.pk, done)
    if done >= task.total:
        background.complete(task.pk)
        if job.after:
            try:
                job.after(account, task)
            except Exception:  # noqa: BLE001 — o aviso nunca desfaz o trabalho feito
                logger.exception("Rodada %s: falha no fim", task_id)
        return False
    return BackgroundTask.all_objects.filter(pk=task_id, status=BackgroundTask.Status.RUNNING).exists()
