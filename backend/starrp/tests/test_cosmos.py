"""Cosmos (assistente de IA): ferramentas, confirmação das gravações, relatórios e supervisão.

O modelo da OpenAI é simulado (`FakeOpenAI`): o que se testa é o que o Starrp faz com as
respostas dele — e que nada é gravado sem o usuário confirmar.
"""
import io
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import override_settings
from openpyxl import load_workbook

from config.asgi import application
from starrp.models import (
    AuditLog, Brand, CosmosAction, CosmosAttachment, CosmosConversation, CosmosFinding, CosmosMessage, Customer,
    UserProfile,
)
from starrp.services.cosmos import agent, bridge, datasets, prompts, report, supervision, tools



@pytest.fixture(autouse=True)
def _cosmos_module(request):
    """A Cosmos é módulo: estes testes partem de uma conta que tem."""
    for name in ("ctx", "other"):
        if name in request.fixturenames:
            account = request.getfixturevalue(name).account
            account.extra_modules = sorted({*(account.extra_modules or []), "cosmos"})
            account.save(update_fields=["extra_modules"])


def _rows(table):
    """A saída em tabela das ferramentas ({colunas, linhas}) de volta a uma lista de objetos."""
    return [dict(zip(table["colunas"], row, strict=False)) for row in table["linhas"]]


def _actor(ctx, user=None):
    return bridge.actor_for(user or ctx.admin, str(ctx.store.pk))


def _ctx(ctx, user=None):
    actor = _actor(ctx, user)
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=actor.user, title="Teste")
    return tools.ToolContext(actor=actor, conversation=conversation)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Contadores da Cosmos (mensagens por minuto, varredura, parar) não passam de um teste para outro."""
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def sent(monkeypatch):
    """O que iria para o WebSocket do usuário."""
    out = []
    monkeypatch.setattr("starrp.services.cosmos.events.send", lambda user_id, event: out.append((user_id, event)))
    return out


# ── modelo simulado ──────────────────────────────────────────────────────────
def _chunk(content=None, calls=None):
    delta = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _call(name, arguments, call_id="call_1"):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return _chunk(calls=[SimpleNamespace(index=0, id=call_id, function=function)])


class FakeOpenAI:
    """Devolve as respostas na ordem; guarda o que recebeu."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return iter(self.replies.pop(0))


@pytest.fixture
def model(monkeypatch, settings):
    settings.OPENAI_API_KEY = "sk-test"

    def use(*replies):
        fake = FakeOpenAI(*replies)
        monkeypatch.setattr(agent, "_client", lambda: fake)
        return fake
    return use


# ── ferramentas ──────────────────────────────────────────────────────────────
def test_consulta_pela_api_respeita_a_conta(ctx, other):
    Brand.all_objects.create(account=ctx.account, name="Aurora")
    Brand.all_objects.create(account=other.account, name="Da Outra Conta")
    out = json.loads(tools.run(_ctx(ctx), "consultar_api", {"caminho": "/catalog/brands/"}))
    results = out["dados"]["results"]
    names = [row["name"] for row in (results if isinstance(results, list) else _rows(results))]
    assert names == ["Aurora"]


def test_endpoints_bloqueados_e_sem_permissao(ctx):
    seller = ctx.user("vendedor1", "seller")
    profile = UserProfile.all_objects.get(user=seller)
    seller_ctx = _ctx(ctx, seller)
    # Vendedor não tem cosmos.manage: a ferramenta de gravação nem aparece para o modelo.
    assert "propor_alteracao" not in {d["function"]["name"] for d in tools.definitions(seller_ctx.actor)}
    assert json.loads(tools.run(seller_ctx, "propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/",
                                                                 "titulo": "x"}))["erro"]
    assert bridge.call(seller_ctx.actor, "POST", "/auth/login/", body={}).status == 403
    assert profile.pk  # o perfil existe; só falta a permissão


def test_proposta_invalida_volta_o_erro_e_nao_cria_acao(ctx):
    tool_ctx = _ctx(ctx)
    out = json.loads(tools.run(tool_ctx, "propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/",
                                                              "corpo": {}, "titulo": "Marca sem nome"}))
    assert out["status"] == 400
    assert not CosmosAction.all_objects.exists()
    assert not Brand.all_objects.filter(account=ctx.account).exists()  # a validação foi desfeita


def test_proposta_so_grava_quando_o_usuario_confirma(ctx, sent, model):
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/", "corpo": {"name": "Nova"},
                                             "titulo": "Cadastrar marca Nova",
                                             "campos": [{"rotulo": "Nome", "valor": "Nova"}]})
    action = CosmosAction.all_objects.get()
    assert action.status == CosmosAction.Status.PENDING
    assert not Brand.all_objects.filter(name="Nova").exists()
    assert tool_ctx.blocks[-1]["action"]["preview"] == [{"label": "Nome", "value": "Nova"}]

    model([_chunk("Pronto, a marca Nova foi cadastrada.")])
    agent.decide(ctx.admin.pk, str(action.pk), approve=True)

    action.refresh_from_db()
    brand = Brand.all_objects.get(account=ctx.account, name="Nova")
    assert action.status == CosmosAction.Status.EXECUTED
    assert action.result["id"] == str(brand.pk) and action.result["endpoint"] == "/catalog/brands/"
    assert brand.created_by == ctx.admin  # gravou COMO o usuário, com auditoria
    assert AuditLog.all_objects.filter(entity="brand", object_id=str(brand.pk), actor=ctx.admin).exists()
    kinds = [event["type"] for _, event in sent]
    assert "action" in kinds and "message" in kinds


def test_proposta_cancelada_nao_grava(ctx, sent):
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/", "corpo": {"name": "Nao"},
                                             "titulo": "Cadastrar"})
    action = CosmosAction.all_objects.get()
    agent.decide(ctx.admin.pk, str(action.pk), approve=False)
    action.refresh_from_db()
    assert action.status == CosmosAction.Status.REJECTED
    assert not Brand.all_objects.filter(name="Nao").exists()
    assert sent[-1][1]["type"] == "typing" and sent[-1][1]["on"] is False


def test_alteracao_mostra_de_para(ctx):
    brand = Brand.all_objects.create(account=ctx.account, name="Antiga")
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "propor_alteracao", {"metodo": "PATCH", "caminho": f"/catalog/brands/{brand.pk}/",
                                             "corpo": {"name": "Nova"}, "titulo": "Renomear"})
    preview = CosmosAction.all_objects.get().preview
    assert preview == [{"label": "Nome", "from": "Antiga", "value": "Nova"}]
    brand.refresh_from_db()
    assert brand.name == "Antiga"


def test_cartao_mostra_tudo_em_pt_br():
    assert tools._show("1234.90") == "1.234,90"
    assert tools._show("2026-11-02") == "02/11/2026"
    assert tools._show(True) == "Sim"
    assert tools._show([{"sku": "A"}, {"sku": "B"}]) == "2 itens"
    assert tools._label("is_active", {}) == "Ativo"
    assert tools._label("weird_field", {}) == "Weird field"


