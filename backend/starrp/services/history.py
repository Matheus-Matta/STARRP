"""Histórico de um registro (o "feed" no fim da página de cada cadastro).

Junta três fontes, da mais nova para a mais antiga:

1. a auditoria (`AuditLog`): criado, alterado (com o que mudou: "Preço: 50,00 → 55,00"),
   excluído — com quem fez, o motivo e o IP (o que passou pela API de cadastro);
2. o histórico do django-simple-history (`models/history.py`): TODA gravação, inclusive
   as dos serviços (venda, estoque, caixa), do admin e de tarefas. Entra aqui a alteração
   que a auditoria não tem (a mesma edição feita pela API aparece uma vez só);
3. os acontecimentos que o próprio registro guarda: `posted_at` + `posted_by`
   viram "Confirmado · Ana", `checked_at` vira "Conferido", `cancelled_at`
   "Cancelado"... Saem do registro, então valem também para o que foi feito
   antes de existir a auditoria e nunca se repetem.

Ex.: GET /stock/documents/{id}/history/?page=1&page_size=10
"""
from django.contrib.auth import get_user_model
from django.db import models

from starrp.models import AuditLog

# Campo de data/hora do registro → (rótulo, tom, ícone). O autor vem do `<prefixo>_by` se houver.
MOMENTS = {
    "opened": ("Aberto", "brand", "pi pi-lock-open"),
    "checked": ("Conferido", "info", "pi pi-list-check"),
    "posted": ("Confirmado", "success", "pi pi-check"),
    "completed": ("Concluído", "success", "pi pi-check"),
    "authorized": ("Autorizado", "success", "pi pi-verified"),
    "approved": ("Aprovado", "info", "pi pi-verified"),
    "closed": ("Fechado", "success", "pi pi-lock"),
    "ready": ("Separado", "info", "pi pi-box"),
    "shipped": ("Saiu para entrega", "info", "pi pi-truck"),
    "delivered": ("Entregue", "success", "pi pi-home"),
    "paid": ("Pago", "success", "pi pi-wallet"),
    "cancelled": ("Cancelado", "danger", "pi pi-times"),
    "ignored": ("Ignorado", "neutral", "pi pi-eye-slash"),
    "revoked": ("Revogado", "danger", "pi pi-ban"),
}
ACTIONS = {
    AuditLog.Action.CREATED: ("Criado", "brand", "pi pi-plus"),
    AuditLog.Action.UPDATED: ("Alterado", "neutral", "pi pi-pencil"),
    AuditLog.Action.DELETED: ("Excluído", "danger", "pi pi-trash"),
    AuditLog.Action.CANCELLED: ("Cancelado", "danger", "pi pi-times"),
    AuditLog.Action.APPROVED: ("Aprovado", "info", "pi pi-verified"),
    AuditLog.Action.PRINTED: ("Impresso", "neutral", "pi pi-print"),
}
IGNORED = {"updated_at", "updated_by", "created_at", "created_by", "deleted_at", "account", "id", "position"}


def _names(user_ids):
    users = get_user_model().objects.filter(pk__in={u for u in user_ids if u})
    return {u.pk: u.get_full_name() or u.username for u in users}


