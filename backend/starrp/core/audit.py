from django.db import transaction

from starrp.models.system import AuditLog, Notification


AUDIENCE = {
    "sale": (Notification.Category.SALES, "sales.view"),
    "salereturn": (Notification.Category.SALES, "sales.view"),
    "productreview": (Notification.Category.SALES, "sales.view"),
    "cashsession": (Notification.Category.CASH, "cash.view"),
    "cashmovement": (Notification.Category.CASH, "cash.view"),
    "stockdocument": (Notification.Category.STOCK, "stock.view"),
    "stockcount": (Notification.Category.STOCK, "stock.view"),
    "nfeissue": (Notification.Category.FISCAL, "fiscal.view"),
    "payable": (Notification.Category.FINANCE, "finance.view"),
    "receivable": (Notification.Category.FINANCE, "finance.view"),
}


def client_ip(request):
    """IP do cliente: o REMOTE_ADDR, que o uvicorn resolve do X-Forwarded-For só quando quem conecta é o
    proxy confiável (S-20). Ler o cabeçalho aqui aceitaria o IP que qualquer um escrevesse."""
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")


def record_audit(*, action, instance, actor=None, request=None, reason="", changes=None, metadata=None):
    """Grava uma linha de auditoria para `instance` (precisa ter `account_id`)."""
    account_id = getattr(instance, "account_id", None)
    if account_id is None:
        return None
    store_id = getattr(instance, "store_id", None)
    if store_id is None and instance._meta.model_name == "store":
        store_id = instance.pk
    row = AuditLog.all_objects.create(
        account_id=account_id,
        store_id=store_id,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        entity=instance._meta.model_name,
        object_id=str(instance.pk),
        reason=reason,
        changes=changes or {},
        metadata=metadata or {},
        ip_address=client_ip(request),
    )
    audience = AUDIENCE.get(instance._meta.model_name)
    if audience and action in (AuditLog.Action.APPROVED, AuditLog.Action.CANCELLED):
        category, permission = audience
        account = instance.account
        label = instance._meta.verbose_name
        title = f"{label.capitalize()} {row.get_action_display().lower()}"
        body = str(instance)[:240]

        def notify():
            from starrp.services.notifications import send

            send(account=account, title=title, body=body, category=category, permission=permission,
                 entity=instance._meta.model_name, object_id=instance.pk)

        transaction.on_commit(notify)
    return row
