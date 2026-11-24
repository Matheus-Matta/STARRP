"""Integrações com serviços externos (Asaas, Shopify...). Ver `base.py`.

    from starrp.services import integrations
    asaas = integrations.active("asaas", purpose="receivable_boleto", account=conta)  # a padrão da conta
    asaas.test()
"""
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from . import asaas, shopify  # noqa: F401 — registram os tipos
from .base import MASK, REGISTRY, CheckResult, Field, IntegrationType, Purpose, get_type, kind_choices, register

__all__ = ["MASK", "REGISTRY", "CheckResult", "Field", "IntegrationType", "Purpose", "active", "check",
           "get_type", "handler", "kind_choices", "register", "types", "webhook_url"]


def types():
    return [cls.describe() for cls in REGISTRY.values()]


def handler(integration):
    """A classe do tipo já com os valores da integração."""
    return get_type(integration.kind)(integration)


def webhook_url(integration):
    """URL pública e estável que deve ser cadastrada no provedor."""
    cls = REGISTRY.get(integration.kind)
    if cls is None or not cls.supports_webhooks:
        return None
    path = reverse("integration-webhook", kwargs={"kind": integration.kind, "integration_id": integration.pk})
    return f"{settings.API_URL.rstrip('/')}{path}"


def active(kind, *, account, purpose=None, pk=None):
    """A integração ativa do tipo (a escolhida por `pk`, senão a padrão, senão a única). None se não houver."""
    from starrp.models import Integration

    qs = Integration.all_objects.filter(account=account, kind=kind, is_active=True, deleted_at__isnull=True)
    if purpose:
        qs = [i for i in qs if purpose in (i.purposes or [])]
    else:
        qs = list(qs)
    chosen = next((i for i in qs if pk and str(i.pk) == str(pk)), None) or next((i for i in qs if i.is_default), None)
    if chosen is None and len(qs) == 1:
        chosen = qs[0]
    return handler(chosen) if chosen else None


def check(integration, save=True):
    """Testa a conexão e guarda o resultado na integração."""
    result = handler(integration).test()
    if save and integration.pk:
        integration.last_check_at, integration.last_check_ok = timezone.now(), result.ok
        integration.last_check_message = result.message[:255]
        type(integration).all_objects.filter(pk=integration.pk).update(
            last_check_at=integration.last_check_at, last_check_ok=result.ok,
            last_check_message=integration.last_check_message)
    return result