def _show(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    return str(value)


def diff(before, instance):
    """O que mudou entre o retrato de antes (`snapshot`) e o registro salvo:
    [{"key": "price", "field": "Price", "from": "50.00", "to": "55.00"}] (a tela troca pelo rótulo do formulário). Só campos simples e FKs (pelo id)."""
    after = snapshot(instance)
    labels = {f.attname: str(f.verbose_name).capitalize() for f in instance._meta.concrete_fields}
    return [{"key": name, "field": labels.get(name, name), "from": _show(before.get(name)), "to": _show(value)}
            for name, value in after.items() if before.get(name) != value]


def snapshot(instance):
    """Valores atuais dos campos simples (texto, número, data, FK pelo id)."""
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in IGNORED or isinstance(field, (models.JSONField, models.FileField)):
            continue
        value = getattr(instance, field.attname)
        data[field.attname] = value if isinstance(value, (bool, int, type(None))) else str(value)
    return data


SAME_EDIT_SECONDS = 5  # auditoria e histórico da mesma gravação nascem juntos
HISTORY_LIMIT = 300


def _history_rows(instance, logs):
    """Alterações do histórico que a auditoria não registrou, com o que mudou."""
    manager = getattr(instance, "history", None)
    if manager is None:
        return [], []
    records = list(manager.order_by("-history_date")[:HISTORY_LIMIT])[::-1]
    skip = {f.name for f in instance._meta.concrete_fields
            if f.name in IGNORED or isinstance(f, (models.JSONField, models.FileField))}
    skip |= {f"{prefix}_{end}" for prefix in MOMENTS for end in ("at", "by")}  # já viram "Confirmado", "Cancelado"...
    labels = {f.name: str(f.verbose_name).capitalize() for f in instance._meta.concrete_fields}
    # A mesma gravação feita pela API tem auditoria E histórico: é a mesma se nasceu junto,
    # pelo mesmo usuário, levando os MESMOS campos aos MESMOS valores (só o tempo esconderia
    # outra mudança vizinha, como um serviço que regrava o campo logo depois).
    audited = [(log.created_at, log.actor_id, log.action,
                frozenset((c.get("key"), c.get("to")) for c in (log.changes or {}).get("fields", []) if isinstance(c, dict)))
               for log in logs if log.action in (AuditLog.Action.UPDATED, AuditLog.Action.DELETED)]
    out, users = [], []
    for before, record in zip(records, records[1:], strict=False):
        if record.history_type != "~":
            continue
        delta = record.diff_against(before, excluded_fields=list(skip))
        changes = [{"key": c.field, "field": labels.get(c.field, c.field), "from": _show(c.old), "to": _show(c.new)}
                   for c in delta.changes]
        deleted = bool(record.deleted_at and not before.deleted_at)
        if not changes and not deleted:
            continue
        keys = frozenset((_attname(instance, c["key"]), c["to"]) for c in changes)
        if any(abs((record.history_date - at).total_seconds()) <= SAME_EDIT_SECONDS
               and actor in (None, record.history_user_id)
               and ((deleted and action == AuditLog.Action.DELETED) or (not deleted and keys <= fields))
               for at, actor, action, fields in audited):
            continue
        label, tone, icon = ACTIONS[AuditLog.Action.DELETED] if deleted else ACTIONS[AuditLog.Action.UPDATED]
        out.append({"id": f"h{record.history_id}", "kind": "deleted" if deleted else "updated", "label": label,
                    "tone": tone, "icon": icon, "at": record.history_date, "by": record.history_user_id,
                    "note": record.history_change_reason or "", "changes": changes})
        users.append(record.history_user_id)
    return out, users


def _attname(instance, name):
    """A auditoria guarda o `attname` (FK como `category_id`); o histórico, o nome do campo."""
    try:
        return instance._meta.get_field(name).attname
    except Exception:  # noqa: BLE001 (campo que saiu da model: fica o nome)
        return name


def events(instance):
    """Todos os acontecimentos do registro, do mais novo para o mais antigo."""
    logs = list(AuditLog.all_objects.filter(entity=instance._meta.model_name, object_id=str(instance.pk),
                                            account_id=instance.account_id).order_by("-created_at"))
    moments = []
    for field in instance._meta.concrete_fields:
        prefix = field.name.removesuffix("_at")
        if prefix in MOMENTS and isinstance(field, models.DateTimeField) and getattr(instance, field.name):
            by = getattr(instance, f"{prefix}_by_id", None)
            moments.append((prefix, getattr(instance, field.name), by))
    history, history_users = _history_rows(instance, logs)
    names = _names([log.actor_id for log in logs] + [by for _, _, by in moments]
                   + [getattr(instance, "created_by_id", None)] + history_users)
    rows = []
    for log in logs:
        label, tone, icon = ACTIONS.get(log.action, (log.get_action_display(), "neutral", "pi pi-circle"))
        changes = log.changes.get("fields", []) if isinstance(log.changes, dict) else []
        rows.append({"id": str(log.pk), "kind": log.action, "label": label, "tone": tone, "icon": icon,
                     "at": log.created_at, "by": names.get(log.actor_id, ""), "note": log.reason, "changes": changes})
    moment_rows = []
    for prefix, at, by in moments:
        label, tone, icon = MOMENTS[prefix]
        moment_rows.append({"id": f"{prefix}:{instance.pk}", "kind": prefix, "label": label, "tone": tone,
                            "icon": icon, "at": at, "by": names.get(by, ""), "note": "", "changes": []})
    for row in history:
        # A gravação do "Confirmar"/"Cancelar" muda a situação junto: o que mudou vai no próprio
        # acontecimento ("Confirmado · Ana" com "Situação: rascunho → confirmado"), sem linha a mais.
        moment = next((m for m in moment_rows if abs((row["at"] - m["at"]).total_seconds()) <= SAME_EDIT_SECONDS), None)
        if moment is not None:
            moment["changes"] = [*moment["changes"], *row["changes"]]
            moment["by"] = moment["by"] or names.get(row["by"], "")
            continue
        rows.append({**row, "by": names.get(row["by"], "")})
    rows.extend(moment_rows)
    if not any(log.action == AuditLog.Action.CREATED for log in logs) and getattr(instance, "created_at", None):
        rows.append({"id": f"created:{instance.pk}", "kind": "created", "label": "Criado", "tone": "brand",
                     "icon": "pi pi-plus", "at": instance.created_at,
                     "by": names.get(getattr(instance, "created_by_id", None), ""), "note": "", "changes": []})
    return sorted(rows, key=lambda row: row["at"], reverse=True)
