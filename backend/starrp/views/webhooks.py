"""Recepção pública e autenticada dos webhooks das integrações."""
import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from starrp.models import Integration, IntegrationWebhookEvent
from starrp.services import integrations


def _error(status, message):
    return JsonResponse({"detail": message}, status=status)


@method_decorator(csrf_exempt, name="dispatch")
class IntegrationWebhookView(View):
    http_method_names = ["post", "options"]

    def post(self, request, kind, integration_id):
        integration = Integration.all_objects.filter(
            pk=integration_id, kind=kind, is_active=True, deleted_at__isnull=True
        ).first()
        cls = integrations.REGISTRY.get(kind)
        if integration is None or cls is None or not cls.supports_webhooks:
            return _error(404, "Integração não encontrada.")

        service = integrations.handler(integration)
        if not service.webhook_ready:
            return _error(503, "A autenticação do webhook não está configurada.")

        raw_body = request.body
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error(400, "Payload JSON inválido.")
        if not isinstance(payload, dict):
            return _error(400, "O payload precisa ser um objeto JSON.")
        if not service.verify_webhook(raw_body, request.headers, payload):
            return _error(401, "Assinatura ou token do webhook inválido.")

        event_id = service.webhook_event_id(request.headers, payload, raw_body).strip()
        event_type = service.webhook_event_type(request.headers, payload).strip()
        if not event_id or not event_type:
            return _error(400, "O webhook não informou o identificador ou o tipo do evento.")

        defaults = {
            "account": integration.account,
            "provider": kind,
            "event_type": event_type[:120],
            "payload": payload,
            "headers": service.webhook_headers(request.headers),
        }
        try:
            with transaction.atomic():
                event, created = IntegrationWebhookEvent.objects.get_or_create(
                    integration=integration, provider_event_id=event_id[:255], defaults=defaults
                )
        except IntegrityError:  # duas entregas iguais chegaram ao mesmo tempo
            event = IntegrationWebhookEvent.objects.get(
                integration=integration, provider_event_id=event_id[:255]
            )
            created = False
        return JsonResponse({"ok": True, "duplicate": not created, "event_id": str(event.pk)}, status=200)