def test_proposta_usa_rotulos_do_modelo_pela_chave(ctx):
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "propor_alteracao", {
        "metodo": "POST", "caminho": "/catalog/brands/", "corpo": {"name": "Aurora", "is_active": True},
        "titulo": "Cadastrar marca", "campos": [{"chave": "name", "rotulo": "Nome da marca", "valor": "Aurora"},
                                                {"rotulo": "Observação", "valor": "Marca nova"}]})
    assert CosmosAction.all_objects.get().preview == [
        {"label": "Nome da marca", "value": "Aurora"}, {"label": "Ativo", "value": "Sim"},
        {"label": "Observação", "value": "Marca nova"}]


def test_botoes_substituem_e_param_em_cinco(ctx):
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "mostrar_botoes", {"botoes": [{"rotulo": "A", "tipo": "resposta", "valor": "a"}]})
    tools.run(tool_ctx, "mostrar_botoes", {"botoes": [
        {"rotulo": f"Opção {n}", "tipo": "resposta", "valor": str(n)} for n in (1, 1, 2, 3, 4, 5, 6, 7)]})
    groups = [b for b in tool_ctx.blocks if b["type"] == "buttons"]
    assert len(groups) == 1
    assert [b["label"] for b in groups[0]["buttons"]] == ["Opção 1", "Opção 2", "Opção 3", "Opção 4", "Opção 5"]


# ── conversa ─────────────────────────────────────────────────────────────────
def test_conversa_chama_ferramenta_e_responde(ctx, sent, model):
    Customer.all_objects.create(account=ctx.account, name="Ana", document="")
    fake = model([_call("consultar_dados", {"conjunto": "clientes", "medidas": ["quantidade"]})],
                 [_chunk("Você tem "), _chunk("1 cliente.")])

    agent.send_message(ctx.admin.pk, "Quantos clientes eu tenho?", store_id=str(ctx.store.pk))

    conversation = CosmosConversation.all_objects.get(user=ctx.admin)
    roles = list(conversation.messages.order_by("created_at").values_list("role", flat=True))
    assert roles == ["user", "assistant", "tool", "assistant"]
    tool_output = json.loads(conversation.messages.get(role="tool").content)
    assert tool_output["rows"] == [{"quantidade": 1}]
    assert conversation.messages.filter(role="assistant").last().content == "Você tem 1 cliente."
    # A 2ª volta levou a chamada e o resultado da ferramenta.
    assert [m["role"] for m in fake.requests[1]["messages"]][-2:] == ["assistant", "tool"]
    assert any(event["type"] == "delta" for _, event in sent)


def test_sem_chave_avisa_que_esta_desligada(ctx, sent, settings):
    settings.OPENAI_API_KEY = ""
    agent.send_message(ctx.admin.pk, "Oi", store_id=str(ctx.store.pk))
    last = CosmosMessage.all_objects.filter(role="assistant").last()
    assert "OPENAI_API_KEY" in last.content
    # Sem modelo também avisa que parou de digitar (senão o widget fica "digitando…" para sempre).
    assert sent[-1][1] == {"type": "typing", "conversation": str(last.conversation_id), "on": False}


def test_historico_nao_comeca_no_meio_de_uma_ferramenta(ctx):
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    make = CosmosMessage.all_objects.create
    make(account=ctx.account, conversation=conversation, role="tool", tool_call_id="x", content="{}")
    make(account=ctx.account, conversation=conversation, role="user", content="Oi")
    make(account=ctx.account, conversation=conversation, role="assistant", content="",
         tool_calls=[{"id": "sem-resposta", "type": "function", "function": {"name": "a", "arguments": "{}"}}])
    assert [m["role"] for m in agent._history(conversation)] == ["user"]


# ── relatórios ───────────────────────────────────────────────────────────────
def test_relatorio_montado_calcula_no_servidor_e_exporta_com_grafico(ctx):
    for name in ("Ana", "Bruno", "Carla"):
        Customer.all_objects.create(account=ctx.account, name=name, person_type="F")
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "montar_relatorio", {
        "titulo": "Clientes", "indicadores": [{"dataset": "clientes", "metric": "quantidade"}],
        "blocos": [{"type": "share", "title": "Por tipo", "dataset": "clientes", "metrics": ["quantidade"],
                    "group_by": ["tipo_pessoa"]}]})
    block = tool_ctx.blocks[-1]
    assert block["type"] == "report"
    assert block["report"]["kpis"][0]["value"] == 3
    assert block["report"]["blocks"][0]["rows"][0]["value"] == 3

    saved = report.CosmosReport.all_objects.get(pk=block["report"]["id"])
    content, _kind, name = report.export(saved, ctx.admin)
    assert name.endswith(".xlsx")
    sheet = load_workbook(io.BytesIO(content))["Por tipo"]
    assert len(sheet._charts) == 1


def test_download_do_relatorio_so_para_quem_gerou(ctx):
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "relatorio_pronto", {"relatorio": "vendas"})
    report_id = tool_ctx.blocks[-1]["report"]["id"]
    assert ctx.client().get(f"/api/v1/cosmos/reports/{report_id}/export/").status_code == 200
    other_user = ctx.user("gerente2", "manager")
    assert ctx.client(other_user).get(f"/api/v1/cosmos/reports/{report_id}/export/").status_code == 404


# ── supervisão ───────────────────────────────────────────────────────────────
def test_supervisao_aponta_documento_invalido_e_fecha_quando_corrigido(ctx, sent):
    ctx.user("super1", "supervisor")
    customer = Customer.all_objects.create(account=ctx.account, name="João", document="11111111112",
                                           phone="1199999", created_by=ctx.admin)
    supervision.check_instance(customer)
    finding = CosmosFinding.all_objects.get(rule="documento_invalido")
    assert finding.actor == ctx.admin and finding.status == CosmosFinding.Status.OPEN

    supervision.check_instance(customer)  # de novo: não duplica
    assert CosmosFinding.all_objects.filter(rule="documento_invalido").count() == 1

    customer.document = "52998224725"  # CPF válido
    customer.save()
    supervision.check_instance(customer)
    finding.refresh_from_db()
    assert finding.status == CosmosFinding.Status.RESOLVED


def test_supervisao_preco_abaixo_do_custo_avisa_o_supervisor(ctx, sent, django_capture_on_commit_callbacks):
    supervisor = ctx.user("super2", "supervisor")
    variant = ctx.product(name="Mesa", price="100.00")
    variant.average_cost = Decimal("150.00")
    with django_capture_on_commit_callbacks(execute=True):
        variant.save()
    finding = CosmosFinding.all_objects.get(rule="preco_abaixo_custo")
    assert finding.severity == CosmosFinding.Severity.CRITICAL
    alerted = [user_id for user_id, event in sent if event["type"] == "alert"]
    assert supervisor.pk in alerted and ctx.admin.pk in alerted


def test_documento_valido():
    assert supervision.document_ok("529.982.247-25")
    assert supervision.document_ok("11.222.333/0001-81")
    assert not supervision.document_ok("111.111.111-11")
    assert supervision.document_ok("")


def test_atividade_da_equipe_so_para_quem_supervisiona(ctx):
    seller = ctx.user("vendedor2", "seller")
    Customer.all_objects.create(account=ctx.account, name="Cliente", created_by=seller)
    assert "atividade_da_equipe" not in {d["function"]["name"] for d in tools.definitions(_actor(ctx, seller))}
    out = supervision.team_activity(_actor(ctx), date_from="2000-01-01")
    assert out["people"]


