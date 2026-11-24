from django.db import migrations


AREAS = [
    ("catalog", "Produtos e catálogo", "base"),
    ("partners", "Clientes e fornecedores", "base"),
    ("promotions", "Promoções e cupons", "base"),
    ("sales", "Vendas", "base"),
    ("cash", "Caixa", "base"),
    ("reports", "Relatórios", "base"),
    ("commissions", "Comissões", "base"),
    ("users", "Usuários e cargos", "base"),
    ("settings", "Filiais, terminais e configurações", "base"),
    ("devices", "Impressoras e balanças", "base"),
    ("stock", "Estoque", "stock"),
    ("logistics", "Logística e entrega", "base"),
    ("finance", "Financeiro", "finance"),
    ("fiscal", "Fiscal", "base"),
    ("inbound_nfe", "NF-e de entrada", "inbound_nfe"),
    ("assets", "Patrimônio", "assets"),
    ("sync", "Sincronização", "sync"),
    ("cosmos", "Assistente Cosmos (IA)", "base"),
]


def add_crud(apps, schema_editor):
    Permission = apps.get_model("starrp", "Permission")
    Role = apps.get_model("starrp", "Role")
    UserProfile = apps.get_model("starrp", "UserProfile")
    for order, (area, label, module) in enumerate(AREAS):
        created = {}
        for offset, (kind, action) in enumerate((("create", "criar"), ("update", "editar"), ("delete", "excluir")), 1):
            permission, _ = Permission._base_manager.update_or_create(
                code=f"{area}.{kind}",
                defaults={"name": f"{label}: {action}", "group": area, "module": module,
                          "sort_order": order * 10 + offset},
            )
            created[kind] = permission
        # Quem podia gerenciar continua podendo criar, editar e excluir. Leitura permanece como estava.
        for role in Role._base_manager.filter(permissions__code=f"{area}.manage").distinct():
            role.permissions.add(created["create"], created["update"], created["delete"])
        for profile in UserProfile._base_manager.filter(extra_permissions__code=f"{area}.manage").distinct():
            profile.extra_permissions.add(created["create"], created["update"], created["delete"])


def remove_crud(apps, schema_editor):
    Permission = apps.get_model("starrp", "Permission")
    codes = [f"{area}.{kind}" for area, _label, _module in AREAS for kind in ("create", "update", "delete")]
    Permission._base_manager.filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [("starrp", "0071_partners_credit_permission")]
    operations = [migrations.RunPython(add_crud, remove_crud)]
