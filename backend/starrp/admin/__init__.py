"""Admin do Django para a plataforma (superusuário).

Todas as models são registradas com um admin genérico: busca por nome/código,
filtro por conta e somente-leitura nas tabelas de razão (movimentos, eventos).
Quem precisar de tela específica cria uma classe aqui e a registra antes do laço.
As models com histórico (models/history.py) ganham o botão "Histórico" do simple_history;
as tabelas Historical* não têm tela própria (são vistas por esse botão).
"""
from datetime import timedelta

from django import forms
from django.apps import apps
from django.contrib import admin
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from starrp.models import Account, CosmosUsage, Module, PriceSourceToken, PriceUsage, SeoCredential, SeoUsage
from starrp.services.cosmos import usage
from starrp.services.market import sources as price_sources
from starrp.services.seo import keywords as seo_keywords

READ_ONLY = {"stockmovement", "syncevent", "auditlog", "idempotencyrecord", "commission", "cosmosusage"}
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


class CosmosUsageInline(admin.TabularInline):
    """Consumo da Cosmos dia a dia (últimos 31), dentro da conta. Só leitura: quem soma é o sistema."""

    model = CosmosUsage
    extra = 0
    can_delete = False
    fields = readonly_fields = ("day", "requests", "prompt_tokens", "cached_tokens", "completion_tokens", "total_tokens")
    ordering = ("-day",)
    max_num = 0
    verbose_name_plural = "Consumo da Cosmos (últimos 31 dias)"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(day__gte=timezone.localdate() - timedelta(days=30))


class PriceUsageInline(admin.TabularInline):
    """Consultas às fontes de preço com chave, por mês. Só leitura: quem soma é o sistema."""

    model = PriceUsage
    extra = 0
    can_delete = False
    fields = readonly_fields = ("month", "source", "requests")
    max_num = 0


class PriceTokenForm(forms.ModelForm):
    """A chave nunca volta para a tela: em branco mantém a que já está gravada."""

    token = forms.CharField(label="Chave", required=False, max_length=255, help_text="Em branco mantém a atual.",
                            widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))

    class Meta:
        model = PriceSourceToken
        fields = ("source", "token", "option")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["token"] = ""

    def clean_token(self):
        value = self.cleaned_data["token"]
        if value:
            return value
        if self.instance.pk:
            return self.instance.token
        raise forms.ValidationError("Informe a chave.")


class PriceTokenInline(admin.TabularInline):
    model = PriceSourceToken
    form = PriceTokenForm
    extra = 0
    fields = ("source", "token", "option", "ending")
    readonly_fields = ("ending",)

    @admin.display(description="Termina em")
    def ending(self, obj):
        return f"••••{obj.token[-4:]}" if obj.pk else "—"


class SeoUsageInline(admin.TabularInline):
    """Consultas de palavras-chave por mês. Só leitura: quem soma é o sistema."""

    model = SeoUsage
    extra = 0
    can_delete = False
    fields = readonly_fields = ("month", "requests")
    max_num = 0


class SeoCredentialForm(forms.ModelForm):
    """Os segredos nunca voltam para a tela: em branco mantém o que já está gravado."""

    SECRETS = ("client_secret", "refresh_token", "developer_token")
    client_secret = forms.CharField(label="OAuth client secret", required=False, max_length=255, help_text="Em branco mantém o atual.",
                                    widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))
    refresh_token = forms.CharField(label="Refresh token", required=False, max_length=512, help_text="Em branco mantém o atual.",
                                    widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))
    developer_token = forms.CharField(label="Developer token", required=False, max_length=255,
                                      help_text="Só para projeto antigo. Em branco mantém o atual.",
                                      widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))

    class Meta:
        model = SeoCredential
        fields = ("client_id", "client_secret", "refresh_token", "customer_id", "login_customer_id", "developer_token")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.SECRETS:
            self.initial[name] = ""

    def clean(self):
        data = super().clean()
        for name in self.SECRETS:
            if not data.get(name):
                data[name] = getattr(self.instance, name, "") if self.instance.pk else ""
                if name != "developer_token" and not data[name] and data.get("client_id"):
                    self.add_error(name, "Informe este campo.")
        return data


class SeoCredentialInline(admin.StackedInline):
    model = SeoCredential
    form = SeoCredentialForm
    extra = 0
    max_num = 1
    verbose_name_plural = "Credencial própria da busca de palavras-chave (SEO), no lugar da global do .env"