def test_status_e_alertas_pela_api(ctx):
    CosmosFinding.all_objects.create(account=ctx.account, rule="x", title="Algo", fingerprint="x")
    body = ctx.client().get("/api/v1/cosmos/status/").json()
    assert body["can_supervise"] and body["open_alerts"] == 1
    finding = ctx.client().get("/api/v1/cosmos/findings/").json()["results"][0]
    resolved = ctx.client().post(f"/api/v1/cosmos/findings/{finding['id']}/resolve/", {"status": "dismissed"},
                                 format="json")
    assert resolved.json()["status"] == "dismissed"
    seller = ctx.user("vendedor3", "seller")
    assert ctx.client(seller).get("/api/v1/cosmos/findings/").status_code == 403


# ── WebSocket ────────────────────────────────────────────────────────────────
@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
def test_websocket_recusa_quem_nao_esta_logado():
    async def connect():
        communicator = WebsocketCommunicator(application, "/api/v1/ws/cosmos/")
        connected, code = await communicator.connect()
        await communicator.disconnect()
        return connected, code

    assert async_to_sync(connect)() == (False, 4401)


# ── limites por conta (só no admin) ──────────────────────────────────────────
def _usage_chunk(prompt, completion):
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
    return SimpleNamespace(choices=[], usage=usage)


def test_consumo_e_somado_no_dia(ctx, sent, model):
    from starrp.models import CosmosUsage

    model([_chunk("Resposta 1"), _usage_chunk(100, 20)], [_chunk("Resposta 2"), _usage_chunk(50, 5)])
    agent.send_message(ctx.admin.pk, "consulta um", store_id=str(ctx.store.pk))
    agent.send_message(ctx.admin.pk, "consulta dois", store_id=str(ctx.store.pk))
    row = CosmosUsage.objects.get(account=ctx.account)
    assert (row.requests, row.prompt_tokens, row.completion_tokens, row.total_tokens) == (2, 150, 25, 175)


@pytest.mark.parametrize("field,period", [("cosmos_daily_tokens", "day"), ("cosmos_weekly_tokens", "week"),
                                          ("cosmos_monthly_tokens", "month")])
def test_cada_limite_bloqueia_sem_chamar_o_modelo(ctx, sent, model, field, period):
    from starrp.services.cosmos import usage

    ctx.account.cosmos_monthly_tokens = 0
    setattr(ctx.account, field, 100)
    ctx.account.save()
    usage.record(ctx.account, 90, 20)
    fake = model([_chunk("não deveria")])
    agent.send_message(ctx.admin.pk, "Quantos clientes tenho?", store_id=str(ctx.store.pk))
    assert fake.requests == []
    assert CosmosMessage.all_objects.filter(role="assistant").last().content == usage.exhausted(period)


def test_janelas_dia_semana_mes(ctx):
    from freezegun import freeze_time

    from starrp.models import CosmosUsage
    from starrp.services.cosmos import usage

    for day, tokens in (("2026-10-31", 1), ("2026-11-02", 10), ("2026-11-08", 100), ("2026-11-10", 1000),
                        ("2026-11-11", 10000)):
        CosmosUsage.objects.create(account=ctx.account, day=day, total_tokens=tokens)
    with freeze_time("2026-11-11 12:00"):  # quarta-feira
        assert usage.spent(ctx.account, "day") == 10000
        assert usage.spent(ctx.account, "week") == 11000  # segunda 09/11 em diante
        assert usage.spent(ctx.account, "month") == 11110


def test_tudo_zerado_e_ilimitado(ctx):
    from starrp.services.cosmos import usage

    ctx.account.cosmos_monthly_tokens = 0
    ctx.account.save()
    usage.record(ctx.account, 10_000_000, 0)
    assert usage.blocked(ctx.account) is None


def test_conta_desligada_esconde_o_widget_e_nao_expoe_o_limite(ctx):
    body = ctx.client().get("/api/v1/cosmos/status/").json()
    assert body["can_use"] and "tokens" not in str(body)
    ctx.account.cosmos_enabled = False
    ctx.account.save()
    assert ctx.client().get("/api/v1/cosmos/status/").json()["can_use"] is False
    # A seção Cosmos da conta (resumo diário, precificação) nunca mostra a chave nem os limites: só no admin.
    settings_body = str(ctx.client().get("/api/v1/account/settings/").json())
    assert "tokens" not in settings_body and "cosmos_enabled" not in settings_body


def test_admin_da_conta_mostra_o_consumo(ctx, client):
    from django.contrib.auth import get_user_model

    from starrp.services.cosmos import usage

    ctx.account.cosmos_daily_tokens = 50_000
    ctx.account.save()
    usage.record(ctx.account, 1000, 234)
    root = get_user_model().objects.create_superuser("root", "root@x.com", "senha123")
    client.force_login(root)
    page = client.get(f"/admin/starrp/account/{ctx.account.pk}/change/").content.decode()
    assert "hoje: 1.234 de 50.000 (2%)" in page
    assert "no mês: 1.234 de 1.000.000 (0%)" in page


# ── isolamento entre contas e perfil de acesso ───────────────────────────────
def _with_cosmos(ctx, username, role):
    """Usuário do cargo `role` que também pode usar a Cosmos (permissão extra no perfil)."""
    from starrp.models import Permission

    user = ctx.user(username, role)
    UserProfile.all_objects.get(user=user).extra_permissions.add(Permission.objects.get(code="cosmos.view"))
    return user


def test_cosmos_nunca_ve_dados_de_outra_conta(ctx, other):
    Customer.all_objects.create(account=ctx.account, name="Meu cliente")
    theirs = Customer.all_objects.create(account=other.account, name="Cliente da outra conta")
    tool_ctx = _ctx(ctx)

    counted = json.loads(tools.run(tool_ctx, "consultar_dados", {"conjunto": "clientes", "medidas": ["quantidade"]}))
    assert counted["rows"] == [{"quantidade": 1}]
    listed = tools.run(tool_ctx, "consultar_api", {"caminho": "/customers/", "parametros": {"search": "Cliente"}})
    assert "outra conta" not in listed
    direct = json.loads(tools.run(tool_ctx, "consultar_api", {"caminho": f"/customers/{theirs.pk}/"}))
    assert direct["status"] == 404
    # Nem propor alteração no registro da outra conta: a validação já recusa.
    proposal = json.loads(tools.run(tool_ctx, "propor_alteracao", {
        "metodo": "PATCH", "caminho": f"/customers/{theirs.pk}/", "corpo": {"name": "x"}, "titulo": "x"}))
    assert proposal.get("status") == 404 and not CosmosAction.all_objects.exists()


