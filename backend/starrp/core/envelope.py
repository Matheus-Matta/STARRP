"""Garante o envelope de erro também no que NÃO passa pelo DRF.

O handler do DRF cobre as views; este middleware (o mais externo) cobre o 404
HTML do Django e respostas de middlewares, para toda rota sob `/api/`.
"""
import json

from django.http import JsonResponse

API_PREFIX = "/api/"

STATUS_INFO = {
    400: ("bad_request", "Requisição inválida."),
    401: ("not_authenticated", "Autenticação necessária."),
    403: ("permission_denied", "Sem permissão para esta ação."),
    404: ("not_found", "Rota ou registro não encontrado."),
    405: ("method_not_allowed", "Método não permitido nesta rota."),
    409: ("conflict", "Conflito com o estado atual do registro."),
    422: ("business_rule", "A operação não é permitida pelas regras do sistema."),
    429: ("throttled", "Muitas requisições. Aguarde e tente novamente."),
    500: ("internal_error", "Ocorreu um erro interno. Tente novamente mais tarde."),
}


def envelope(status_code, message=None, code=None):
    default_code, default_message = STATUS_INFO.get(
        status_code, ("server_error" if status_code >= 500 else "error", "Não foi possível concluir a operação.")
    )
    return {
        "success": False,
        "status_code": status_code,
        "error": {"code": code or default_code, "message": message if message is not None else default_message},
    }


def is_enveloped(payload):
    return isinstance(payload, dict) and "success" in payload and "error" in payload


class ApiErrorEnvelopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code < 400 or not request.path.startswith(API_PREFIX):
            return response
        if getattr(response, "streaming", False):
            return response
        if not response.get("Content-Type", "").startswith("application/json"):
            return JsonResponse(envelope(response.status_code), status=response.status_code)
        try:
            payload = json.loads(response.content.decode(response.charset or "utf-8"))
        except ValueError:
            return response
        if is_enveloped(payload):
            return response
        message = payload.get("detail", payload) if isinstance(payload, dict) else payload
        return JsonResponse(envelope(response.status_code, message), status=response.status_code)
