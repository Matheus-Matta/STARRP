from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from starrp.core.permissions import is_account_admin, role_rank, user_permission_codes
from starrp.core.serializers import TenantSerializer
from starrp.models import Permission, Role, Store, UserProfile

User = get_user_model()


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = "__all__"


class RoleSerializer(TenantSerializer):
    """Cargo fixo: a conta ajusta desconto, ativo e permissões; identidade/hierarquia vêm do catálogo."""

    LOCKED = ("code", "name", "area", "description", "rank", "is_account_admin")
    permissions = serializers.SlugRelatedField(slug_field="code", many=True, queryset=Permission.objects.all())
    user_count = serializers.SerializerMethodField()
    permission_names = serializers.SerializerMethodField(help_text='Para ler: "Logística: gerenciar", "Estoque: ver".')

    class Meta:
        model = Role
        fields = "__all__"
        read_only_fields = ["is_system"]

    def get_permission_names(self, obj):
        return [p.name for p in sorted(obj.permissions.all(), key=lambda p: (p.sort_order, p.code))]

    def get_user_count(self, obj):
        if hasattr(obj, "main_users"):  # anotado pela RoleViewSet
            return obj.main_users + obj.extra_users
        return obj.profiles.filter(deleted_at__isnull=True).count() + obj.extra_profiles.filter(
            deleted_at__isnull=True).exclude(role=obj).count()

    def validate_permissions(self, value):
        """`manage` é interno e representa Criar + Editar + Excluir juntos."""
        selected = {permission.code: permission for permission in value}
        areas = {code.rsplit(".", 1)[0] for code in selected}
        for area in areas:
            writes = {f"{area}.{operation}" for operation in ("create", "update", "delete")}
            manage_code = f"{area}.manage"
            if writes <= selected.keys():
                manage = Permission.objects.filter(code=manage_code).first()
                if manage is not None:
                    selected[manage.code] = manage
            else:
                selected.pop(manage_code, None)
        # Nos recursos especiais, acesso total sempre carrega também o acesso normal.
        for area in ("cosmos", "pricing", "seo"):
            full_code, access_code = f"{area}.full", f"{area}.access"
            if full_code in selected and access_code not in selected:
                access = Permission.objects.filter(code=access_code).first()
                if access is not None:
                    selected[access.code] = access
        return list(selected.values())

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        if request is not None and not request.user.is_superuser and self.instance is not None:  # criar: a view barra
            changed = [f for f in self.LOCKED if f in attrs and self._differs(f, attrs[f])]
            if changed:
                raise serializers.ValidationError(
                    {changed[0]: "Cargo fixo: nome, área e nível vêm do sistema; ajuste as permissões na matriz."})
        return attrs

    def _differs(self, field, value):
        if self.instance is None:
            return True
        if field == "permissions":
            return {p.code for p in value} != set(self.instance.permissions.values_list("code", flat=True))
        return getattr(self.instance, field) != value


def target_problem(actor, profile):
    """Por que `actor` não pode mexer no usuário `profile` (S-24); `None` = pode.

    Só no seu nível ou abaixo: sem isso o Suporte de TI troca a senha, desativa ou exclui o administrador da
    conta. O admin da conta mexe em todos; ninguém (além do suporte) mexe no superusuário. Vale para editar,
    excluir e as ações em massa (ativar/desativar)."""
    if actor is None or actor.is_superuser or profile is None:
        return None
    if profile.user.is_superuser:
        return "Este usuário é do suporte e não se edita pela conta."
    if profile.user_id == actor.pk or is_account_admin(actor):
        return None
    # Estritamente abaixo (dois gerentes não trocam a senha um do outro) e SEM acesso que eu não tenho: um
    # cargo menor pode ter permissão que o meu não tem (auxiliar financeiro x TI) — trocar a senha dele
    # seria herdar esse acesso (rodada 1, P-1).
    if profile.is_account_admin or profile.rank >= role_rank(actor):
        return "Você não pode alterar um usuário do seu nível ou acima."
    mine = user_permission_codes(actor)
    if "*" not in mine and not profile.permission_codes() <= mine:
        return "Este usuário tem acesso que você não tem: só um superior altera."
    allowed, theirs = getattr(actor, "profile", None), profile.allowed_store_ids()
    mine_stores = allowed.allowed_store_ids() if allowed is not None else None
    if mine_stores is not None and (theirs is None or not set(theirs) <= set(mine_stores)):
        return "Este usuário acessa filial que você não acessa."
    return None


