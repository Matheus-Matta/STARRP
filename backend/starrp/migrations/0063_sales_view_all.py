from django.db import migrations

CODE = "sales.view_all"


def grant_view_all(apps, schema_editor):
    """Nova permissão "ver as vendas de toda a equipe". Nada muda para quem já via vendas: todo cargo com
    `sales.view` (fixo ou criado pela conta) ganha a nova — menos o cargo fixo Vendedor, que passa a ver só
    as próprias vendas."""
    Permission = apps.get_model("starrp", "Permission")
    Role = apps.get_model("starrp", "Role")
    permission, _ = Permission._base_manager.update_or_create(
        code=CODE, defaults={"name": "Ver as vendas de toda a equipe (sem ela, só as próprias)", "group": "sales",
                             "module": "base", "sort_order": 500})
    for role in Role._base_manager.filter(permissions__code="sales.view").distinct():
        if role.is_system and role.code == "seller":
            continue
        role.permissions.add(permission)


def revoke(apps, schema_editor):
    apps.get_model("starrp", "Permission")._base_manager.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("starrp", "0062_integration_webhook_event"),
    ]

    operations = [migrations.RunPython(grant_view_all, revoke)]
