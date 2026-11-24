from django.db import migrations

CODE = "catalog.view_costs"
# Cargos FIXOS que veem custo e margem (o mesmo de services/access_catalog.py; o sync_permissions do
# deploy reaplica o catálogo). Caixa, vendedor, líder de vendas, logística, patrimônio e TI ficam sem.
SYSTEM_CODES = {"director", "manager", "supervisor", "stock_lead", "comprador", "stockist", "financeiro",
                "finance_assistant", "fiscal", "marketing", "auditor"}


def grant(apps, schema_editor):
    """Nova permissão "ver custo e margem". Cargo criado pela conta (não fixo) ganha a permissão: hoje
    ele vê custo, e tirar é decisão do administrador. Cargo fixo segue o catálogo."""
    Permission = apps.get_model("starrp", "Permission")
    Role = apps.get_model("starrp", "Role")
    permission, _ = Permission._base_manager.update_or_create(
        code=CODE, defaults={"name": "Ver custo e margem dos produtos e das vendas", "group": "catalog",
                             "module": "base", "sort_order": 510})
    for role in Role._base_manager.filter(deleted_at__isnull=True):
        if not role.is_system or role.code in SYSTEM_CODES:
            role.permissions.add(permission)


def revoke(apps, schema_editor):
    apps.get_model("starrp", "Permission")._base_manager.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("starrp", "0063_sales_view_all"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
