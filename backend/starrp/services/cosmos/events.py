"""Entrega dos acontecimentos da Cosmos ao widget, pelo WebSocket.

Cada usuário tem um grupo (`cosmos_<id>`): todas as abas abertas dele recebem a mesma coisa —
o texto chegando aos poucos, o cartão de confirmação, o alerta da supervisão. Quem envia pode
estar no consumidor, numa thread da conversa ou numa tarefa: `send` serve para todos.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def group(user_id):
    return f"cosmos_{user_id}"


def send(user_id, event):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group(user_id), {"type": "cosmos.event", "event": event})
    except Exception:  # noqa: BLE001 — sem WebSocket o dado continua salvo; a tela pega ao abrir
        logger.warning("Cosmos: não foi possível avisar o usuário %s", user_id, exc_info=True)
