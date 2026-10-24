"""Deduplicação de escritas reenviadas pelo PDV (`Idempotency-Key`).

A primeira execução guarda a resposta na MESMA transação da operação; uma
repetição com a mesma chave recebe a resposta guardada sem executar nada.
A mesma chave com outro corpo é recusada (409).
"""
import hashlib
import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse

from starrp.core.envelope import envelope

HEADER = "Idempotency-Key"
GUARDED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _LostRace(Exception):
    pass


class IdempotencyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = (request.headers.get(HEADER) or "").strip()[:200]
        account = getattr(request, "account", None)
        if not key or account is None or request.method not in GUARDED_METHODS:
            return self.get_response(request)

        from starrp.models import IdempotencyRecord

        fingerprint = hashlib.sha256(
            b"|".join([request.method.encode(), request.get_full_path().encode(), request.body or b""])
        ).hexdigest()
        stored = IdempotencyRecord.objects.filter(account=account, key=key).first()
        if stored is not None:
            return self._replay_or_conflict(stored, fingerprint)
        try:
            with transaction.atomic():
                response = self.get_response(request)
                if not (200 <= response.status_code < 300) or "json" not in response.get("Content-Type", ""):
                    return response
                try:
                    with transaction.atomic():
                        IdempotencyRecord.objects.create(
                            account=account,
                            key=key,
                            method=request.method,
                            path=request.path[:500],
                            request_fingerprint=fingerprint,
                            status_code=response.status_code,
                            response_body=json.loads(response.content or b"{}"),
                        )
                except IntegrityError:
                    raise _LostRace from None
        except _LostRace:
            return self._replay_or_conflict(IdempotencyRecord.objects.get(account=account, key=key), fingerprint)
        return response

    @staticmethod
    def _replay_or_conflict(stored, fingerprint):
        if stored.request_fingerprint != fingerprint:
            body = envelope(409, "Esta chave de idempotência já foi usada para outra operação.", "idempotency_reused")
            return JsonResponse(body, status=409)
        response = JsonResponse(stored.response_body, safe=False, status=stored.status_code)
        response["Idempotent-Replay"] = "true"
        return response
