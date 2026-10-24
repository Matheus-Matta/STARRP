"""Handler de exceções do DRF: toda resposta de erro sai no mesmo envelope.

    {"success": false, "status_code": 409, "error": {"code": "...", "message": ...}}
"""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from starrp.core.envelope import envelope

logger = logging.getLogger("starrp.api")


def _integrity_message(exc):
    text = str(exc).lower()
    if "unique" in text or "duplicate" in text:
        return "Já existe um registro com estes dados."
    if "foreign key" in text:
        return "Registro relacionado inválido ou inexistente."
    if "not null" in text:
        return "Um campo obrigatório não foi informado."
    return "Não foi possível salvar: conflito de integridade dos dados."


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    code = getattr(exc, "default_code", "error")

    if response is None and isinstance(exc, IntegrityError):
        response, code = Response({"detail": _integrity_message(exc)}, status=status.HTTP_409_CONFLICT), "conflict"
    elif response is None and isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": " ".join(exc.messages)}
        response, code = Response(detail, status=status.HTTP_400_BAD_REQUEST), "invalid"
    elif response is None and isinstance(exc, OperationalError):
        logger.warning("Banco indisponível")
        response = Response(
            {"detail": "Serviço temporariamente indisponível."}, status=503, headers={"Retry-After": "2"}
        )
        code = "service_unavailable"
    elif response is None:
        logger.exception("Erro não tratado na API")
        return Response(envelope(500), status=500)

    # A exceção pode carregar um código específico (ex.: BusinessError(code=...)).
    detail = getattr(exc, "detail", None)
    if hasattr(detail, "code") and isinstance(detail.code, str) and detail.code not in ("invalid", "error"):
        code = detail.code
    message = response.data.get("detail", response.data) if isinstance(response.data, dict) else response.data
    if isinstance(response.data, dict) and set(response.data) != {"detail"}:
        message = response.data
    response.data = envelope(response.status_code, message, code)
    return response
