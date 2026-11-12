"""Pedidos do widget pelo WebSocket (em vez de HTTP): lista de conversas, falas, renomear,
apagar, alertas e "resolvido". O socket já está aberto e autenticado — sem handshake, cookies e
middleware a cada clique. A API REST continua igual (o widget cai nela se o socket estiver fora).

    → {"type": "request", "id": "r1", "op": "conversations", "params": {}}
    ← {"type": "response", "id": "r1", "ok": true, "data": [...]}
    ← {"type": "response", "id": "r1", "ok": false, "status": 403, "error": "..."}

Mesmas regras da API: conta e filiais do usuário (`bridge.actor_for`), `cosmos.view` para
conversar, `cosmos.supervise` para os alertas, e cada um só vê as próprias conversas.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from starrp.core.middleware import ALL_STORES
from starrp.core.permissions import has_permission_code
from starrp.core.tenant import clear_current_account
from starrp.models import CosmosConversation, CosmosFinding
from starrp.services.cosmos import bridge

logger = logging.getLogger(__name__)

HABITS_SECONDS = 6 * 60 * 60
PAGE = 50
CONVERSATION_PAGE = 20  # igual ao `page_size` que o widget pede por HTTP


class RpcError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def status_payload(user, account):
    """O que o widget precisa saber ao abrir (o mesmo de GET /cosmos/status/)."""
    from starrp.services.cosmos import agent, digest, supervision

    if not account.cosmos_active:  # sem o módulo: o widget nem aparece, e nada roda em nome dele
        return {"enabled": False, "model": None, "can_use": False, "can_write": False, "can_supervise": False, "open_alerts": 0, "habits": []}
    supervise = has_permission_code(user, "cosmos.supervise")
    # Sem Celery beat a varredura e o resumo do dia não rodam: quem supervisiona e abre o widget dispara.
    if supervise and cache.add(f"cosmos:sweep:{account.pk}", 1, supervision.SWEEP_SECONDS):
        if settings.CELERY_TASK_ALWAYS_EAGER:
            # Desenvolvimento sem Redis/worker: conserva o fallback existente.
            supervision.sweep(account)
        else:
            # Produção: abrir o widget nunca espera a varredura pesada.
            from starrp.tasks.cosmos import cosmos_supervision

            try:
                cosmos_supervision.delay(str(account.pk))
            except Exception:  # noqa: BLE001 — o widget abre mesmo se o broker estiver fora
                cache.delete(f"cosmos:sweep:{account.pk}")
                logger.warning("Cosmos: não consegui agendar a varredura da conta %s", account.pk, exc_info=True)
    if supervise:
        digest.ensure(user, account)
    # Os atalhos do widget seguem o que a pessoa mais faz (lido do histórico; 6 h no cache).
    habits = cache.get_or_set(f"cosmos:habits:{account.pk}:{user.pk}",
                              lambda: supervision.habits(user, account.pk), HABITS_SECONDS)
    alerts = CosmosFinding.objects.filter(status=CosmosFinding.Status.OPEN).count() if supervise else 0
    return {
        "enabled": agent.enabled(), "model": settings.OPENAI_MODEL if agent.enabled() else None,
        # O limite de tokens não é mostrado.
        "can_use": has_permission_code(user, "cosmos.view"),
        "can_write": has_permission_code(user, "cosmos.manage"),
        "can_supervise": supervise, "open_alerts": alerts, "habits": habits,
    }


def _get(queryset, pk, message):
    """O registro pelo id; id inexistente ou malformado → 404 (nunca diz se é de outra pessoa)."""
    try:
        return queryset.get(pk=str(pk or ""))
    except (queryset.model.DoesNotExist, ValidationError, ValueError) as error:
        raise RpcError(message, 404) from error


def _conversation(user, params):
    return _get(CosmosConversation.objects.filter(user=user), params.get("id"), "Conversa não encontrada.")


def conversations_of(user, search=""):
    """As conversas da pessoa, mais recentes primeiro; `search` procura no título."""
    rows = CosmosConversation.objects.filter(user=user)
    return rows.filter(title__icontains=search.strip()) if search and search.strip() else rows


def _conversations(actor, params):
    """Uma página da lista (o widget carrega a próxima ao rolar até o fim)."""
    from starrp.serializers.cosmos import CosmosConversationSerializer

    try:
        page = max(int(params.get("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    start = (page - 1) * CONVERSATION_PAGE
    rows = conversations_of(actor.user, str(params.get("q") or ""))[start:start + CONVERSATION_PAGE]
    return CosmosConversationSerializer(rows, many=True).data


def _messages(actor, params):
    from starrp.services.cosmos import agent

    conversation = _conversation(actor.user, params)
    rows = [agent.message_payload(m) for m in conversation.messages.order_by("position") if agent.visible(m)]
    return {"conversation": agent.conversation_payload(conversation), "messages": rows}


def _rename(actor, params):
    title = str(params.get("title") or "").strip()[:120]
    if not title:
        raise RpcError("Dê um nome à conversa.")
    conversation = _conversation(actor.user, params)
    conversation.title, conversation.updated_by = title, actor.user
    conversation.save(update_fields=["title", "updated_by", "updated_at"])
    return {"id": str(conversation.pk), "title": title}


def _remove(actor, params):
    conversation = _conversation(actor.user, params)
    conversation.delete()  # exclusão lógica, como na API
    return {"id": str(conversation.pk)}


def _supervisor(actor):
    if not has_permission_code(actor.user, "cosmos.supervise"):
        raise RpcError("Você não tem permissão para ver os alertas da equipe.", 403)


def _findings(actor, params):
    from starrp.serializers.cosmos import CosmosFindingSerializer

    _supervisor(actor)
    rows = (CosmosFinding.objects.filter(status=CosmosFinding.Status.OPEN).select_related("actor", "store")[:PAGE])
    return [{**row, "actor": row["actor_name"]} for row in CosmosFindingSerializer(rows, many=True).data]


def _resolve(actor, params):
    _supervisor(actor)
    status = params.get("status") or CosmosFinding.Status.RESOLVED
    if status not in (CosmosFinding.Status.RESOLVED, CosmosFinding.Status.DISMISSED):
        raise RpcError("Use resolved ou dismissed.")
    finding = _get(CosmosFinding.objects.all(), params.get("id"), "Alerta não encontrado.")
    finding.status, finding.resolved_by, finding.resolved_at = status, actor.user, timezone.now()
    finding.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])
    return {"id": str(finding.pk), "status": status}


def _status(actor, params):
    return status_payload(actor.user, actor.account)


OPS = {"status": _status, "conversations": _conversations, "messages": _messages, "rename": _rename,
       "remove": _remove, "findings": _findings, "resolve": _resolve}


def handle(user_id, store_id, op, params):
    """Executa um pedido como o usuário; devolve o evento de resposta (sem o `id`)."""
    fn = OPS.get(op)
    if fn is None:
        return {"ok": False, "status": 400, "error": f"Pedido desconhecido: {op}"}
    try:
        user = get_user_model().objects.get(pk=user_id, is_active=True)
        actor = bridge.actor_for(user, store_id or ALL_STORES)
        if not (actor.account.cosmos_active and has_permission_code(user, "cosmos.view")):
            raise RpcError("Você não tem permissão para usar a Cosmos.", 403)
        return {"ok": True, "data": fn(actor, params if isinstance(params, dict) else {})}
    except RpcError as error:
        return {"ok": False, "status": error.status, "error": str(error)}
    except bridge.CosmosDenied as error:
        return {"ok": False, "status": 403, "error": str(error)}
    finally:
        clear_current_account()
