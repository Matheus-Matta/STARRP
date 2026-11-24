"""Organização semântica dos formulários genéricos do Django Admin."""
from collections import OrderedDict

from django.core.exceptions import FieldDoesNotExist
from django.db import models


GROUPS = OrderedDict(
    (
        ("main", ("Dados principais", "Informações essenciais para identificar este registro.")),
        ("scope", ("Escopo e vínculos", "Conta, loja e registros relacionados.")),
        ("contact", ("Contato", "Canais usados para comunicação.")),
        ("address", ("Endereço", "Localização e dados postais.")),
        ("commercial", ("Valores e condições", "Quantidades, preços e demais condições comerciais.")),
        ("fiscal", ("Dados fiscais", "Tributação, documentos e emissão fiscal.")),
        ("cosmos", ("Cosmos e automações", "Limites e recursos inteligentes disponíveis para a conta.")),
        ("pricing", ("Pesquisa de preços", "Fontes, limites e regras da pesquisa de mercado.")),
        ("seo", ("SEO", "Configurações e limites de otimização para busca.")),
        ("workflow", ("Fluxo e situação", "Etapas, responsáveis e datas do processo.")),
        ("settings", ("Configuração", "Opções que controlam o comportamento deste registro.")),
        ("integration", ("Integração e dados técnicos", "Referências externas e dados de integração.")),
        ("audit", ("Auditoria", "Informações mantidas automaticamente pelo sistema.")),
    )
)

AUDIT = {"created_at", "updated_at", "deleted_at", "created_by", "updated_by"}
CONTACT = {"email", "phone", "mobile", "website", "contact_name", "contact_phone", "contact_email"}
ADDRESS = {
    "address", "street", "number", "complement", "district", "neighborhood", "city", "city_ibge",
    "state", "country", "zip_code", "postal_code", "latitude", "longitude", "shipping_address",
    "billing_address",
}
FISCAL = {
    "document", "cnpj", "cpf", "state_registration", "municipal_registration", "ncm", "cest", "cfop",
    "cfop_interstate", "csosn", "cst_icms", "pis_cst", "cofins_cst", "crt", "origin", "tax_data",
}
COMMERCIAL_PARTS = (
    "price", "cost", "amount", "total", "subtotal", "discount", "freight", "margin", "quantity", "balance",
    "credit", "commission", "paid", "refund", "change", "percent", "rate", "weight", "width", "height",
)
INTEGRATION_PARTS = (
    "external", "provider_", "remote_", "payload", "metadata", "metafields", "webhook", "api_", "sync_",
    "access_key", "xml", "token", "secret", "credential",
)
WORKFLOW_EXACT = {"status", "reason", "priority", "error", "error_message", "processing"}
LONG_NAMES = {
    "description", "notes", "message", "content", "body", "value", "payload", "metadata", "metafields", "xml",
    "summary_xml", "full_xml", "provider_data", "shipping_address", "billing_address", "tax_data", "fields",
}


def _model_field(model, name):
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _group_for(model, name):
    field = _model_field(model, name)
    lowered = name.lower()
    if lowered in AUDIT:
        return "audit"
    if lowered.startswith("cosmos_"):
        return "cosmos"
    if lowered.startswith("price_"):
        return "pricing"
    if lowered.startswith("seo_"):
        return "seo"
    if lowered in CONTACT or lowered.endswith(("_email", "_phone")):
        return "contact"
    if lowered in ADDRESS or lowered.startswith(("address_", "shipping_", "billing_")):
        return "address"
    if lowered in FISCAL or lowered.startswith(("fiscal_", "certificate_", "csc_", "dfe_", "tax_")):
        return "fiscal"
    if any(part in lowered for part in COMMERCIAL_PARTS):
        return "commercial"
    if lowered in WORKFLOW_EXACT or lowered.endswith(("_status", "_at", "_by", "_reason")):
        return "workflow"
    if any(part in lowered for part in INTEGRATION_PARTS):
        return "integration"
    if field is not None and field.is_relation:
        return "scope"
    if field is not None and isinstance(field, (models.BooleanField, models.JSONField)):
        return "settings"
    if lowered.startswith(("is_", "has_", "allow_", "enable_")) or lowered.endswith(("_enabled", "_mode")):
        return "settings"
    return "main"


def _wide(model, name):
    field = _model_field(model, name)
    return (
        field is None
        or name in LONG_NAMES
        or isinstance(field, (models.TextField, models.JSONField, models.FileField, models.ImageField, models.ManyToManyField))
    )


def _rows(model, names):
    """Agrupa campos compactos em pares e preserva campos longos em linha inteira."""
    rows = []
    pending = None
    for name in names:
        if _wide(model, name):
            if pending is not None:
                rows.append((pending,))
                pending = None
            rows.append((name,))
        elif pending is None:
            pending = name
        else:
            rows.append((pending, name))
            pending = None
    if pending is not None:
        rows.append((pending,))
    return tuple(rows)


def semantic_fieldsets(model, fields):
    """Transforma uma lista de campos do ModelAdmin em seções StarHub."""
    grouped = {key: [] for key in GROUPS}
    for name in fields:
        grouped[_group_for(model, name)].append(name)

    result = []
    for key, (title, description) in GROUPS.items():
        names = grouped[key]
        if not names:
            continue
        classes = [f"section-{key}"]
        if key == "main" or len(names) > 4 or any(_wide(model, name) for name in names):
            classes.append("wide")
        if key in {"integration", "audit"}:
            classes.extend(("collapse", "collapsed"))
        result.append(
            (title, {"fields": _rows(model, names), "classes": tuple(classes), "description": description})
        )
    return tuple(result)