def test_conversa_proposta_e_relatorio_de_outra_conta_sao_inacessiveis(ctx, other, sent):
    mine = _ctx(ctx)
    tools.run(mine, "propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/", "corpo": {"name": "M"},
                                         "titulo": "Marca"})
    tools.run(mine, "montar_relatorio", {"titulo": "R", "indicadores": [{"dataset": "clientes", "metric": "quantidade"}]})
    action = CosmosAction.all_objects.get()
    report_id = mine.blocks[-1]["report"]["id"]
    conversation = mine.conversation

    agent.decide(other.admin.pk, str(action.pk), approve=True)
    action.refresh_from_db()
    assert action.status == CosmosAction.Status.PENDING  # o admin da outra conta não executa
    agent.send_message(other.admin.pk, "oi", conversation_id=str(conversation.pk))
    assert not conversation.messages.filter(role="user").exists()
    assert [e["message"] for _, e in sent if e["type"] == "error"] == ["Proposta não encontrada.", "Conversa não encontrada."]

    api = other.client()
    assert api.get(f"/api/v1/cosmos/conversations/{conversation.pk}/messages/").status_code == 404
    assert api.get(f"/api/v1/cosmos/reports/{report_id}/export/").status_code == 404


def test_sem_permissao_responde_logo(ctx):
    seller = _with_cosmos(ctx, "vend-cosmos", "seller")  # vendedor: sem relatórios, sem estoque, sem gravar pela Cosmos
    tool_ctx = _ctx(ctx, seller)

    for name, arguments in (
        ("consultar_dados", {"conjunto": "vendas"}),
        ("relatorio_pronto", {"relatorio": "vendas"}),
        ("consultar_api", {"caminho": "/stock/balances/"}),
        ("propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/", "titulo": "x"}),
        ("atividade_da_equipe", {}),
    ):
        out = json.loads(tools.run(tool_ctx, name, arguments))
        assert out["erro"] == "sem_permissao", (name, out)
    assert not tool_ctx.blocks  # nada foi mostrado

    from starrp.services.cosmos import prompts

    text = prompts.system_prompt(tool_ctx.actor)
    assert "Só ver: " in text and "Estoque" not in text.split("Perfil de acesso")[1].split("Todo o resto")[0]


def test_tirar_a_permissao_vale_na_hora(ctx, sent, model):
    from starrp.models import Permission

    user = _with_cosmos(ctx, "ex-cosmos", "seller")
    UserProfile.all_objects.get(user=user).extra_permissions.remove(Permission.objects.get(code="cosmos.view"))
    fake = model([_chunk("não deveria")])
    agent.send_message(user.pk, "oi", store_id=str(ctx.store.pk))
    assert fake.requests == [] and not CosmosConversation.all_objects.filter(user=user).exists()
    assert "não tem permissão" in sent[-1][1]["message"]


# ── relatório quando nada pronto cobre o pedido ──────────────────────────────
def test_relatorio_livre_com_dados_da_conversa(ctx):
    tool_ctx = _ctx(ctx)
    tools.run(tool_ctx, "relatorio_livre", {
        "titulo": "Atividade e qualidade da equipe", "data_inicial": "2026-01-01", "data_final": "2026-11-02",
        "indicadores": [{"rotulo": "Pessoas analisadas", "valor": 2}, {"rotulo": "Melhor", "valor": "Bruno",
                                                                         "formato": "text"}],
        "blocos": [
            {"tipo": "ranking", "titulo": "Ações no sistema", "linhas": [
                {"rotulo": "Bruno Lima", "valor": 10, "detalhe": "0 alertas"}, {"rotulo": "Ana Souza", "valor": 8}]},
            {"tipo": "bars", "titulo": "Ações x alertas", "eixo": ["Bruno", "Ana"],
             "series": [{"nome": "Ações", "valores": [10, 8]}, {"nome": "Alertas", "valores": ["0", "1"]}]},
            {"tipo": "table", "titulo": "Detalhe", "colunas": [
                {"chave": "pessoa", "rotulo": "Pessoa", "formato": "text"}, {"chave": "acoes", "rotulo": "Ações"}],
             "linhas": [{"pessoa": "Bruno", "acoes": 10}, {"pessoa": "Ana", "acoes": 8}]},
        ]})
    rep = tool_ctx.blocks[-1]["report"]
    assert [k["value"] for k in rep["kpis"]] == [2, "Bruno"]
    assert rep["blocks"][0]["rows"][0] == {"label": "Bruno Lima", "value": 10, "sub": "0 alertas"}
    assert rep["blocks"][1]["series"][1]["values"] == [0, 1]
    content, _kind, _name = report.export(report.CosmosReport.all_objects.get(pk=rep["id"]), ctx.admin)
    book = load_workbook(io.BytesIO(content))
    assert len(book["Ações no sistema"]._charts) == 1 and len(book["Ações x alertas"]._charts) == 1


def test_relatorio_livre_recusa_dado_malformado(ctx):
    out = json.loads(tools.run(_ctx(ctx), "relatorio_livre", {
        "titulo": "x", "blocos": [{"tipo": "line", "titulo": "Linha", "eixo": ["a", "b"],
                                   "series": [{"nome": "s", "valores": [1]}]}]}))
    assert "tem 1 valores e o eixo 2 pontos" in out["erro"]
    out = json.loads(tools.run(_ctx(ctx), "relatorio_livre", {
        "titulo": "x", "indicadores": [{"rotulo": "Total", "valor": "muito"}]}))
    assert "não é número" in out["erro"]


def test_endereco_existe_pelo_modelo_ou_pelo_id_real():
    from starrp.services.cosmos import catalog

    assert catalog.find("PATCH", "/catalog/brands/3f1c2b9e-0000-4000-8000-000000000000/")[0] == "/catalog/brands/{id}/"
    assert catalog.find("PATCH", "/catalog/brands/{id}/")[0] == "/catalog/brands/{id}/"
    assert catalog.find("POST", "/catalog/brands/")[0] == "/catalog/brands/"
    assert catalog.find("POST", "/reports/custom/")[0] is None


def test_proposta_com_endereco_inventado_e_recusada(ctx):
    out = json.loads(tools.run(_ctx(ctx), "propor_alteracao", {
        "metodo": "POST", "caminho": "/reports/custom/", "corpo": {"titulo": "x"}, "titulo": "Gerar Excel"}))
    assert "não existe na API" in out["erro"]
    assert not CosmosAction.all_objects.exists()


def test_alertas_por_pessoa_e_equipe_sem_administradores(ctx):
    bruno = ctx.user("bruno", "seller")
    CosmosFinding.all_objects.create(account=ctx.account, rule="a", title="A", fingerprint="1", actor=bruno)
    CosmosFinding.all_objects.create(account=ctx.account, rule="b", title="B", fingerprint="2", actor=bruno,
                                     status=CosmosFinding.Status.RESOLVED)
    CosmosFinding.all_objects.create(account=ctx.account, rule="c", title="C", fingerprint="3", actor=ctx.admin)
    out = json.loads(tools.run(_ctx(ctx), "consultar_dados", {"conjunto": "alertas", "medidas": ["quantidade"],
                                                             "agrupar_por": ["pessoa"]}))
    rows = out["rows"] if isinstance(out["rows"], list) else _rows(out["rows"])
    assert {r["pessoa"]: r["quantidade"] for r in rows} == {"Bruno": 2, ctx.admin.username: 1}

    Customer.all_objects.create(account=ctx.account, name="Feito pelo Bruno", created_by=bruno, updated_by=bruno)
    Customer.all_objects.create(account=ctx.account, name="Feito pelo admin", created_by=ctx.admin, updated_by=ctx.admin)
    with_admins = supervision.team_activity(_actor(ctx), date_from="2000-01-01")
    without = supervision.team_activity(_actor(ctx), date_from="2000-01-01", skip_admins=True)
    assert ctx.admin.pk in {p["user_id"] for p in with_admins["people"]}
    assert ctx.admin.pk not in {p["user_id"] for p in without["people"]}


