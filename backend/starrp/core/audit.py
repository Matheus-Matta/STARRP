from starrp.models.system import AuditLog


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def record_audit(*, action, instance, actor=None, request=None, reason="", changes=None, metadata=None):
    """Grava uma linha de auditoria para `instance` (precisa ter `account_id`)."""
    account_id = getattr(instance, "account_id", None)
    if account_id is None:
        return None
    store_id = getattr(instance, "store_id", None)
    if store_id is None and instance._meta.model_name == "store":
        store_id = instance.pk
    return AuditLog.all_objects.create(
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
