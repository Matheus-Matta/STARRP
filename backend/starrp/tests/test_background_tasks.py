"""Tarefas em segundo plano: histórico, progresso, parar e isolamento entre contas."""
from datetime import timedelta

import pytest
from django.utils import timezone

from starrp.models import BackgroundTask, SeoCheck
from starrp.services import background, batches
from starrp.services.seo import analyzer
from starrp.tasks import batches as batch_tasks
from starrp.tasks import seo as seo_tasks

TASKS = "/api/v1/background-tasks/"
SEO = "/api/v1/seo-checks/"
Kind, Status = BackgroundTask.Kind, BackgroundTask.Status


@pytest.fixture(autouse=True)
def _modules(request):
    if "ctx" in request.fixturenames:
        ctx = request.getfixturevalue("ctx")
        ctx.account.extra_modules = ["seo", "pricing"]
        ctx.account.save(update_fields=["extra_modules"])


@pytest.fixture
def queue(monkeypatch, settings):
    """Segura os lotes: cada um roda quando o teste mandar."""
    settings.PRICE_BATCH_SIZE, settings.PRICE_BATCH_PAUSE = 2, 45
    sent = []
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: sent.append(args))
    monkeypatch.setattr(batch_tasks.batch_step, "apply_async", lambda args, countdown: sent.append(args))
    return sent


def _products(ctx, count=5):
    return [ctx.product(f"Produto {i} Teste", price="10", sku=f"T{i}").product for i in range(count)]


def test_rodada_vira_tarefa_com_progresso_ate_concluir(ctx, queue):
    _products(ctx)
    api = ctx.client()
    state = api.post(f"{SEO}run/").json()
    task = api.get(f"{TASKS}{state['task']}/").json()
    assert task["status"] == "running" and task["status_display"] == "Em andamento" and task["total"] == 5
    assert task["percent"] == 0 and task["can_stop"] is True and task["started_by_name"] and task["finished_at"] is None

    batch_tasks.batch_step(state["task"])
    task = api.get(f"{TASKS}{state['task']}/").json()
    assert task["done"] == 2 and task["percent"] == 40 and task["status"] == "running"

    batch_tasks.batch_step(state["task"])
    batch_tasks.batch_step(state["task"])
    task = api.get(f"{TASKS}{state['task']}/").json()
    assert task["status"] == "completed" and task["done"] == 5 and task["percent"] == 100
    assert task["finished_at"] and task["can_stop"] is False
    assert api.get(f"{SEO}run-status/").json()["running"] is False


def test_parar_vale_na_hora_e_nenhum_lote_novo_roda(ctx, queue):
    _products(ctx)
    api = ctx.client()
    pk = api.post(f"{SEO}run/").json()["task"]
    batch_tasks.batch_step(pk)
    assert SeoCheck.all_objects.count() == 2
    stopped = api.post(f"{TASKS}{pk}/stop/")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped" and stopped.json()["finished_at"]
    batch_tasks.batch_step(pk)
    assert SeoCheck.all_objects.count() == 2 and api.get(f"{TASKS}{pk}/").json()["done"] == 2
    assert api.post(f"{TASKS}{pk}/stop/").status_code == 409
    assert api.get(f"{SEO}run-status/").json()["running"] is False


def test_parar_durante_o_lote_nao_vira_concluida_nem_agenda_outro(ctx, queue, monkeypatch):
    _products(ctx)
    api = ctx.client()
    pk = api.post(f"{SEO}run/").json()["task"]
    queue.clear()
    original = analyzer.batch_process

    def stopping(account, rows):
        original(account, rows)
        background.stop(BackgroundTask.all_objects.get(pk=pk))

    monkeypatch.setattr(analyzer, "batch_process", stopping)
    batch_tasks.batch_step(pk)
    task = api.get(f"{TASKS}{pk}/").json()
    assert task["status"] == "stopped" and task["done"] == 2 and not queue


def test_depois_de_parar_pode_comecar_outra_rodada(ctx, queue):
    _products(ctx)
    api = ctx.client()
    first = api.post(f"{SEO}run/").json()["task"]
    assert api.post(f"{SEO}run/").json()["task"] == first  # uma por vez
    api.post(f"{TASKS}{first}/stop/")
    second = api.post(f"{SEO}run/").json()["task"]
    assert second != first and BackgroundTask.all_objects.filter(status=Status.RUNNING).count() == 1


def test_erro_vira_falha_com_motivo_que_nao_expoe_detalhe(ctx, queue, monkeypatch):
    _products(ctx)
    api = ctx.client()
    pk = api.post(f"{SEO}run/").json()["task"]

    def boom(account, rows):
        raise RuntimeError("chave-secreta bright data")

    monkeypatch.setattr(analyzer, "batch_process", boom)
    batch_tasks.batch_step(pk)
    task = api.get(f"{TASKS}{pk}/").json()
    assert task["status"] == "failed" and task["status_display"] == "Falha" and "falhou" in task["error"]
    assert "secreta" not in str(task) and "bright" not in str(task).lower()