# ── revisão: custo, parar, tela, lote, limite por minuto ─────────────────────
def test_resultado_antigo_de_ferramenta_vai_resumido(ctx):
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    make = lambda **f: CosmosMessage.all_objects.create(account=ctx.account, conversation=conversation, **f)  # noqa: E731
    call = lambda cid: [{"id": cid, "type": "function", "function": {"name": "consultar_api", "arguments": "{}"}}]  # noqa: E731
    make(role="user", content="primeira")
    make(role="assistant", content="", tool_calls=call("a"))
    make(role="tool", tool_call_id="a", content="x" * 5000)
    make(role="assistant", content="respondi")
    make(role="user", content="segunda")
    make(role="assistant", content="", tool_calls=call("b"))
    make(role="tool", tool_call_id="b", content="y" * 5000)
    tools_sent = [m["content"] for m in agent._history(conversation) if m["role"] == "tool"]
    assert len(tools_sent[0]) < 1400 and "resumido" in tools_sent[0]   # da rodada anterior
    assert tools_sent[1] == "y" * 5000                                   # da rodada atual, inteiro


def test_parar_interrompe_a_resposta(ctx, sent, model, monkeypatch):
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    agent.stop(ctx.admin.pk, str(conversation.pk))
    actor = _actor(ctx)
    turn = agent._Turn(actor, conversation)
    model([_chunk("isso não deveria aparecer")])
    agent._respond(turn)
    assert conversation.messages.get(role="assistant").content == "_(resposta interrompida)_"
    # Outro usuário não para a conversa de ninguém.
    agent.stop(ctx.user("intruso", "manager").pk, str(conversation.pk))


def test_mensagem_nova_ignora_parar_antigo_e_leva_a_tela(ctx, sent, model):
    fake = model([_chunk("Ok.")])
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    agent.stop(ctx.admin.pk, str(conversation.pk))
    agent.send_message(ctx.admin.pk, "o que é esta tela?", conversation_id=str(conversation.pk),
                       store_id=str(ctx.store.pk), page={"path": "/cadastros/produtos/123", "title": "Produto X"})
    assert conversation.messages.filter(role="assistant").last().content == "Ok."
    system = fake.requests[0]["messages"][0]["content"]
    assert "Produto X — /cadastros/produtos/123" in system


def test_confirmar_todas_grava_todas_com_uma_resposta(ctx, sent, model):
    tool_ctx = _ctx(ctx)
    for name in ("Uma", "Duas", "Tres"):
        tools.run(tool_ctx, "propor_alteracao", {"metodo": "POST", "caminho": "/catalog/brands/", "corpo": {"name": name},
                                                 "titulo": f"Cadastrar {name}"})
    ids = [str(a.pk) for a in CosmosAction.all_objects.all()]
    fake = model([_chunk("Pronto, as 3 marcas foram cadastradas.")])
    agent.decide(ctx.admin.pk, ids, approve=True)
    assert set(Brand.all_objects.filter(account=ctx.account).values_list("name", flat=True)) == {"Uma", "Duas", "Tres"}
    assert fake.requests == []  # sucesso conhecido: não gasta outra chamada só para dizer "pronto"
    assert tool_ctx.conversation.messages.filter(role="assistant").last().content == \
        "Pronto, as 3 propostas foram executadas com sucesso."
    event = tool_ctx.conversation.messages.get(role="event").content
    assert "CONFIRMOU 3 propostas" in event


def test_limite_de_mensagens_por_minuto(ctx, sent, model, settings):
    settings.COSMOS_MESSAGES_PER_MINUTE = 2
    model([_chunk("1")], [_chunk("2")], [_chunk("3")])
    for text in ("a", "b", "c"):
        agent.send_message(ctx.admin.pk, text, store_id=str(ctx.store.pk))
    assert CosmosMessage.all_objects.filter(role="user").count() == 2
    assert "Muitas mensagens" in sent[-1][1]["message"]


def test_status_dispara_a_varredura_sem_celery(ctx, monkeypatch):
    calls = []
    monkeypatch.setattr(supervision, "sweep", lambda account=None: calls.append(account) or 0)
    ctx.client().get("/api/v1/cosmos/status/")
    ctx.client().get("/api/v1/cosmos/status/")
    assert calls == [ctx.account]  # uma vez a cada 30 min por conta


# ── anexos na conversa ───────────────────────────────────────────────────────
def _xlsx(rows):
    from openpyxl import Workbook

    book = Workbook()
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_planilha_anexada_e_lida_e_vai_ao_modelo(ctx, sent, model):
    from django.core.files.uploadedfile import SimpleUploadedFile

    raw = _xlsx([[None], ["Nome", "Preço", "Ativo"], ["Camiseta", 49.9, True], ["Boné", 30, False]])
    response = ctx.client().post("/api/v1/cosmos/attachments/",
                                 {"file": SimpleUploadedFile("produtos.xlsx", raw)}, format="multipart")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["rows"] == 2 and body["columns"] == 3

    fake = model([_chunk("Li a planilha.")])
    agent.send_message(ctx.admin.pk, "", store_id=str(ctx.store.pk), files=[body["id"]])
    message = CosmosMessage.all_objects.get(role="user")
    assert message.content == "Veja o anexo."
    assert message.blocks[0]["items"][0]["name"] == "produtos.xlsx"
    attachment = CosmosAttachment.all_objects.get(pk=body["id"])
    assert attachment.conversation_id == message.conversation_id
    user_text = fake.requests[0]["messages"][-1]["content"]
    assert "Colunas: Nome, Preço, Ativo" in user_text and "Camiseta" in user_text


def test_ler_anexo_pagina_e_so_da_propria_conversa(ctx):
    tool_ctx = _ctx(ctx)
    rows = [[f"Item {i}", i] for i in range(1, 131)]
    attachment = CosmosAttachment.all_objects.create(
        account=ctx.account, user=ctx.admin, conversation=tool_ctx.conversation, name="lote.csv", kind="sheet",
        columns=["Nome", "Qtd"], rows=rows, row_count=130)
    page = json.loads(tools.run(tool_ctx, "ler_anexo", {"anexo": str(attachment.pk), "inicio": 101, "quantidade": 500}))
    assert page["colunas"] == ["linha", "Nome", "Qtd"] and page["linhas"][0] == [101, "Item 101", 101]
    assert len(page["linhas"]) == 30 and page["proxima"] is None  # última página
    wide = CosmosAttachment.all_objects.create(  # linhas grandes: a página encolhe e diz onde continuar
        account=ctx.account, user=ctx.admin, conversation=tool_ctx.conversation, name="largo.csv", kind="sheet",
        columns=["Texto"], rows=[["x" * 300] for _ in range(100)], row_count=100)
    page = json.loads(tools.run(tool_ctx, "ler_anexo", {"anexo": str(wide.pk), "quantidade": 100}))
    assert 1 < len(page["linhas"]) < 100 and page["proxima"] == len(page["linhas"]) + 1
    other = _ctx(ctx)  # outra conversa: não abre o anexo desta
    assert "não encontrado" in tools.run(other, "ler_anexo", {"anexo": str(attachment.pk)})


