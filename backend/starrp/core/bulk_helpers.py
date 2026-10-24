"""Ajudantes das ações em massa de domínio (definir campo, somar tags)."""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from starrp.core.audit import record_audit
from starrp.core.serializers import related_scope_error
from starrp.models.system import AuditLog
from starrp.services.tags import set_tags


def related_param(request, params, name, model, label):
    """Lê o id do parâmetro e devolve o registro, conferindo conta e loja."""
    raw = params.get(name)
    if not raw:
        raise ValidationError({name: f"Escolha {label}."})
    obj = model.all_objects.filter(pk=raw, deleted_at__isnull=True).first()
    if obj is None or related_scope_error(obj, request.account):
        raise ValidationError({name: f"{label.capitalize()} inválido(a)."})
    return obj


@transaction.atomic
def set_field(view, request, queryset, field, value):
    done = 0
    for obj in queryset:
        view.check_writable(obj)
        setattr(obj, field, value)
        obj.updated_by = request.user
        obj.save(update_fields=[field, "updated_by", "updated_at"])
        record_audit(action=AuditLog.Action.UPDATED, instance=obj, actor=request.user, request=request,
                     changes={field: str(getattr(value, "pk", value))}, reason="ação em massa")
        done += 1
    return {"affected": done}


@transaction.atomic
def add_tags(view, request, queryset, params, scope):
    names = [n for n in params.get("tags") or [] if str(n).strip()]
    if not names:
        raise ValidationError({"tags": "Informe ao menos uma tag."})
    done = 0
    for obj in queryset.prefetch_related("tags"):
        view.check_writable(obj)
        current = [t.name for t in obj.tags.all() if t.deleted_at is None]
        set_tags(obj, current + names, scope, request.user)
        done += 1
    return {"affected": done}
