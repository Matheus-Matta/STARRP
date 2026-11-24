"""Encerrar todas as sessões de um usuário (S-12, docs/SEGURANCA.md): senha trocada ou redefinida.

- refresh tokens: todos para a blacklist (não renovam mais);
- access tokens já emitidos: o middleware recusa os anteriores a `UserProfile.sessions_revoked_at`.
"""
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from starrp.models import UserProfile


def revoke_all(user):
    now = timezone.now()
    UserProfile.all_objects.filter(user=user).update(sessions_revoked_at=now)
    outstanding = OutstandingToken.objects.filter(user=user, expires_at__gt=now).exclude(blacklistedtoken__isnull=False)
    BlacklistedToken.objects.bulk_create([BlacklistedToken(token=t) for t in outstanding], ignore_conflicts=True)
    _close_sockets(user)


def _close_sockets(user):
    """WebSocket da Cosmos aberto com a senha antiga fecha na hora (rodada 1, P-9)."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from starrp.services.cosmos import events

    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(events.group(user.pk), {"type": "session.revoked"})
    except Exception:  # noqa: BLE001 — sem camada de canais: a próxima mensagem do socket confere sozinha
        pass