def test_anexo_csv_texto_e_formatos_recusados(ctx):
    from starrp.services.cosmos import attachments

    sheet = attachments.parse("precos.csv", "Nome;Preço\nCafé;12,50\nAçúcar;5\n".encode("cp1252"))
    assert sheet["columns"] == ["Nome", "Preço"] and sheet["rows"][0] == ["Café", "12,50"]
    text = attachments.parse("notas.txt", "Fornecedor novo: ACME".encode())
    assert text["kind"] == "text" and "ACME" in text["text"]
    for name in ("antiga.xls", "nota.pdf"):
        with pytest.raises(attachments.AttachmentError):
            attachments.parse(name, b"x")
    seller = ctx.user("vend_anexo", "seller")  # sem cosmos.view
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = ctx.client(seller).post("/api/v1/cosmos/attachments/",
                                       {"file": SimpleUploadedFile("a.csv", b"a,b\n1,2")}, format="multipart")
    assert response.status_code == 403


def test_anexo_de_outro_usuario_nao_entra_na_conversa(ctx):
    from starrp.services.cosmos import attachments

    owner = ctx.user("dono_anexo", "manager")
    attachment = CosmosAttachment.all_objects.create(account=ctx.account, user=owner, name="x.csv", kind="sheet")
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    assert attachments.claim(ctx.admin, conversation, [str(attachment.pk)]) == []


# ── resumo diário da equipe ──────────────────────────────────────────────────
def test_resumo_diario_mostra_quem_fez_o_que_e_os_alertas(ctx, sent):
    from django.utils import timezone

    from starrp.services.cosmos import digest

    seller = ctx.user("carla", "seller")
    Customer.all_objects.create(account=ctx.account, name="Cliente da Carla", created_by=seller, updated_by=seller)
    CosmosFinding.all_objects.create(account=ctx.account, rule="x", title="Cliente sem contato", fingerprint="d1",
                                     actor=seller, severity="warning")
    today = timezone.localdate()
    conversation = digest.deliver(ctx.admin, ctx.account, today)
    assert conversation.digest_day == today and conversation.title.startswith("Resumo da equipe")
    message = conversation.messages.get()
    assert message.role == "assistant" and message.tokens == 0  # sem modelo: não gasta tokens
    assert "**Carla**" in message.content and "Alertas novos (1)" in message.content
    assert message.blocks[0]["type"] == "buttons" and len(message.blocks[0]["buttons"]) <= 4
    assert any(event["type"] == "digest" for _, event in sent)
    assert digest.deliver(ctx.admin, ctx.account, today) is None  # um por dia
    assert digest.deliver(seller, ctx.account, today) is None     # só quem supervisiona


def test_resumo_dia_sem_movimento_e_conta_desligada(ctx, sent):
    from datetime import date

    from starrp.services.cosmos import digest

    assert digest.deliver(ctx.admin, ctx.account, date(2001, 1, 1)) is None
    ctx.account.cosmos_daily_digest = False
    ctx.account.save()
    assert digest.ensure(ctx.admin, ctx.account) is None


def test_status_entrega_o_resumo_de_ontem_uma_vez(ctx, monkeypatch):
    from freezegun import freeze_time

    from starrp.services.cosmos import digest

    calls = []
    monkeypatch.setattr(digest, "deliver", lambda user, account, day: calls.append(day))
    with freeze_time("2026-11-03 13:00:00"):  # 10h em Brasília
        ctx.client().get("/api/v1/cosmos/status/")
        ctx.client().get("/api/v1/cosmos/status/")
    assert [str(d) for d in calls] == ["2026-11-02"]


# ── ensaio de toda proposta (não só criar/alterar/excluir) ───────────────────
def test_sangria_em_caixa_fechado_nao_vira_cartao(ctx):
    from starrp.models import CashMovement, CashSession

    sid = ctx.client().post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                            format="json").json()["id"]
    CashSession.all_objects.filter(pk=sid).update(status=CashSession.Status.CLOSED)
    out = json.loads(tools.run(_ctx(ctx), "propor_alteracao", {
        "metodo": "POST", "caminho": f"/cash/sessions/{sid}/movements/", "titulo": "Registrar sangria",
        "corpo": {"kind": "withdrawal", "amount": "23.50", "reason": "Ajuste", "destination": "Cofre"}}))
    assert "FALHOU" in out["erro"] and out["status"] >= 400
    assert not CosmosAction.all_objects.exists()       # o usuário nem vê o cartão
    assert not CashMovement.all_objects.filter(session_id=sid).exists()  # o ensaio foi desfeito


def test_sangria_em_caixa_aberto_e_ensaiada_e_desfeita(ctx):
    from starrp.models import CashMovement

    sid = ctx.client().post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                            format="json").json()["id"]
    before = CashMovement.all_objects.filter(session_id=sid).count()
    out = tools.run(_ctx(ctx), "propor_alteracao", {
        "metodo": "POST", "caminho": f"/cash/sessions/{sid}/movements/", "titulo": "Registrar sangria",
        "corpo": {"kind": "withdrawal", "amount": "10", "reason": "Cofre", "destination": "Cofre"}})
    assert out.startswith("Proposta") and CosmosAction.all_objects.count() == 1
    assert CashMovement.all_objects.filter(session_id=sid).count() == before  # nada gravado antes de confirmar


def test_fiscal_nao_e_ensaiado():
    assert tools.NO_TRIAL.match("fiscal/invoices/abc/cancel/")
    assert tools.NO_TRIAL.match("inbound-nfe/123/manifest/")
    assert not tools.NO_TRIAL.match("cash/sessions/1/movements/")


def test_atalhos_seguem_o_que_a_pessoa_mais_faz(ctx):
    for i in range(3):
        Customer.all_objects.create(account=ctx.account, name=f"C{i}", created_by=ctx.admin, updated_by=ctx.admin)
    ctx.product(name="Mesa")
    habits = supervision.habits(ctx.admin, ctx.account.pk)
    assert habits[0] == "customers"
    assert ctx.client().get("/api/v1/cosmos/status/").json()["habits"] == habits


# ── custo: tabela, roteamento, janela + resumo, cache de prompt ──────────────
def test_lista_de_objetos_vai_ao_modelo_como_tabela():
    data = {"results": [{"id": i, "name": f"P{i}", "price": "1.00"} for i in range(5)]}
    out = json.loads(tools.compact(data))
    assert out["results"]["colunas"] == ["id", "name", "price"] and out["results"]["linhas"][0] == [0, "P0", "1.00"]
    assert len(tools.compact(data)) < len(json.dumps(data))


