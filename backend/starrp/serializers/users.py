from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from starrp.core.serializers import TenantSerializer
from starrp.core.permissions import role_rank
from starrp.models import Permission, Role, Store, UserProfile

User = get_user_model()


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = "__all__"


class RoleSerializer(TenantSerializer):
    """Cargo fixo: a conta só ajusta o desconto máximo e o "ativo"; o resto é do catálogo
    (`services/access_catalog.SYSTEM_ROLES`). O superusuário (suporte) mexe em tudo."""

    LOCKED = ("code", "name", "area", "description", "rank", "permissions", "is_account_admin")
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
        return obj.profiles.filter(deleted_at__isnull=True).count() + obj.extra_profiles.filter(
            deleted_at__isnull=True).exclude(role=obj).count()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        if request is not None and not request.user.is_superuser and self.instance is not None:  # criar: a view barra
            changed = [f for f in self.LOCKED if f in attrs and self._differs(f, attrs[f])]
            if changed:
                raise serializers.ValidationError(
                    {changed[0]: "Cargo fixo do sistema: só o desconto máximo e o ativo são ajustados pela conta."})
        return attrs

    def _differs(self, field, value):
        if self.instance is None:
            return True
        if field == "permissions":
            return {p.code for p in value} != set(self.instance.permissions.values_list("code", flat=True))
        return getattr(self.instance, field) != value


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

    def validate(self, attrs):
        """Sem escalada de acesso: quem é de filial só concede o que ele tem."""
        attrs = super().validate(attrs)
        request = self.context.get("request")
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
                raise serializers.ValidationError({"all_stores": "Só quem acessa todas as lojas concede este acesso."})
            if admin:
                raise serializers.ValidationError({"role": "Só quem acessa todas as lojas atribui o cargo de administrador."})
        if request is not None:
            above = [r for r in every if r.rank > role_rank(request.user)]
            if above:
                field = "role" if above[0] == role else "extra_roles"
                raise serializers.ValidationError({field: f"Você não pode atribuir um cargo acima do seu ({above[0].name})."})
        if not all_stores and not admin and not stores:
            raise serializers.ValidationError({"stores": "Informe ao menos uma loja (ou marque todas as lojas)."})
        default = attrs.get("default_store")
        if default is not None and not all_stores and stores and default not in stores:
            raise serializers.ValidationError({"default_store": "A loja padrão precisa estar entre as lojas do usuário."})
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
        for field, value in user_data.items():
            setattr(instance.user, field, value)
        if password:
            instance.user.set_password(password)
        instance.user.save()
        return super().update(instance, validated_data)


class MeSerializer(serializers.Serializer):
    def to_representation(self, request):
        user = request.user
        profile = getattr(request, "profile", None) or getattr(user, "profile", None)
        from starrp.core.permissions import user_permission_codes

        return {
            "id": user.pk,
            "username": user.username,
            "name": user.get_full_name() or user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "account": {"id": str(request.account.id), "name": request.account.name,
                        "modules": sorted(request.account.active_modules())} if request.account else None,
            "role": {"code": profile.role.code, "name": profile.role.name, "rank": profile.rank} if profile else None,
            "roles": [{"code": r.code, "name": r.name} for r in profile.roles_all()] if profile else [],
            "all_stores": getattr(request, "allowed_store_ids", None) is None,
            "stores": [{"id": str(store.pk), "name": store.name} for store in Store.objects.all()],
            "active_store_id": str(request.store.pk) if getattr(request, "store", None) else None,
            "is_seller": bool(profile and profile.is_seller),
            "permissions": sorted(user_permission_codes(user)),
        }
