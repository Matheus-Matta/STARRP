from django.db import migrations
from django.db.models import F


LEVELS = (
    ("cosmos.access", "Conversa com IA — acesso normal", "cosmos", "cosmos"),
    ("cosmos.full", "Conversa com IA — acesso total", "cosmos", "cosmos"),
    ("pricing.access", "Precificação — acesso normal", "pricing", "pricing"),
    ("pricing.full", "Precificação — acesso total", "pricing", "pricing"),
    ("seo.access", "Análise SEO — acesso normal", "seo", "seo"),
    ("seo.full", "Análise SEO — acesso total", "seo", "seo"),
)
LEGACY_COSMOS = {f"cosmos.{operation}" for operation in ("view", "create", "update", "delete", "manage")}


def add_levels(apps, schema_editor):
    Permission = apps.get_model("starrp", "Permission")
    Role = apps.get_model("starrp", "Role")
    UserProfile = apps.get_model("starrp", "UserProfile")

    Permission.objects.filter(sort_order__gte=500).update(sort_order=F("sort_order") + len(LEVELS))
    created = {}
    for index, (code, name, group, module) in enumerate(LEVELS):
        created[code], _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "group": group, "module": module, "sort_order": 500 + index},
        )

    def migrate(holder, relation):
        permissions = getattr(holder, relation)
        current = set(permissions.values_list("code", flat=True))
        wanted = set()
        if "cosmos.view" in current:
            wanted.add("cosmos.access")
        if "cosmos.manage" in current:
            wanted.update(("cosmos.access", "cosmos.full"))
        if "catalog.view" in current:
            wanted.update(("pricing.access", "seo.access"))
        if "catalog.manage" in current:
            wanted.update(("pricing.access", "pricing.full", "seo.access", "seo.full"))
        if wanted:
            permissions.add(*(created[code] for code in wanted))

    for role in Role.all_objects.all().iterator():
        migrate(role, "permissions")
    for profile in UserProfile.all_objects.all().iterator():
        migrate(profile, "extra_permissions")

    # Estes cinco códigos eram a antiga linha CRUD da Cosmos. Agora os dois níveis ficam em Ações especiais.
    Permission.objects.filter(code__in=LEGACY_COSMOS).delete()


def remove_levels(apps, schema_editor):
    Permission = apps.get_model("starrp", "Permission")
    Role = apps.get_model("starrp", "Role")
    UserProfile = apps.get_model("starrp", "UserProfile")

    legacy = {}
    labels = {"view": "ver", "create": "criar", "update": "editar", "delete": "excluir",
              "manage": "executar ações"}
    for index, (operation, label) in enumerate(labels.items()):
        legacy[f"cosmos.{operation}"], _ = Permission.objects.update_or_create(
            code=f"cosmos.{operation}",
            defaults={"name": f"Assistente Cosmos (IA): {label}", "group": "cosmos", "module": "base",
                      "sort_order": 170 + index},
        )

    def restore(holder, relation):
        permissions = getattr(holder, relation)
        current = set(permissions.values_list("code", flat=True))
        wanted = set()
        if {"cosmos.access", "cosmos.full"} & current:
            wanted.add("cosmos.view")
        if "cosmos.full" in current:
            wanted.update(LEGACY_COSMOS)
        if {"pricing.access", "seo.access"} & current:
            wanted.add("catalog.view")
        if {"pricing.full", "seo.full"} & current:
            wanted.update(f"catalog.{operation}" for operation in ("view", "create", "update", "delete", "manage"))
        available = Permission.objects.filter(code__in=wanted)
        if available:
            permissions.add(*available)

    for role in Role.all_objects.all().iterator():
        restore(role, "permissions")
    for profile in UserProfile.all_objects.all().iterator():
        restore(profile, "extra_permissions")

    Permission.objects.filter(code__in=[code for code, _name, _group, _module in LEVELS]).delete()
    Permission.objects.filter(sort_order__gte=506).update(sort_order=F("sort_order") - len(LEVELS))


class Migration(migrations.Migration):
    dependencies = [("starrp", "0072_granular_crud_permissions")]
    operations = [migrations.RunPython(add_levels, remove_levels)]
