"""WebSocket do widget da Cosmos: `ws(s)://<host>/api/v1/ws/cosmos/?store=<id|*>`.

O widget manda:
    {"type": "message", "conversation": "<id>" | null, "text": "...", "finding": "<id>"?,
     "page": {"path", "title"}?, "attachments": ["<id>", ...]?}   (anexos enviados antes em /cosmos/attachments/)
    {"type": "decide", "action": "<id>" | "actions": ["<id>", ...], "approve": true | false}
    {"type": "stop", "conversation": "<id>"}                       (Parar a resposta em andamento)
    {"type": "request", "id": "r1", "op": "conversations" | "messages" | "rename" | "remove" | "findings" |
     "resolve" | "status", "params": {...}}         → {"type": "response", "id": "r1", "ok", "data" | "error"}
     (o que o widget pedia por HTTP: ver `services/cosmos/rpc.py`)
    {"type": "ping"}

E recebe (todas as abas do usuário, pelo grupo `cosmos_<id>`): `conversation`, `message`,
`delta`, `status`, `typing`, `action`, `alert`, `error` — ver `services/cosmos/agent.py`.

A resposta do modelo roda numa thread à parte (`thread_sensitive=False`): uma conversa longa
não segura as dos outros usuários nem as próximas mensagens deste.
"""
import asyncio

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import close_old_connections

from starrp.core.permissions import has_permission_code
from starrp.services.cosmos import agent, events, rpc

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


@database_sync_to_async
def _can_use(user):
    from starrp.core.tenant import clear_current_account
    from starrp.services.cosmos.bridge import CosmosDenied, actor_for

    try:
        actor = actor_for(user, "*")
        return actor.account.cosmos_active and has_permission_code(user, "cosmos.view")
    except CosmosDenied:
        return False
    finally:
        clear_current_account()


def _in_thread(fn):
    """Roda `fn` numa thread do pool, com conexão de banco própria e limpa (como uma requisição)."""
    def run(*args):
        close_old_connections()
        try:
            return fn(*args)
        finally:
            close_old_connections()
    return sync_to_async(run, thread_sensitive=False)


class CosmosConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if not await _can_use(user):
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.user_id = user.pk
        params = dict(part.split("=", 1) for part in self.scope.get("query_string", b"").decode().split("&") if "=" in part)
        self.store_id = params.get("store") or None
        self.group = events.group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "ready", "enabled": agent.enabled()})

    async def disconnect(self, code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type") if isinstance(content, dict) else None
        if kind == "ping":
            await self.send_json({"type": "pong"})
        elif kind == "store":
            self.store_id = content.get("store") or None
        elif kind == "message":
            run = _in_thread(agent.send_message)
            self._spawn(run(self.user_id, content.get("text", ""), content.get("conversation") or None,
                            content.get("store") or self.store_id, content.get("finding") or None,
                            content.get("page") or None, content.get("attachments") or None))
        elif kind == "decide":
            run = _in_thread(agent.decide)
            self._spawn(run(self.user_id, content.get("actions") or content.get("action"), bool(content.get("approve"))))
        elif kind == "request":
            # Rápido (lista, falas, alertas): responde direto, sem fila; o `id` casa a resposta com o pedido.
            reply = await _in_thread(rpc.handle)(self.user_id, self.store_id, str(content.get("op") or ""),
                                                 content.get("params") or {})
            await self.send_json({"type": "response", "id": content.get("id"), **reply})
        elif kind == "stop" and content.get("conversation"):
            await _in_thread(agent.stop)(self.user_id, str(content["conversation"]))

    def _spawn(self, coroutine):
        # Fica rodando sozinho; o que ele produzir chega pelo grupo (`cosmos_event`).
        task = asyncio.ensure_future(coroutine)
        self._tasks = getattr(self, "_tasks", set())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def cosmos_event(self, message):
        await self.send_json(message["event"])
