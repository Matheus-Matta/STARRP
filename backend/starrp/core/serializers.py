"""Serializer-base de tudo que pertence a uma conta.

- `account`, auditoria e `deleted_at` são somente-leitura: vêm do contexto;
- todo objeto relacionado informado precisa ser da MESMA conta (barra
  referência cruzada entre tenants, que o FK sozinho não impede);
- número negativo é recusado por padrão (preço, quantidade, desconto), salvo
  os campos listados em `Meta.signed_fields`.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from rest_framework import serializers

READ_ONLY_BASE = ("id", "account", "created_at", "updated_at", "created_by", "updated_by", "deleted_at")


class TenantSerializer(serializers.ModelSerializer):
    def get_fields(self):
        fields = super().get_fields()
        signed = set(getattr(self.Meta, "signed_fields", ()))
        for name in READ_ONLY_BASE:
            if name in fields:
                fields[name].read_only = True
        # Loja obrigatória vem da loja ativa (X-Store-ID) quando omitida.
        if "store" in fields and not fields["store"].read_only:
            fields["store"].required = False
        for name, field in fields.items():
            if field.read_only or name in signed:
                continue
            if isinstance(field, (serializers.DecimalField, serializers.IntegerField)) and field.min_value is None:
                floor = Decimal("0") if isinstance(field, serializers.DecimalField) else 0
                field.min_value = floor
                field.validators.append(MinValueValidator(floor, message="O valor não pode ser negativo."))
        return fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.parent is None:  # só no registro aberto: na lista seria uma consulta por linha
            data.update(user_names(instance, data, self.context))
        if hasattr(instance, "children_count"):  # cadastro em árvore (`TenantViewSet.tree_parent`)
            data["children_count"] = instance.children_count
        return data

    def get_uniqueness_extra_kwargs(self, field_names, declared_fields, extra_kwargs):
        # O DRF lê as UniqueConstraint e marca os campos delas como OBRIGATÓRIOS —
        # inclusive em constraint condicional ("único quando preenchido"), o que
        # tornava obrigatório o código de vendedor. A unicidade é do banco: viola
        # e o handler devolve 409 com mensagem clara.
        return extra_kwargs, {}

    def get_validators(self):
        from rest_framework.validators import UniqueTogetherValidator

        return [v for v in super().get_validators() if not isinstance(v, UniqueTogetherValidator)]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        account = getattr(request, "account", None)
        if account is None:
            return attrs
        errors = {}
        for name, value in attrs.items():
            related = value if isinstance(value, (list, tuple)) else [value]
            for obj in related:
                message = related_scope_error(obj, account)
                if message:
                    errors[name] = message
                    break
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


def user_names(instance, data, context):
    """`<campo>_name` de cada FK para usuário (criado/confirmado/conferido/cancelado por...):
    a linha do tempo da tela de leitura mostra QUEM fez, não o id."""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    cache = context.setdefault("_user_names", {})
    names = {}
    for field in instance._meta.concrete_fields:
        key = f"{field.name}_name"
        if not field.is_relation or field.related_model is not user_model or data.get(key):
            continue
        user_id = getattr(instance, field.attname)
        if user_id is None:
            continue
        if user_id not in cache:
            user = user_model.objects.filter(pk=user_id).only("first_name", "last_name", "username").first()
            cache[user_id] = (user.get_full_name() or user.username) if user else ""
        names[key] = cache[user_id]
    return names


def related_scope_error(obj, account):
    """O registro relacionado é visível para quem está gravando?

    Pergunta ao próprio `TenantManager` (conta + lojas permitidas): uma regra
    só para os dois níveis. O FK sozinho aceitaria o id de outra conta ou de
    outra filial, porque o Django só confere que o registro EXISTE.
    """
    if not hasattr(obj, "_meta"):
        return None
    obj_account = getattr(obj, "account_id", None)
    if obj_account is not None and obj_account != account.id:
        return "Registro relacionado pertence a outra conta."
    manager = getattr(type(obj), "objects", None)
    from starrp.models.base import TenantManager

    if isinstance(manager, TenantManager) and not manager.filter(pk=obj.pk).exists():
        return "Registro relacionado pertence a uma loja à qual você não tem acesso."
    return None


def tenant_serializer(model_cls, fields="__all__", exclude=None, read_only=(), extra=None):
    """Fábrica para os cadastros simples (evita dezenas de classes iguais)."""
    meta_attrs = {"model": model_cls, "read_only_fields": tuple(read_only)}
    if exclude:
        meta_attrs["exclude"] = exclude
    else:
        meta_attrs["fields"] = fields
    attrs = {"Meta": type("Meta", (), meta_attrs), **(extra or {})}
    return type(f"{model_cls.__name__}Serializer", (TenantSerializer,), attrs)


class TenantPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """FK por id resolvida na conta da requisição NO MOMENTO da validação.

    `queryset=Model.objects.all()` seria avaliado na importação, sem conta no
    contexto — e o `TenantManager` devolveria vazio para sempre.
    """

    def __init__(self, model, **kwargs):
        self.model = model
        kwargs.setdefault("queryset", model.all_objects.none())
        super().__init__(**kwargs)

    def get_queryset(self):
        return self.model.objects.all()
