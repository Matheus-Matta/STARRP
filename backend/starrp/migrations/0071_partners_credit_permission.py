from django.db import migrations


CODE = "partners.credit"
SYSTEM_CODES = {"director"}


def grant(apps, schema_editor):
    Permission = apps.get_model("starrp", "Permission")
    Role = apps.get_model("starrp", "Role")
    permission, _ = Permission._base_manager.update_or_create(
        code=CODE,
        defaults={
            "name": "Conceder crédito manual na carteira do cliente",
            "group": "partners",
            "module": "base",
            "sort_order": 506,
        },
    )
    roles = Role._base_manager.filter(deleted_at__isnull=True)
    for role in roles:
        role.permissions.remove(permission)
    for role in roles.filter(is_system=True, code__in=SYSTEM_CODES):
        role.permissions.add(permission)


def revoke(apps, schema_editor):
    apps.get_model("starrp", "Permission")._base_manager.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("starrp", "0070_historicalstorerule_allow_store_credit_refund_and_more")]
    operations = [migrations.RunPython(grant, revoke)]