class UserProfileSerializer(TenantSerializer):
    """Usuário da conta: cria/edita o login (auth.User) e o perfil juntos."""

    username = serializers.CharField(source="user.username")
    first_name = serializers.CharField(source="user.first_name", required=False, allow_blank=True)
    last_name = serializers.CharField(source="user.last_name", required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, min_length=6)
    role_name = serializers.CharField(source="role.name", read_only=True)
    roles_label = serializers.SerializerMethodField(help_text="Cargo principal + somados, para a lista.")
    user_id = serializers.IntegerField(source="user.pk", read_only=True, help_text="Id do login (operadores do caixa).")
    full_name = serializers.SerializerMethodField()
    extra_permissions = serializers.SlugRelatedField(
        slug_field="code", many=True, queryset=Permission.objects.all(), required=False
    )

    class Meta:
        model = UserProfile
        exclude = ["user"]

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_roles_label(self, obj):
        return " + ".join(r.name for r in obj.roles_all())

    #: O que define o ACESSO do usuário: ninguém mexe nisso no próprio perfil (S-03).
    ACCESS_FIELDS = ("role", "extra_roles", "extra_permissions", "stores", "all_stores", "default_store",
                     "is_active", "cosmos_enabled", "is_seller", "commission_percent")

    def validate_password(self, value):
        user = self.instance.user if self.instance is not None else None
        try:
            validate_password(value, user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value

    def _check_grants(self, request, attrs, every):
        """Só concede o que tem (S-03): permissões avulsas e as dos cargos NOVOS precisam estar entre as de
        quem grava. O que o usuário já tinha fica (editar outro campo não exige ter tudo dele)."""
        if request is None or is_account_admin(request.user):
            return
        mine = user_permission_codes(request.user)
        current_perms, current_roles = set(), set()
        if self.instance is not None:
            current_perms = set(self.instance.extra_permissions.values_list("code", flat=True))
            current_roles = {self.instance.role_id, *self.instance.extra_roles.values_list("pk", flat=True)}
        if "extra_permissions" in attrs:
            added = {p.code for p in attrs["extra_permissions"]} - current_perms
            beyond = sorted(added - mine)
            if beyond:
                raise serializers.ValidationError(
                    {"extra_permissions": f"Você não pode conceder permissão que não tem ({', '.join(beyond)})."})
        for role in every:
            if role.pk in current_roles:
                continue
            beyond = sorted(set(role.permissions.values_list("code", flat=True)) - mine)
            if beyond:
                field = "role" if role == attrs.get("role") else "extra_roles"
                raise serializers.ValidationError(
                    {field: f"O cargo {role.name} dá acesso que você não tem ({', '.join(beyond[:5])})."})

    def _check_self(self, request, attrs):
        """Ninguém altera o próprio acesso (cargo, permissões, filiais, ativo, Cosmos): só nome, e-mail e senha."""
        if request is None or self.instance is None or request.user.is_superuser:
            return
        if self.instance.user_id != request.user.pk:
            return
        for field in self.ACCESS_FIELDS:
            if field not in attrs:
                continue
            value, current = attrs[field], getattr(self.instance, field, None)
            if hasattr(current, "all"):  # many-to-many
                changed = {getattr(v, "pk", v) for v in value} != set(current.values_list("pk", flat=True))
            else:
                changed = value != current
            if changed:
                raise serializers.ValidationError({field: "Você não pode alterar o seu próprio acesso. Peça a um superior."})

    def _check_target(self, request):
        """Só edita quem está no seu nível ou abaixo (S-24, `target_problem`)."""
        if request is None or self.instance is None:
            return
        problem = target_problem(request.user, self.instance)
        if problem:
            raise serializers.ValidationError(problem)

    def validate(self, attrs):
        """Sem escalada de acesso: quem é de filial só concede o que ele tem."""
        attrs = super().validate(attrs)
        request = self.context.get("request")
        self._check_target(request)
        self._check_self(request, attrs)
        allowed = getattr(request, "allowed_store_ids", None)
        stores = attrs.get("stores", getattr(self.instance, "stores", None) and list(self.instance.stores.all()))
        all_stores = attrs.get("all_stores", getattr(self.instance, "all_stores", False))
        role = attrs.get("role") or getattr(self.instance, "role", None)
        extra = attrs.get("extra_roles")
        if extra is None:
            extra = list(self.instance.extra_roles.all()) if self.instance is not None else []
        extra = [r for r in extra if role is None or r.pk != role.pk]  # o principal não se repete
        if "extra_roles" in attrs:
            attrs["extra_roles"] = extra
        every = [r for r in [role, *extra] if r is not None]
        admin = any(r.is_account_admin for r in every)
        if allowed is not None:
            if all_stores:
                raise serializers.ValidationError({"all_stores": "Só quem acessa todas as filiais concede este acesso."})
            if admin:
                raise serializers.ValidationError({"role": "Só quem acessa todas as filiais atribui o cargo de administrador."})
        if request is not None:
            above = [r for r in every if r.rank > role_rank(request.user)]
            if above:
                field = "role" if above[0] == role else "extra_roles"
                raise serializers.ValidationError({field: f"Você não pode atribuir um cargo acima do seu ({above[0].name})."})
        self._check_grants(request, attrs, every)
        if not all_stores and not admin and not stores:
            raise serializers.ValidationError({"stores": "Informe ao menos uma filial (ou marque todas as filiais)."})
        default = attrs.get("default_store")
        if default is not None and not all_stores and stores and default not in stores:
            raise serializers.ValidationError({"default_store": "A filial padrão precisa estar entre as filiais do usuário."})
        return attrs

    def validate_username(self, value):
        qs = User.objects.filter(username=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("Nome de usuário já em uso.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        user_data = validated_data.pop("user")
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Informe a senha inicial."})
        user = User.objects.create_user(password=password, **user_data)
        return super().create({**validated_data, "user": user})

    @transaction.atomic
    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        password = validated_data.pop("password", None)
        # R4-18: o link enviado ao e-mail antigo (ou antes da senha nova, ou de quem foi desligado) morre aqui.
        email = user_data.get("email", instance.user.email)
        stale_links = bool(password) or email != instance.user.email or validated_data.get("is_active") is False
        for field, value in user_data.items():
            setattr(instance.user, field, value)
        if password:
            instance.user.set_password(password)
        instance.user.save()
        if stale_links:
            from starrp.services import password_reset

            password_reset.invalidate(instance.user)
        updated = super().update(instance, validated_data)
        if password:  # S-12: senha nova derruba as sessões abertas com a antiga (depois do save do perfil)
            from starrp.services import sessions

            sessions.revoke_all(instance.user)
            updated.refresh_from_db(fields=["sessions_revoked_at"])
        return updated


class MeSerializer(serializers.Serializer):
    def to_representation(self, request):
        user = request.user
        profile = getattr(request, "profile", None) or getattr(user, "profile", None)
        from starrp.core.permissions import can_use_cosmos, is_account_admin, user_permission_codes

        return {
            "id": user.pk,
            "username": user.username,
            "name": user.get_full_name() or user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "is_account_admin": is_account_admin(user),
            "can_use_cosmos": bool(request.account and request.account.cosmos_active and can_use_cosmos(user)),
            "account": {"id": str(request.account.id), "name": request.account.name,
                        "modules": request.account.session_modules(),
                        # Logo da empresa (impressões); sem ele, a tela usa o do Starrp.
                        "logo_url": request.account.logo.file.url if request.account.logo_id else None}
            if request.account else None,
            "role": {"code": profile.role.code, "name": profile.role.name, "rank": profile.rank} if profile else None,
            "roles": [{"code": r.code, "name": r.name} for r in profile.roles_all()] if profile else [],
            "all_stores": getattr(request, "allowed_store_ids", None) is None,
            "stores": [{"id": str(store.pk), "name": store.name} for store in Store.objects.all()],
            "active_store_id": str(request.store.pk) if getattr(request, "store", None) else None,
            # Loja principal do usuário: o PDV entra nela quando a retaguarda está em "todas as lojas".
            "default_store_id": str(profile.default_store_id) if profile and profile.default_store_id else None,
            "is_seller": bool(profile and profile.is_seller),
            "permissions": sorted(user_permission_codes(user)),
        }
