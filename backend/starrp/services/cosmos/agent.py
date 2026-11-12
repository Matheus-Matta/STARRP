"""A conversa com a Cosmos: mensagem do usuário → modelo ⇄ ferramentas → resposta no widget.

Roda numa thread própria (o consumidor do WebSocket não espera): `send_message` e `decide`
abrem o contexto do usuário, gravam cada fala e mandam ao widget, em tempo real, o texto
chegando (`delta`), o que ela está fazendo (`status`) e a mensagem pronta (`message`).

Gravação proposta (`propor_alteracao`) espera o clique: `decide(..., approve=True)` executa pela
API normal, atualiza o cartão e devolve o resultado ao modelo, que comenta o que foi feito.
"""
import json
import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from starrp.core.middleware import ALL_STORES
from starrp.core.permissions import has_permission_code
from starrp.core.tenant import clear_current_account
from starrp.models import CosmosAction, CosmosAttachment, CosmosConversation, CosmosMessage
from starrp.services.cosmos import attachments, bridge, events, memory, prompts, router, tools, usage

logger = logging.getLogger(__name__)

Role = CosmosMessage.Role
HISTORY = 40
# Resultado de ferramenta de rodadas ANTERIORES vai resumido ao modelo: os números já viraram resposta, e
# reenviar 14 mil caracteres por consulta a cada mensagem esgotaria o limite de tokens da conta.
OLD_TOOL_CHARS = 1200
BUSY_SECONDS = 300
STOP_SECONDS = 120
STOPPED = "\n\n_(resposta interrompida)_"
ACTION_TTL = timedelta(hours=24)
TITLE_SIZE = 60
DELTA_SECONDS = 0.04
DELTA_CHARS = 160
TURN_TOOL_CHARS = 24_000
REPEATED_TOOL_LIMIT = 2
_CLIENT = None
_CLIENT_CONFIG = None
_CLIENT_LOCK = threading.Lock()


def enabled():
    return bool(settings.OPENAI_API_KEY)


def _client():
    from openai import OpenAI

    global _CLIENT, _CLIENT_CONFIG
    config = (settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL, settings.OPENAI_TIMEOUT)
    if _CLIENT is None or _CLIENT_CONFIG != config:
        with _CLIENT_LOCK:
            if _CLIENT is None or _CLIENT_CONFIG != config:
                _CLIENT = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL,
                                 timeout=settings.OPENAI_TIMEOUT, max_retries=2)
                _CLIENT_CONFIG = config
    return _CLIENT


# ── formato para a tela ─────────────────────────────────────────────────────
def visible(message):
    if message.role in (Role.USER, Role.EVENT):
        return True
    return message.role == Role.ASSISTANT and bool(message.content or message.blocks)


def message_payload(message):
    return {"id": str(message.pk), "conversation": str(message.conversation_id), "role": message.role,
            "content": message.content, "blocks": message.blocks, "created_at": message.created_at.isoformat()}


def conversation_payload(conversation):
    return {"id": str(conversation.pk), "title": conversation.title,
            "last_message_at": (conversation.last_message_at or conversation.created_at).isoformat(),
            "created_at": conversation.created_at.isoformat(),
            "digest_day": conversation.digest_day.isoformat() if conversation.digest_day else None}


class _Turn:
    """Uma rodada: quem fala, em qual conversa, e o envio ao widget dele."""

    def __init__(self, actor, conversation, page=None):
        self.actor, self.conversation, self.page = actor, conversation, page or {}

    @property
    def stopped(self):
        return bool(cache.get(_stop_key(self.conversation.pk)))

    def emit(self, kind, **data):
        events.send(self.actor.user.pk, {"type": kind, "conversation": str(self.conversation.pk), **data})

    def save(self, role, content="", **fields):
        message = CosmosMessage.all_objects.create(account=self.actor.account, conversation=self.conversation,
                                                   role=role, content=content, created_by=self.actor.user,
                                                   updated_by=self.actor.user, **fields)
        if visible(message):
            self.emit("message", message=message_payload(message))
        return message


