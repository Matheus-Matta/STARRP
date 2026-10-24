"""Admin do Django para a plataforma (superusuário).

Todas as models são registradas com um admin genérico: busca por nome/código,
filtro por conta e somente-leitura nas tabelas de razão (movimentos, eventos).
Quem precisar de tela específica cria uma classe aqui e a registra antes do laço.
As models com histórico (models/history.py) ganham o botão "Histórico" do simple_history;
as tabelas Historical* não têm tela própria (são vistas por esse botão).
"""
from django.apps import apps
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

READ_ONLY = {"stockmovement", "syncevent", "auditlog", "idempotencyrecord", "commission"}
SEARCHABLE = ("name", "code", "sku", "number", "document", "description", "key", "access_key")


class StarrpAdmin(admin.ModelAdmin):
    list_per_page = 50

    def __init__(self, model, admin_site):
        names = [f.name for f in model._meta.fields]
        self.list_display = [n for n in ("__str__", "account", "store", "status", "is_active", "created_at") if
                             n == "__str__" or n in names]
        self.search_fields = [n for n in SEARCHABLE if n in names]
        self.list_filter = [n for n in ("status", "is_active", "kind") if n in names]
        self.raw_id_fields = [f.name for f in model._meta.fields if f.is_relation and f.many_to_one]
        super().__init__(model, admin_site)

    def get_queryset(self, request):
        manager = getattr(self.model, "all_objects", self.model._default_manager)
        return manager.all()

    def has_change_permission(self, request, obj=None):
        return self.model._meta.model_name not in READ_ONLY and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.model._meta.model_name not in READ_ONLY and super().has_delete_permission(request, obj)


class StarrpHistoryAdmin(SimpleHistoryAdmin, StarrpAdmin):
    """O admin genérico + o botão "Histórico" (quem mudou o quê, com a versão de cada vez)."""


for model in apps.get_app_config("starrp").get_models():
    if model.__name__.startswith("Historical"):
        continue
    if not admin.site.is_registered(model):
        admin.site.register(model, StarrpHistoryAdmin if hasattr(model, "history") else StarrpAdmin)

admin.site.site_header = "Starrp"
admin.site.site_title = "Starrp Admin"