def test_roteador_escolhe_o_modelo_mais_barato_que_resolve(settings):
    from starrp.services.cosmos import router

    settings.OPENAI_MODEL, settings.OPENAI_MODEL_LIGHT, settings.OPENAI_MODEL_HEAVY = "gpt-5-mini", "gpt-5-nano", ""
    assert router.tier("Obrigado, Cosmos!") == router.LIGHT
    assert router.tier("sim") == router.DEFAULT                    # continua uma tarefa: não vai ao leve
    assert router.tier("vendas de hoje por vendedor") == router.DEFAULT
    assert router.tier("cadastrar em lote") == router.HEAVY
    assert router.model_for(router.HEAVY) == "gpt-5-mini"          # sem modelo forte configurado: o padrão
    assert router.options("gpt-5-nano", router.LIGHT)["reasoning_effort"] == "minimal"
    assert router.options("gpt-5-mini", router.DEFAULT)["max_completion_tokens"] == settings.COSMOS_MAX_OUTPUT_TOKENS


def test_saudacao_responde_localmente_sem_gastar_tokens(ctx, sent, model, settings):
    settings.OPENAI_MODEL_LIGHT = "gpt-5-nano"
    fake = model([_chunk("Oi! Como posso ajudar?")])
    agent.send_message(ctx.admin.pk, "bom dia", store_id=str(ctx.store.pk))
    assert fake.requests == []
    assert CosmosMessage.all_objects.filter(role="assistant").last().content == "Oi! Como posso ajudar?"


def test_prompt_estavel_mantem_cache_e_nao_carrega_mapa_inteiro(ctx, sent, model):
    fake = model([_chunk("Certo.")])
    agent.send_message(ctx.admin.pk, "explique as vendas", store_id=str(ctx.store.pk))
    request = fake.requests[0]
    assert request["prompt_cache_key"].startswith("cosmos-")
    assert request["store"] is False
    system = request["messages"][0]["content"]
    assert system.startswith("Você é a Cosmos") and system.index("Regras:") < system.index("Agora:")
    assert "Recursos da API: use buscar_endpoints" in system
    assert "/catalog/products/," not in system


class _Summarizer(FakeOpenAI):
    """Além das respostas em fluxo, devolve um resumo (chamada sem stream)."""

    def _create(self, **kwargs):
        if not kwargs.get("stream"):
            self.requests.append(kwargs)
            usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            message = SimpleNamespace(content="- Usuário quer cadastrar a marca Acme.")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)
        return super()._create(**kwargs)


def test_conversa_longa_vira_resumo_e_so_a_janela_vai_inteira(ctx, sent, monkeypatch, settings):
    settings.OPENAI_API_KEY, settings.COSMOS_HISTORY_TURNS = "sk-test", 2
    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    for i in range(6):
        CosmosMessage.all_objects.create(account=ctx.account, conversation=conversation, role="user", content=f"p{i}")
        CosmosMessage.all_objects.create(account=ctx.account, conversation=conversation, role="assistant",
                                         content=f"r{i}")
    fake = _Summarizer([_chunk("Certo.")])
    monkeypatch.setattr(agent, "_client", lambda: fake)
    agent.send_message(ctx.admin.pk, "e agora?", conversation_id=str(conversation.pk), store_id=str(ctx.store.pk))
    conversation.refresh_from_db()
    assert conversation.summary.startswith("- Usuário quer")
    sent_to_model = fake.requests[-1]["messages"]
    assert "Resumo do começo" in sent_to_model[1]["content"]
    users = [m["content"] for m in sent_to_model if m["role"] == "user"]
    assert users == ["p5", "e agora?"]  # a janela: as 2 últimas falas do usuário


def test_pausa_longa_tira_o_assunto_velho_da_janela(ctx):
    from datetime import timedelta

    from django.utils import timezone

    from starrp.services.cosmos import memory

    conversation = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin)
    old = CosmosMessage.all_objects.create(account=ctx.account, conversation=conversation, role="user", content="velho")
    CosmosMessage.all_objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
    new = CosmosMessage.all_objects.create(account=ctx.account, conversation=conversation, role="user", content="novo")
    assert memory.cut(conversation) == (new.position, True)


# ── pedidos do widget pelo WebSocket ─────────────────────────────────────────
def test_pedidos_pelo_socket_listam_renomeiam_e_apagam_so_o_que_e_seu(ctx):
    from starrp.services.cosmos import rpc

    mine = CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin, title="Minha")
    other_user = ctx.user("outro_rpc", "manager")
    theirs = CosmosConversation.all_objects.create(account=ctx.account, user=other_user, title="Dele")
    listed = rpc.handle(ctx.admin.pk, None, "conversations", {})
    assert listed["ok"] and [c["id"] for c in listed["data"]] == [str(mine.pk)]
    assert rpc.handle(ctx.admin.pk, None, "messages", {"id": str(theirs.pk)})["status"] == 404
    assert rpc.handle(ctx.admin.pk, None, "messages", {"id": "nao-e-um-id"})["status"] == 404
    assert rpc.handle(ctx.admin.pk, None, "rename", {"id": str(mine.pk), "title": "Nova"})["ok"]
    mine.refresh_from_db()
    assert mine.title == "Nova"
    assert rpc.handle(ctx.admin.pk, None, "remove", {"id": str(mine.pk)})["ok"]
    assert rpc.handle(ctx.admin.pk, None, "conversations", {})["data"] == []
    assert rpc.handle(ctx.admin.pk, None, "inventado", {})["status"] == 400


def test_alertas_pelo_socket_exigem_supervisao(ctx, other):
    from starrp.services.cosmos import rpc

    finding = CosmosFinding.all_objects.create(account=ctx.account, rule="x", title="Algo", fingerprint="rpc1")
    CosmosFinding.all_objects.create(account=other.account, rule="x", title="Da outra conta", fingerprint="rpc2")
    out = rpc.handle(ctx.admin.pk, None, "findings", {})
    assert [f["title"] for f in out["data"]] == ["Algo"]  # nunca os da outra conta
    seller = _with_cosmos(ctx, "vend_rpc", "seller")
    assert rpc.handle(seller.pk, None, "findings", {})["status"] == 403
    assert rpc.handle(seller.pk, None, "resolve", {"id": str(finding.pk)})["status"] == 403
    assert rpc.handle(ctx.admin.pk, None, "resolve", {"id": str(finding.pk), "status": "dismissed"})["ok"]
    finding.refresh_from_db()
    assert finding.status == "dismissed" and finding.resolved_by == ctx.admin
    status = rpc.handle(ctx.admin.pk, None, "status", {})["data"]
    assert status["can_supervise"] and status["open_alerts"] == 0


# ── filial sem movimento aparece zerada; cadastro fixo não é proposto ────────
def _empty_store(ctx):
    from starrp.models import Store

    return Store.all_objects.create(account=ctx.account, name="Loja Sem Venda")


def test_relatorio_por_filial_mostra_a_filial_sem_venda(ctx):
    from starrp.services.cosmos import datasets

    _empty_store(ctx)
    actor = bridge.actor_for(ctx.admin, "*")
    rows = datasets.query(actor, "vendas", ["faturamento", "quantidade"], ["filial"], date_from="2000-01-01")["rows"]
    assert {"filial": "Loja Sem Venda", "faturamento": Decimal("0.00"), "quantidade": 0} in rows
    hidden = datasets.query(actor, "vendas", ["quantidade"], ["filial"], date_from="2000-01-01", include_empty=False)
    assert all(r["filial"] != "Loja Sem Venda" for r in hidden["rows"])
    one_store = datasets.query(_actor(ctx), "vendas", ["quantidade"], ["filial"], date_from="2000-01-01")
    assert all(r["filial"] != "Loja Sem Venda" for r in one_store["rows"])  # tela de uma filial: só ela


