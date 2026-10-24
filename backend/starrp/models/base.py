"""Classes-base e campos padronizados de todas as models.

Hierarquia (uma só, sem variações paralelas):

    UUIDModel -> TimeStampedModel -> TenantModel -> StoreModel

- `TenantModel`: pertence a uma conta, é auditado (quem criou/alterou) e tem
  exclusão lógica (`deleted_at`). É o único mecanismo de soft-delete.
- `StoreModel`: além da conta, pertence a UMA loja (obrigatório).
- Cadastros que valem para a rede inteira OU para uma loja declaram
  `store = optional_store_fk()` — vazio significa "todas as lojas".

O `TenantManager` filtra pela conta da requisição e esconde excluídos.
`all_objects` é o acesso cru, para tarefas de plataforma e migrações.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from starrp.core.tenant import get_allowed_store_ids, get_current_account
# Reexportados: as migrations referenciam `starrp.models.base.MoneyField` etc.
from starrp.models.fields import MoneyField, PercentField, QuantityField, UnitCostField  # noqa: F401


def user_fk(related_name, **kwargs):
    """FK para usuário que sobrevive à exclusão dele (o histórico fica)."""
    kwargs.setdefault("null", True)
    kwargs.setdefault("blank", True)
    kwargs.setdefault("on_delete", models.SET_NULL)
    return models.ForeignKey(settings.AUTH_USER_MODEL, related_name=related_name, **kwargs)


def optional_store_fk(related_name="%(class)s_set"):
    """Loja opcional: vazio = vale para todas as lojas da conta."""
    return models.ForeignKey(
        "starrp.Store",
        null=True,
        blank=True,
        related_name=related_name,
        on_delete=models.PROTECT,
        help_text="Vazio = vale para todas as lojas.",
    )


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # `updated_at` em microssegundos é a VERSÃO do registro na sincronização.
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def active(self):
        qs = self.alive()
        if any(f.name == "is_active" for f in self.model._meta.fields):
            qs = qs.filter(is_active=True)
        return qs

    def delete(self):
        return self.update(deleted_at=timezone.now())


def store_scope_q(model, store_ids):
    """Filtro "pertence a uma destas lojas" para `model`.

    Cada model diz por onde chega à loja (`store_lookup`, ex.: "sale__store").
    `store_lookup = None` = cadastro da conta inteira, sem recorte por loja.
    Com `store_shared_when_null`, linha sem loja vale para a rede e aparece.
    """
    lookup = getattr(model, "store_lookup", None)
    if lookup is None:
        return None
    q = models.Q(**{f"{lookup}__in": store_ids})
    if getattr(model, "store_shared_when_null", False):
        q |= models.Q(**{f"{lookup}__isnull": True})
    return q


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Escopo automático: conta da requisição, lojas permitidas, sem excluídos.

    Sem conta no contexto devolve VAZIO, nunca a base inteira: um esquecimento
    vira "não achei" em vez de vazamento entre contas ou entre lojas.
    """

    def get_queryset(self):
        account = get_current_account()
        qs = super().get_queryset()
        if account is None:
            return qs.none()
        qs = qs.filter(account=account, deleted_at__isnull=True)
        allowed = get_allowed_store_ids()
        if allowed is not None:
            q = store_scope_q(self.model, allowed)
            if q is not None:
                qs = qs.filter(q)
        return qs


class AliveManager(models.Manager.from_queryset(TenantQuerySet)):
    """Sem os excluídos, mas sem exigir conta no contexto.

    É o manager das relações reversas (`venda.items`) e do admin: elas já
    chegam filtradas pelo pai, e precisam funcionar em tarefas de fundo.
    """

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class UnscopedManager(models.Manager.from_queryset(TenantQuerySet)):
    pass


class TenantModel(TimeStampedModel):
    # Caminho até a loja (None = cadastro da conta inteira). Ver `store_scope_q`.
    store_lookup = None
    store_shared_when_null = False

    account = models.ForeignKey("starrp.Account", related_name="+", on_delete=models.PROTECT)
    created_by = user_fk("+")
    updated_by = user_fk("+")
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    alive_objects = AliveManager()
    objects = TenantManager()
    all_objects = UnscopedManager()

    class Meta:
        abstract = True
        # Relações reversas usam o default (sem excluídos); FK direta usa o base
        # (cru), para que um item de venda ainda enxergue o produto excluído.
        default_manager_name = "alive_objects"
        base_manager_name = "all_objects"

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class StoreModel(TenantModel):
    store_lookup = "store"

    store = models.ForeignKey("starrp.Store", related_name="%(class)s_set", on_delete=models.PROTECT)

    class Meta(TenantModel.Meta):
        abstract = True


def alive(**extra):
    """Condição de constraint única que ignora os excluídos logicamente.

    Sem ela, um registro excluído seguraria o nome/código para sempre.
    """
    return models.Q(deleted_at__isnull=True, **extra)