# ── histórico para o modelo ─────────────────────────────────────────────────
def _with_attachments(message, files):
    """A fala do usuário como o modelo vê: o texto e o resumo de cada anexo dela."""
    ids = [item["id"] for b in message.blocks or [] if b.get("type") == "attachments" for item in b.get("items", [])]
    notes = [attachments.note(files[i]) for i in ids if i in files]
    return "\n\n".join([message.content, *notes]) if notes else message.content


def _history(conversation):
    # Só a janela (o que já foi resumido fica de fora) e, por segurança, no máximo HISTORY falas.
    rows = list(conversation.messages.filter(position__gt=conversation.summary_until)
                .order_by("-position")[:HISTORY])[::-1]
    files = {}
    if any(m.role == Role.USER and m.blocks for m in rows):
        files = {str(a.pk): a for a in CosmosAttachment.all_objects.filter(conversation=conversation,
                                                                            deleted_at__isnull=True)}
    while rows and rows[0].role not in (Role.USER, Role.EVENT):
        rows.pop(0)  # nunca começar no meio de uma chamada de ferramenta
    answered = {m.tool_call_id for m in rows if m.role == Role.TOOL}
    # A rodada atual começa na última fala do usuário (ou aviso de confirmação): antes dela, resumido.
    current = max((i for i, m in enumerate(rows) if m.role in (Role.USER, Role.EVENT)), default=0)
    out, open_calls = [], set()
    if conversation.summary:
        out.append({"role": "system", "content": f"Resumo do começo desta conversa:\n{conversation.summary}"})
    for index, m in enumerate(rows):
        if m.role == Role.USER:
            out.append({"role": "user", "content": _with_attachments(m, files)})
        elif m.role == Role.EVENT:
            out.append({"role": "system", "content": m.content})
        elif m.role == Role.ASSISTANT:
            calls = [c for c in (m.tool_calls or []) if c.get("id") in answered]
            if not calls and not m.content:
                continue
            item = {"role": "assistant", "content": m.content or None}
            if calls:
                item["tool_calls"] = calls
                open_calls.update(c["id"] for c in calls)
            out.append(item)
        elif m.role == Role.TOOL and m.tool_call_id in open_calls:
            content = m.content
            if index < current and len(content) > OLD_TOOL_CHARS:
                content = content[:OLD_TOOL_CHARS] + " … (resultado antigo resumido; consulte de novo se precisar)"
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": content})
    return out


