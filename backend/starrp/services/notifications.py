"""Entrega de notificações já materializadas por usuário, com recorte de acesso."""
from starrp.models import Notification, UserProfile


CATEGORY_PERMISSION = {
    Notification.Category.SALES: "sales.view",
    Notification.Category.CASH: "cash.view",
    Notification.Category.STOCK: "stock.view",
    Notification.Category.FISCAL: "fiscal.view",
    Notification.Category.FINANCE: "finance.view",
}


def recipients(account, permission="", store=None):
    profiles = (UserProfile.all_objects.filter(
        account=account, deleted_at__isnull=True, is_active=True, user__is_active=True,
    ).select_related("user", "role").prefetch_related(
        "extra_roles__permissions", "role__permissions", "extra_permissions",
    ))
    users = []
    for profile in profiles:
        allowed = profile.allowed_store_ids()
        if store is not None and allowed is not None and store.pk not in allowed:
            continue  # o assunto é de outra filial
        if profile.is_account_admin or (permission and permission in profile.permission_codes()):
            users.append(profile.user)
    return users


def send(*, account, title, body="", category=Notification.Category.SYSTEM,
         level=Notification.Level.INFO, url="", entity="", object_id="", recipient=None, permission="",
         store=None):
    """Cria uma cópia por destinatário: cada pessoa tem seu próprio estado de leitura."""
    required = permission or CATEGORY_PERMISSION.get(category, "")
    targets = [recipient] if recipient is not None else recipients(account, required, store)
    rows = [Notification(
        account=account, recipient=user, category=category, permission=required, level=level,
        title=title, body=body, url=url, entity=entity, object_id=str(object_id or ""),
    ) for user in targets if user is not None and user.is_active]
    return Notification.all_objects.bulk_create(rows)