def test_worker_caido_vira_falha_e_nao_trava_nova_rodada(ctx, queue):
    _products(ctx)
    api = ctx.client()
    pk = api.post(f"{SEO}run/").json()["task"]
    BackgroundTask.all_objects.filter(pk=pk).update(updated_at=timezone.now() - timedelta(hours=1))
    task = api.get(f"{TASKS}{pk}/").json()
    assert task["status"] == "failed" and "parou" in task["error"]
    assert api.post(f"{SEO}run/").json()["task"] != pk


def test_clique_em_um_produto_tambem_aparece_nas_tarefas(ctx, monkeypatch):
    sent = []
    monkeypatch.setattr(seo_tasks.seo_read, "delay", lambda *args: sent.append(args))
    product = _products(ctx, 1)[0]
    api = ctx.client()
    api.post(f"{SEO}product/", {"product": str(product.pk)}, format="json")
    row = api.get(TASKS).json()["results"][0]
    assert row["kind"] == "seo_read" and row["status"] == "running" and row["total"] == 1 and row["can_stop"] is False
    assert row["started_by_name"]
    seo_tasks.seo_read(*sent[0])
    row = api.get(TASKS).json()["results"][0]
    assert row["status"] == "completed" and row["done"] == 1


def test_varredura_automatica_aparece_como_automatica(ctx, monkeypatch, settings):
    monkeypatch.setattr(batch_tasks.batch_step, "delay", lambda *args: None)
    settings.SERPAPI_KEY = "k"
    _products(ctx, 1)
    ctx.account.price_tracking_enabled, ctx.account.price_sources = True, ["manual"]
    ctx.account.save()
    from starrp.services.market import tracker

    assert tracker.run() == 1
    assert ctx.client().get(TASKS).json()["results"][0]["started_by_name"] == "Automática"


def test_filtro_e_ordem_mais_nova_primeiro(ctx):
    old = background.begin(ctx.account, Kind.SEO_READ, 1)
    background.complete(old.pk, 1)
    new = background.begin(ctx.account, Kind.SEO_READ, 1)
    api = ctx.client()
    assert [row["id"] for row in api.get(TASKS).json()["results"]][:2] == [str(new.pk), str(old.pk)]
    assert [row["id"] for row in api.get(TASKS, {"status": "running"}).json()["results"]] == [str(new.pk)]


def test_uma_conta_nao_ve_nem_para_a_tarefa_da_outra(ctx, other):
    alheia = background.begin(other.account, Kind.SEO_ROUND, 3)
    api = ctx.client()
    assert api.get(TASKS).json()["results"] == []
    assert api.get(f"{TASKS}{alheia.pk}/").status_code == 404
    assert api.post(f"{TASKS}{alheia.pk}/stop/").status_code == 404
    alheia.refresh_from_db()
    assert alheia.status == Status.RUNNING


def test_quem_so_ve_nao_para_e_sem_login_nao_entra(ctx):
    task = background.begin(ctx.account, Kind.SEO_ROUND, 3)
    auditor = ctx.client(ctx.user("auditor-tarefa", "auditor"))
    assert auditor.get(f"{TASKS}{task.pk}/").status_code == 200
    assert auditor.post(f"{TASKS}{task.pk}/stop/").status_code == 403
    from rest_framework.test import APIClient

    assert APIClient().get(f"{TASKS}{task.pk}/").status_code == 401


def test_tarefa_nao_e_criada_nem_alterada_pela_api(ctx):
    task = background.begin(ctx.account, Kind.SEO_ROUND, 3)
    api = ctx.client()
    assert api.post(TASKS, {"kind": "seo_round"}, format="json").status_code == 422
    assert api.patch(f"{TASKS}{task.pk}/", {"status": "completed"}, format="json").status_code == 405
    assert api.delete(f"{TASKS}{task.pk}/").status_code == 405


def test_fila_fora_do_ar_marca_falha_e_avisa(ctx, monkeypatch):
    from kombu.exceptions import OperationalError

    def down(*args):
        raise OperationalError("sem redis")

    monkeypatch.setattr(batch_tasks.batch_step, "delay", down)
    _products(ctx)
    response = ctx.client().post(f"{SEO}run/")
    assert response.status_code == 422 and "fila" in str(response.json())
    assert BackgroundTask.all_objects.get(account=ctx.account).status == Status.FAILED
    assert batches.status(Kind.SEO_ROUND, ctx.account)["running"] is False
