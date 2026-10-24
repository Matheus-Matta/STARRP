"""Acesso: permissões, cargos e o perfil do usuário na conta.

O cargo é a única fonte de acesso. A hierarquia (`rank`) agora é um campo do
cargo, e não uma tabela fixa no código (`role_catalog.SYSTEM_ROLE_RANKS`).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from starrp.models.base import PercentField, TenantModel, alive


class Permission(models.Model):
    code = models.CharField(max_length=120, primary_key=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    group = models.CharField(max_length=80, blank=True)
    module = models.CharField(max_length=40, default="base")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["module", "sort_order", "name"]

    def __str__(self):
        return self.code


class Role(TenantModel):
    """Cargo FIXO do sistema (`services/access_catalog.SYSTEM_ROLES`): nasce com a conta e é
    sincronizado; a conta só ajusta o desconto máximo e liga/desliga. `rank` ordena a
    hierarquia: quem tem rank maior aprova o menor."""

    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    area = models.CharField(max_length=40, blank=True, help_text="Agrupa na tela: Direção, Vendas, Logística...")
    description = models.CharField(max_length=255, blank=True, help_text="O que o cargo faz no sistema.")
    rank = models.PositiveSmallIntegerField(default=10)
    permissions = models.ManyToManyField(Permission, blank=True, related_name="roles")
    max_discount_percent = PercentField(help_text="Desconto máximo sem pedir autorização.")
    is_account_admin = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False, help_text="Criado pela plataforma; não pode ser apagado.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-rank", "name"]
        constraints = [
            models.UniqueConstraint(fields=["account", "code"], condition=alive(), name="uniq_role_code"),
        ]

    def __str__(self):
        return self.name


class UserProfile(TenantModel):
    """O vínculo do login com a conta: cargo, lojas e dados de vendedor.

    Isolamento por loja: o usuário só enxerga dados das `stores` dele, a menos
    que `all_stores` (ou cargo de administrador da conta). Um gerente de duas
    filiais tem as duas em `stores`; o caixa de uma loja, só ela.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="profile", on_delete=models.CASCADE)
    role = models.ForeignKey(Role, related_name="profiles", on_delete=models.PROTECT, help_text="Cargo principal.")
    # Cargos somados ao principal (ex.: logística + financeiro): permissões se somam,
    # vale o maior nível e o maior desconto. Ver `roles_all`.
    extra_roles = models.ManyToManyField(Role, blank=True, related_name="extra_profiles")
    all_stores = models.BooleanField(default=False, help_text="Acessa todas as lojas da conta, inclusive as futuras.")
    stores = models.ManyToManyField("starrp.Store", blank=True, related_name="profiles")
    default_store = models.ForeignKey(
        "starrp.Store", null=True, blank=True, related_name="+", on_delete=models.SET_NULL,
        help_text="Loja aberta por padrão quando a requisição não informa X-Store-ID.",
    )
    phone = models.CharField(max_length=32, blank=True)
    extra_permissions = models.ManyToManyField(Permission, blank=True, related_name="profiles")
    # Vendedor: código digitado no PDV e comissão padrão.
    is_seller = models.BooleanField(default=False)
    seller_code = models.CharField(max_length=20, blank=True)
    commission_percent = PercentField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "seller_code"],
                condition=alive() & ~models.Q(seller_code=""),
                name="uniq_seller_code",
            ),
        ]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.get_username()} ({self.role})"

    def roles_all(self):
        """O cargo principal e os somados (só os ativos e não excluídos)."""
        extra = [r for r in self.extra_roles.all() if r.deleted_at is None and r.is_active]
        return [self.role, *[r for r in extra if r.pk != self.role_id]]

    @property
    def is_account_admin(self):
        return any(r.is_account_admin for r in self.roles_all())

    @property
    def rank(self):
        return max(r.rank for r in self.roles_all())

    @property
    def max_discount_percent(self):
        return max(r.max_discount_percent for r in self.roles_all())

    def allowed_store_ids(self):
        """`None` = todas as lojas; senão, o conjunto de ids das lojas dele."""
        if self.all_stores or self.is_account_admin:
            return None
        return set(self.stores.filter(deleted_at__isnull=True).values_list("pk", flat=True))

    def permission_codes(self):
        codes = set(Permission.objects.filter(roles__in=[r.pk for r in self.roles_all()]).values_list("code", flat=True))
        codes.update(self.extra_permissions.values_list("code", flat=True))
        return codes


class PasswordResetRequest(models.Model):
    """Token de redefinição de senha: só o hash é persistido."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="password_resets", on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()


class FirstAccessState(models.Model):
    """Marca permanente: o bootstrap do primeiro superusuário já aconteceu."""

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    completed_at = models.DateTimeField(default=timezone.now, editable=False)