class AccountAdminForm(forms.ModelForm):
    extra_modules = forms.MultipleChoiceField(
        label="Módulos liberados além do plano", required=False, widget=forms.CheckboxSelectMultiple,
        choices=[choice for choice in Module.choices if choice[0] != Module.BASE])
    price_sources = forms.CharField(
        label="Fontes de preço, em ordem", required=False, widget=forms.Textarea(attrs={"rows": 5, "cols": 30}),
        help_text="Uma por linha: a ordem é a fila de execução. A pesquisa da equipe (manual) é sempre ativa e não precisa estar aqui. "
                  "Opções: " + ", ".join(price_sources.SOURCES))

    class Meta:
        model = Account
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        chosen = self.initial.get("price_sources") or []
        self.initial["price_sources"] = "\n".join(chosen) if isinstance(chosen, list) else chosen

    def clean_price_sources(self):
        keys = [line.strip() for line in self.cleaned_data["price_sources"].splitlines() if line.strip()]
        unknown = [key for key in keys if key not in price_sources.SOURCES]
        if unknown:
            raise forms.ValidationError(f"Fonte desconhecida: {', '.join(unknown)}.")
        return list(dict.fromkeys(["manual", *keys]))


def _tokens(value):
    return f"{value:,}".replace(",", ".")


@admin.register(Account)
class AccountAdmin(StarrpHistoryAdmin):
    """Conta com o controle da plataforma: módulos, Cosmos (IA) e precificação (limite, consumo e chaves próprias)."""

    form = AccountAdminForm
    readonly_fields = ("cosmos_usage_now", "price_usage_now", "price_sources_ready", "seo_usage_now")

    def get_inlines(self, request, obj):
        secret = [PriceTokenInline, SeoCredentialInline] if request.user.is_superuser else []
        return [CosmosUsageInline, PriceUsageInline, SeoUsageInline, *secret]

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        self.list_display = [*self.list_display, "cosmos_enabled", "cosmos_usage_now"]
        self.list_filter = [*self.list_filter, "cosmos_enabled"]

    @admin.display(description="Consumo da Cosmos agora")
    def cosmos_usage_now(self, obj):
        if obj.pk is None:
            return "—"
        rows = usage.limits(obj)
        if not rows:
            return f"Sem limite · {_tokens(usage.spent(obj, 'month'))} tokens neste mês"
        names = {"day": "hoje", "week": "na semana", "month": "no mês"}
        return " · ".join(f"{names[period]}: {_tokens(used)} de {_tokens(limit)} ({used * 100 // limit}%)"
                          for period, limit, used in rows)

    @admin.display(description="Consultas de busca neste mês")
    def seo_usage_now(self, obj):
        if obj.pk is None:
            return "—"
        used, limit = seo_keywords.used_this_month(obj), obj.seo_monthly_requests
        ready = "credencial pronta" if seo_keywords.configured(obj) else "sem credencial: só regras"
        return f"{_tokens(used)} de {_tokens(limit)} · {ready}" if limit else f"{_tokens(used)} (sem limite) · {ready}"

    @admin.display(description="Fontes prontas para usar")
    def price_sources_ready(self, obj):
        if obj.pk is None:
            return "—"
        return " · ".join(f"{row['label']}: {'pronta' if row['ready'] else 'falta chave'}" for row in price_sources.status(obj))

    @admin.display(description="Consultas de preço neste mês")
    def price_usage_now(self, obj):
        if obj.pk is None:
            return "—"
        used, limit = price_sources.used_this_month(obj), obj.price_monthly_requests
        return f"{_tokens(used)} de {_tokens(limit)} ({used * 100 // limit}%)" if limit else f"{_tokens(used)} (sem limite)"


for model in apps.get_app_config("starrp").get_models():
    # A chave própria só aparece dentro da conta, mascarada; a tela genérica mostraria o valor.
    if model.__name__.startswith("Historical") or model in (PriceSourceToken, SeoCredential):
        continue
    if not admin.site.is_registered(model):
        admin.site.register(model, StarrpHistoryAdmin if hasattr(model, "history") else StarrpAdmin)

admin.site.site_header = "Starrp — Administração"
admin.site.site_title = "Starrp Admin"
admin.site.index_title = "Visão geral"