def _complete(turn, system, definitions, level=router.DEFAULT, history=None):
    """Uma chamada ao modelo (o do nível da rodada), com o texto indo ao widget enquanto chega."""
    model = router.model_for(level)
    options = router.options(model, level)
    if not settings.OPENAI_BASE_URL:
        # Cache de prompt da OpenAI: o começo do texto de sistema é igual entre as chamadas da mesma
        # pessoa; a chave mantém essas chamadas no mesmo servidor de cache (entrada com desconto).
        options["prompt_cache_key"] = f"cosmos-{turn.actor.account.pk}-{turn.actor.user.pk}"
    stream = _client().chat.completions.create(
        model=model, messages=[{"role": "system", "content": system},
                               *(history if history is not None else _history(turn.conversation))],
        tools=definitions, stream=True, stream_options={"include_usage": True}, **options)
    content, calls, tokens, cut_short = [], {}, 0, False
    pending_delta, pending_chars, last_delta = [], 0, time.monotonic()

    def flush_delta():
        nonlocal pending_delta, pending_chars, last_delta
        if pending_delta:
            turn.emit("delta", text="".join(pending_delta))
            pending_delta, pending_chars, last_delta = [], 0, time.monotonic()

    for count, chunk in enumerate(stream):
        if count % 15 == 0 and turn.stopped:
            flush_delta()
            getattr(stream, "close", lambda: None)()  # o usuário clicou em Parar: corta aqui
            return "".join(content) + STOPPED, [], tokens
        if getattr(chunk, "usage", None):  # vem no último pedaço (stream_options.include_usage)
            tokens = chunk.usage.total_tokens or 0
            details = getattr(chunk.usage, "prompt_tokens_details", None)
            usage.record(turn.actor.account, chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0, tokens,
                         cached_tokens=getattr(details, "cached_tokens", 0) or 0)
        if not chunk.choices:
            continue
        cut_short = cut_short or getattr(chunk.choices[0], "finish_reason", None) == "length"
        delta = chunk.choices[0].delta
        if delta.content:
            content.append(delta.content)
            pending_delta.append(delta.content)
            pending_chars += len(delta.content)
            if pending_chars >= DELTA_CHARS or time.monotonic() - last_delta >= DELTA_SECONDS:
                flush_delta()
        for part in delta.tool_calls or []:
            slot = calls.setdefault(part.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if part.id:
                slot["id"] = part.id
            if part.function is not None:
                slot["function"]["name"] += part.function.name or ""
                slot["function"]["arguments"] += part.function.arguments or ""
    flush_delta()
    if cut_short:  # bateu no teto de saída (COSMOS_MAX_OUTPUT_TOKENS): a chamada pela metade não vale
        text = "".join(content).strip()
        return (text + "\n\n_(resposta cortada por ser longa demais — peça em partes menores)_").strip(), [], tokens
    return "".join(content), [calls[i] for i in sorted(calls)], tokens


def _respond(turn, level=router.DEFAULT):
    if not enabled():
        turn.save(Role.ASSISTANT, "A Cosmos ainda não foi ligada neste servidor: falta a chave da OpenAI "
                                  "(`OPENAI_API_KEY` no `.env`). Peça ao suporte para configurar.")
        return
    from openai import APIError

    ctx = tools.ToolContext(actor=turn.actor, conversation=turn.conversation)
    definitions = tools.definitions(turn.actor)
    system = prompts.system_prompt(turn.actor, turn.page)
    turn.emit("typing", on=True)
    try:
        memory.refresh(turn.conversation, turn.actor, _client())  # o que saiu da janela vira resumo (modelo leve)
        history = _history(turn.conversation)
        tool_chars, repeated = 0, {}
        for _step in range(settings.COSMOS_MAX_STEPS):
            if turn.stopped:
                turn.save(Role.ASSISTANT, STOPPED.strip(), blocks=ctx.blocks)
                return
            limit = usage.blocked(turn.actor.account)  # conferido a cada volta: o limite pode acabar no meio
            if limit:
                turn.save(Role.ASSISTANT, limit, blocks=ctx.blocks)
                return
            content, calls, tokens = _complete(turn, system, definitions, level, history)
            if not calls:
                turn.save(Role.ASSISTANT, content, blocks=ctx.blocks, tokens=tokens)
                return
            if level == router.LIGHT:
                level = router.DEFAULT  # o leve quis usar ferramentas: a tarefa não era simples
            turn.save(Role.ASSISTANT, content, tool_calls=calls, tokens=tokens)
            history.append({"role": "assistant", "content": content or None, "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                if tools.STATUS.get(name):
                    turn.emit("status", text=tools.STATUS[name])
                try:
                    raw_arguments = call["function"]["arguments"] or "{}"
                    signature = f"{name}:{raw_arguments}"
                    repeated[signature] = repeated.get(signature, 0) + 1
                    if repeated[signature] > REPEATED_TOOL_LIMIT:
                        output = json.dumps({"erro": "Esta mesma ferramenta com os mesmos argumentos já foi "
                                                        "tentada duas vezes. Use o que já recebeu, mude os "
                                                        "parâmetros ou conclua a resposta."}, ensure_ascii=False)
                    elif tool_chars >= TURN_TOOL_CHARS:
                        output = json.dumps({"erro": "O limite de dados desta resposta foi atingido. Conclua com "
                                                        "os resultados já recebidos ou peça ao usuário para "
                                                        "continuar em outra mensagem."}, ensure_ascii=False)
                    else:
                        arguments = json.loads(raw_arguments)
                        output = tools.run(ctx, name, arguments) if name in tools.HANDLERS else \
                            json.dumps({"erro": f"Ferramenta inexistente: {name}"})
                except json.JSONDecodeError:
                    output = json.dumps({"erro": "Argumentos não são JSON válido."})
                except Exception:  # noqa: BLE001 — a ferramenta falhou; o modelo fica sabendo e segue
                    logger.exception("Cosmos: ferramenta %s falhou", name)
                    output = json.dumps({"erro": "Falha interna ao executar a ferramenta. Tente de novo com "
                                                 "outros parâmetros (outro agrupamento ou ferramenta) sem "
                                                 "perguntar ao usuário."})
                remaining = max(TURN_TOOL_CHARS - tool_chars, 0)
                if remaining and len(output) > remaining:
                    output = output[:remaining] + " … (limite total de dados da resposta atingido)"
                tool_chars += len(output)
                CosmosMessage.all_objects.create(account=turn.actor.account, conversation=turn.conversation,
                                                 role=Role.TOOL, content=output, tool_call_id=call["id"],
                                                 tool_name=name[:60], created_by=turn.actor.user)
                history.append({"role": "tool", "tool_call_id": call["id"], "content": output})
        turn.save(Role.ASSISTANT, "Precisei de mais passos do que o permitido para esta pergunta. Pode dividir em "
                                  "partes menores?", blocks=ctx.blocks)
    except APIError as error:
        logger.warning("Cosmos: erro da OpenAI: %s", error)
        turn.save(Role.ASSISTANT, "Não consegui falar com o serviço de IA agora "
                                  f"({getattr(error, 'status_code', None) or 'sem resposta'}). Tente de novo em instantes.",
                  blocks=ctx.blocks)
    finally:
        turn.conversation.last_message_at = timezone.now()
        turn.conversation.save(update_fields=["last_message_at", "updated_at"])
        turn.emit("typing", on=False)


# ── pontos de entrada (rodam numa thread) ───────────────────────────────────
def _store_key(store_id):
    return store_id or ALL_STORES


def _stop_key(conversation_id):
    return f"cosmos:stop:{conversation_id}"


def stop(user_id, conversation_id):
    """Pedido de parar a resposta em andamento (o laço confere entre os pedaços e entre as ferramentas)."""
    if CosmosConversation.all_objects.filter(pk=conversation_id, user_id=user_id).exists():
        cache.set(_stop_key(conversation_id), 1, STOP_SECONDS)


def _throttled(user_id):
    """Mais de N mensagens por minuto do mesmo usuário: segura (clique repetido, uso abusivo)."""
    key = f"cosmos:rate:{user_id}:{timezone.now():%Y%m%d%H%M}"
    cache.add(key, 0, 90)
    try:
        return cache.incr(key) > settings.COSMOS_MESSAGES_PER_MINUTE
    except ValueError:
        return False


def _locked(conversation_id):
    return not cache.add(f"cosmos:busy:{conversation_id}", 1, BUSY_SECONDS)


def _release(user_id, conversation_id):
    """Fim da rodada: libera a conversa e SEMPRE avisa o widget que parou de digitar
    (inclusive quando não houve modelo: Cosmos desligada, proposta cancelada ou expirada)."""
    cache.delete(f"cosmos:busy:{conversation_id}")
    events.send(user_id, {"type": "typing", "conversation": str(conversation_id), "on": False})


def _user(user_id):
    return get_user_model().objects.get(pk=user_id, is_active=True)


def _actor(user, store_id):
    """O contexto do usuário (conta e filiais dele) — e a permissão de usar a Cosmos, conferida a cada
    mensagem: se o administrador tirar o acesso, vale na hora, sem esperar o widget reconectar."""
    actor = bridge.actor_for(user, store_id)
    if not has_permission_code(user, "cosmos.view"):
        raise bridge.CosmosDenied("Você não tem permissão para usar a Cosmos. Peça ao administrador.")
    return actor


def _fail(user_id, conversation_id, message):
    events.send(user_id, {"type": "error", "conversation": conversation_id, "message": message})


def _page(page):
    """A tela aberta no navegador (endereço e título), só como contexto — nunca como instrução."""
    if not isinstance(page, dict):
        return {}
    return {"path": str(page.get("path") or "")[:200], "title": str(page.get("title") or "")[:120]}


def send_message(user_id, text, conversation_id=None, store_id=None, finding_id=None, page=None, files=None):
    conversation = None
    try:
        user = _user(user_id)
        actor = _actor(user, _store_key(store_id))
        text = (text or "").strip()[:8000]
        files = [str(f) for f in files or [] if f][:attachments.PER_MESSAGE] if isinstance(files, list) else []
        if not text and files:
            text = "Veja o anexo." if len(files) == 1 else "Veja os anexos."
        if not text:
            return
        if _throttled(user.pk):
            _fail(user.pk, str(conversation_id or ""), "Muitas mensagens em sequência. Espere um minuto e tente de novo.")
            return
        if conversation_id:
            conversation = CosmosConversation.objects.get(pk=conversation_id, user=user)
        else:
            conversation = CosmosConversation.all_objects.create(
                account=actor.account, user=user, store=actor.store, title=text[:TITLE_SIZE],
                finding_id=finding_id, created_by=user, updated_by=user)
            events.send(user.pk, {"type": "conversation", "conversation": conversation_payload(conversation)})
        if _locked(conversation.pk):
            _fail(user.pk, str(conversation.pk), "Espere a Cosmos terminar a resposta anterior.")
            return
        try:
            cache.delete(_stop_key(conversation.pk))  # um "Parar" antigo não corta a resposta nova
            turn = _Turn(actor, conversation, _page(page))
            claimed = attachments.claim(user, conversation, files)
            blocks = [{"type": "attachments", "items": [attachments.payload(a) for a in claimed]}] if claimed else []
            turn.save(Role.USER, text, blocks=blocks)
            local = "" if claimed or not enabled() else router.local_reply(text)
            if local:
                turn.save(Role.ASSISTANT, local)
                conversation.last_message_at = timezone.now()
                conversation.save(update_fields=["last_message_at", "updated_at"])
            else:
                _respond(turn, router.tier(text, attachments=bool(claimed)))
        finally:
            _release(user.pk, conversation.pk)
    except bridge.CosmosDenied as error:
        _fail(user_id, str(conversation_id or ""), str(error))
    except CosmosConversation.DoesNotExist:
        _fail(user_id, str(conversation_id), "Conversa não encontrada.")
    except Exception:  # noqa: BLE001 — a thread não pode morrer calada
        logger.exception("Cosmos: falha ao responder")
        _fail(user_id, str(conversation_id or getattr(conversation, "pk", "")), "Algo deu errado. Tente de novo.")
    finally:
        clear_current_account()


def _result(action, result):
    data = result.data if isinstance(result.data, dict) else {"dados": result.data}
    record_id = data.get("id") or (action.path.rstrip("/").rsplit("/", 1)[-1] if action.method != "POST" else None)
    parts = action.path.rstrip("/").split("/")
    endpoint = "/" + "/".join(parts if action.method == "POST" else parts[:-1]) + "/"
    message = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else data.get("detail")
    return {"status": result.status, "ok": result.ok, "id": str(record_id) if record_id else None,
            "endpoint": endpoint, "message": message or ""}


def _update_card(turn, action):
    payload = tools.action_payload(action)
    for message in turn.conversation.messages.filter(role=Role.ASSISTANT).order_by("-position")[:30]:
        blocks = message.blocks or []
        if any(b.get("type") == "action" and b.get("action", {}).get("id") == payload["id"] for b in blocks):
            message.blocks = [{"type": "action", "action": payload}
                              if b.get("type") == "action" and b["action"].get("id") == payload["id"] else b
                              for b in blocks]
            message.save(update_fields=["blocks", "updated_at"])
            break
    turn.emit("action", action=payload)


def _execute(turn, action, approve, user):
    """Decide UMA proposta; devolve a linha do resumo para o modelo (ou None se já estava decidida)."""
    action.refresh_from_db()
    if action.status != CosmosAction.Status.PENDING:
        turn.emit("action", action=tools.action_payload(action))
        return None
    action.decided_by, action.decided_at = user, timezone.now()
    if action.created_at < timezone.now() - ACTION_TTL:
        action.status = CosmosAction.Status.EXPIRED
    elif not approve:
        action.status = CosmosAction.Status.REJECTED
    else:
        result = bridge.call(turn.actor, action.method, action.path, body=action.body)
        action.status = CosmosAction.Status.EXECUTED if result.ok else CosmosAction.Status.FAILED
        action.result = _result(action, result)
        action.save()
        _update_card(turn, action)
        outcome = "executada com sucesso" if result.ok else "FALHOU"
        return (f"- '{action.title}' ({action.method} /{action.path}): {outcome}. Resposta da API "
                f"(HTTP {result.status}): {tools.compact(result.data)[:1500]}")
    action.save()
    _update_card(turn, action)
    return f"- '{action.title}': {action.get_status_display().lower()}."


def decide(user_id, action_ids, approve):
    """Confirma ou cancela uma proposta — ou várias de uma vez ("Confirmar todas"), com UMA resposta no fim."""
    # Até 50 de uma vez: o cadastro em lote de uma planilha gera uma proposta por linha.
    ids = [action_ids] if isinstance(action_ids, str) else [str(a) for a in (action_ids or [])][:50]
    conversation_id = ""
    try:
        user = _user(user_id)
        actions = list(CosmosAction.all_objects.select_related("conversation").filter(
            pk__in=ids, conversation__user=user, deleted_at__isnull=True).order_by("created_at"))
        if not actions or len({a.conversation_id for a in actions}) != 1:
            raise CosmosAction.DoesNotExist
        conversation = actions[0].conversation
        conversation_id = str(conversation.pk)
        store = actions[0].store_id
        actor = _actor(user, str(store) if store else ALL_STORES)
        if _locked(conversation.pk):
            _fail(user.pk, conversation_id, "Espere a Cosmos terminar a resposta anterior.")
            return
        try:
            cache.delete(_stop_key(conversation.pk))
            turn = _Turn(actor, conversation)
            lines = [line for line in (_execute(turn, action, approve, user) for action in actions) if line]
            if not lines:
                return
            if not approve:
                turn.save(Role.EVENT, "O usuário CANCELOU as propostas. Nada foi gravado:\n" + "\n".join(lines))
                turn.save(Role.ASSISTANT, "Tudo bem, não gravei nada. Quer ajustar alguma coisa?")
                return
            if all("expirada" in line for line in lines):
                turn.save(Role.ASSISTANT, "Essa proposta expirou (mais de 24 horas). Peça de novo que eu refaço com "
                                          "os dados atuais.")
                return
            failed = any("FALHOU" in line for line in lines)
            what = "a proposta" if len(lines) == 1 else f"{len(lines)} propostas"
            turn.save(Role.EVENT, f"O usuário CONFIRMOU {what}. Resultado:\n" + "\n".join(lines)
                      + "\nAvise o resultado ao usuário em poucas palavras"
                      + (" e explique o que falhou e como corrigir." if failed else "."))
            if failed:
                _respond(turn, router.DEFAULT)
            else:
                executed = sum(action.status == CosmosAction.Status.EXECUTED for action in actions)
                expired = sum(action.status == CosmosAction.Status.EXPIRED for action in actions)
                if executed == 1 and not expired:
                    reply = "Pronto, a proposta foi executada com sucesso."
                elif executed and not expired:
                    reply = f"Pronto, as {executed} propostas foram executadas com sucesso."
                else:
                    reply = (f"Pronto, {executed} proposta(s) foram executadas; "
                             f"{expired} expiraram e precisam ser refeitas.")
                turn.save(Role.ASSISTANT, reply)
                conversation.last_message_at = timezone.now()
                conversation.save(update_fields=["last_message_at", "updated_at"])
        finally:
            _release(user.pk, conversation.pk)
    except CosmosAction.DoesNotExist:
        _fail(user_id, conversation_id, "Proposta não encontrada.")
    except bridge.CosmosDenied as error:
        _fail(user_id, conversation_id, str(error))
    except Exception:  # noqa: BLE001
        logger.exception("Cosmos: falha ao decidir a proposta")
        _fail(user_id, conversation_id, "Algo deu errado ao executar. Tente de novo.")
    finally:
        clear_current_account()
