"""Limpeza diária das tabelas que só crescem: sem ela, o banco engorda a cada requisição do PDV.

- `IdempotencyRecord`: uma linha por escrita com `Idempotency-Key` (todo envio do PDV). Passado o
  prazo em que a fila offline ainda pode reenviar, a resposta guardada não serve para mais nada.
- Tokens JWT vencidos (`OutstandingToken` e o `BlacklistedToken` ligado a ele): um por login e por
  renovação (com rotação, cada renovação cria um e põe o anterior na lista negra).
- Pedidos de redefinição de senha vencidos.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

BATCH = 5000


def _delete_in_batches(qs):
    """Apaga em lotes: um DELETE gigante trava a tabela e incha o log de transações do Postgres."""
    total = 0
    while True:
        ids = list(qs.values_list("pk", flat=True)[:BATCH])
        if not ids:
            return total
        total += qs.model._base_manager.filter(pk__in=ids).delete()[0]


def run(now=None):
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

    from starrp.models import IdempotencyRecord, PasswordResetRequest

    now = now or timezone.now()
    keep_days = getattr(settings, "IDEMPOTENCY_KEEP_DAYS", 30)
    return {
        "idempotency": _delete_in_batches(
            IdempotencyRecord.objects.filter(created_at__lt=now - timedelta(days=keep_days))),
        # O BlacklistedToken cai junto (FK em cascata).
        "jwt_tokens": _delete_in_batches(OutstandingToken.objects.filter(expires_at__lt=now)),
        "password_resets": _delete_in_batches(
            PasswordResetRequest.objects.filter(expires_at__lt=now - timedelta(days=7))),
    }