def test_comparativo_de_filiais_do_livro_inclui_a_sem_venda(ctx):
    from starrp.core.tenant import set_current_account
    from starrp.services import report_book

    _empty_store(ctx)
    set_current_account(ctx.account)
    report = report_book.movement_branches(ctx.account, None, {"date_from": "2000-01-01"})
    table = next(b for b in report["blocks"] if b["type"] == "table")
    assert "Loja Sem Venda" in [r["name"] for r in table["rows"]]
    report = report_book.movement_branches(ctx.account, None, {"date_from": "2000-01-01", "include_empty": "0"})
    table = next(b for b in report["blocks"] if b["type"] == "table")
    assert "Loja Sem Venda" not in [r["name"] for r in table["rows"]]


def test_cadastro_fixo_do_sistema_nao_e_oferecido_a_cosmos(ctx):
    from starrp.services.cosmos import catalog

    actor = _actor(ctx)  # administrador da conta, mas não o suporte
    assert not catalog.allowed(actor, "POST", "/payment-methods/")
    assert not catalog.allowed(actor, "DELETE", "/payment-methods/123/")
    assert catalog.allowed(actor, "PATCH", "/payment-methods/123/")  # ajustar (ativar, taxa) pode
    out = json.loads(tools.run(_ctx(ctx), "propor_alteracao", {"metodo": "POST", "caminho": "/roles/",
                                                              "corpo": {"name": "Novo"}, "titulo": "Criar cargo"}))
    assert out["erro"] == "sem_permissao" and not CosmosAction.all_objects.exists()


# ── alerta fechado por alguém não volta ──────────────────────────────────────
def test_alerta_descartado_nao_volta_na_varredura_e_fecha_quando_o_caixa_resolve(ctx, sent):
    from starrp.models import CashDiscrepancy, CashSession

    sid = ctx.client().post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                            format="json").json()["id"]
    diff = CashDiscrepancy.all_objects.create(account=ctx.account, session=CashSession.all_objects.get(pk=sid), store=ctx.store,
                                              amount=Decimal("23.50"), reason="Faltou no fechamento")
    supervision.sweep(ctx.account)
    finding = CosmosFinding.all_objects.get(rule="diferenca_caixa")
    assert finding.title == "Diferença de caixa de R$ 23,50 sem resolução"

    finding.status, finding.resolved_by = CosmosFinding.Status.DISMISSED, ctx.admin
    finding.save()
    supervision.sweep(ctx.account)
    supervision.sweep(ctx.account)
    assert CosmosFinding.all_objects.filter(rule="diferenca_caixa").count() == 1  # não reabriu

    CashDiscrepancy.all_objects.filter(pk=diff.pk).update(status="resolved")
    supervision.sweep(ctx.account)
    finding.refresh_from_db()
    assert ":fim:" in finding.fingerprint  # episódio encerrado


def test_alerta_aberto_some_sozinho_quando_o_problema_e_resolvido(ctx, sent):
    from starrp.models import CashDiscrepancy, CashSession

    sid = ctx.client().post("/api/v1/cash/sessions/", {"register": str(ctx.register.pk), "opening_amount": "100"},
                            format="json").json()["id"]
    diff = CashDiscrepancy.all_objects.create(account=ctx.account, session=CashSession.all_objects.get(pk=sid), store=ctx.store,
                                              amount=Decimal("5"), reason="Troco")
    supervision.sweep(ctx.account)
    CashDiscrepancy.all_objects.filter(pk=diff.pk).update(status="resolved")
    supervision.sweep(ctx.account)
    finding = CosmosFinding.all_objects.get(rule="diferenca_caixa")
    assert finding.status == CosmosFinding.Status.RESOLVED and finding.resolved_by is None


def test_cadastro_descartado_nao_reabre_ao_editar_mas_o_corrigido_pelo_sistema_reabre(ctx, sent):
    customer = Customer.all_objects.create(account=ctx.account, name="Ana", document="11111111112", phone="1199")
    supervision.check_instance(customer)
    finding = CosmosFinding.all_objects.get(rule="documento_invalido")
    finding.status, finding.resolved_by = CosmosFinding.Status.DISMISSED, ctx.admin
    finding.save()
    customer.name = "Ana Maria"
    customer.save()
    supervision.check_instance(customer)
    assert CosmosFinding.all_objects.filter(rule="documento_invalido").count() == 1

    other = Customer.all_objects.create(account=ctx.account, name="Bia", document="22222222223", phone="1199")
    supervision.check_instance(other)
    other.document = "52998224725"
    other.save()
    supervision.check_instance(other)  # corrigiu: o sistema fecha
    other.document = "22222222223"
    other.save()
    supervision.check_instance(other)  # estragou de novo: volta a avisar
    assert CosmosFinding.all_objects.filter(rule="documento_invalido", object_id=str(other.pk),
                                            status=CosmosFinding.Status.OPEN).exists()


# ── contas por dia (vencimento é só data) ──────────────────────────────────────
def test_contas_agrupam_por_dia_de_vencimento(ctx):
    ctx.account.extra_modules = ["finance", "cosmos"]
    ctx.account.save()
    response = ctx.client().post("/api/v1/finance/titles/", {"kind": "payable", "description": "Aluguel",
                                                            "total": "300.00", "installment_count": 3,
                                                            "first_due": "2026-11-04"}, format="json")
    assert response.status_code == 201, response.json()
    rows = datasets.query(_actor(ctx), "contas", ["valor", "quantidade"], ["dia", "tipo"],
                          date_from="2026-11-02", date_to="2026-12-31")["rows"]
    assert [(r["dia"], r["tipo"], r["valor"]) for r in rows] == [
        ("04/11/2026", "A pagar", Decimal("100.00")), ("04/12/2026", "A pagar", Decimal("100.00"))]


def test_prompt_manda_entregar_sem_ficar_perguntando(ctx):
    text = prompts.system_prompt(_actor(ctx))
    assert "ENTREGUE NA HORA" in text and "Nunca responda só com perguntas" in text


def test_conversas_vem_por_pagina_e_buscam_no_servidor(ctx):
    from starrp.services.cosmos import rpc

    for i in range(rpc.CONVERSATION_PAGE + 3):
        CosmosConversation.all_objects.create(account=ctx.account, user=ctx.admin,
                                              title=f"Vendas {i}" if i % 2 else f"Estoque {i}")
    first = rpc.handle(ctx.admin.pk, None, "conversations", {})["data"]
    second = rpc.handle(ctx.admin.pk, None, "conversations", {"page": 2})["data"]
    assert len(first) == rpc.CONVERSATION_PAGE and len(second) == 3
    assert not {c["id"] for c in first} & {c["id"] for c in second}
    found = rpc.handle(ctx.admin.pk, None, "conversations", {"q": "estoque"})["data"]
    assert len(found) == 12 and all(c["title"].startswith("Estoque") for c in found)
    body = ctx.client().get("/api/v1/cosmos/conversations/", {"q": "vendas", "page_size": 20}).json()
    assert body["count"] == 11
