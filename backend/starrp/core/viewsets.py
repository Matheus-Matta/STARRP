"""Viewsets-base. Toda view de recurso de conta herda de `TenantViewSet`.

O que ela faz, uma vez para todas:
- o queryset vem do `TenantManager` (já filtrado pela conta e sem excluídos);
- recursos com loja são filtrados pela loja ativa (`X-Store-ID`) ou pela loja
  a que o usuário está preso; cadastros com loja opcional mostram também os
  da rede (store = NULL);
- `?updated_after=` devolve só o que mudou (sincronização incremental do PDV),
  e com `include_deleted=1` inclui as exclusões;
- create/update preenchem conta/loja/autor e gravam auditoria;
- `/bulk/` executa ações em massa nos selecionados (ver `core/bulk.py`).
"""
from collections.abc import Mapping

from django.db import transaction
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ParseError, PermissionDenied, ValidationError

from starrp.core.audit import record_audit
from starrp.core.bulk import BulkActionsMixin
from starrp.models.base import store_scope_q
from starrp.models.system import AuditLog


def _store_field(model):
    try:
        return model._meta.get_field("store")
    except Exception:  # noqa: BLE001 — model sem loja
        return None


class TenantViewSet(BulkActionsMixin, viewsets.ModelViewSet):
    model = None
    select_related = ()
    prefetch_related = ()
    permission_code = None
    action_permissions = {}
    audit = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # O router e o gerador de schema leem `queryset` só para saber o model.
        if cls.model is not None:
            cls.queryset = cls.model.all_objects.none()

    # Cadastro em árvore (categoria dentro de categoria): nome do FK para o pai.
    # Liga `?root=1` (só os do topo), `?parent=<id>` (os filhos) e `children_count` em cada linha.
    tree_parent = None

    def get_queryset(self):
        return self._tree(self._base_queryset())

    def _tree(self, qs):
        if not self.tree_parent:
            return qs
        params = self.request.query_params
        qs = qs.annotate(children_count=Count(
            "children", filter=Q(children__deleted_at__isnull=True), distinct=True))
        if params.get("root") in {"1", "true"}:
            qs = qs.filter(**{f"{self.tree_parent}__isnull": True})
        if params.get("parent"):
            qs = qs.filter(**{self.tree_parent: params["parent"]})
        return qs

    def _base_queryset(self):
        if self._wants_deleted():
            qs = self.model.all_objects.filter(account=self.request.account)
            allowed = getattr(self.request, "allowed_store_ids", None)
            q = store_scope_q(self.model, allowed) if allowed is not None else None
            qs = qs.filter(q) if q is not None else qs
        else:
            qs = self.model.objects.all()
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)
        return self._scope_store(self._delta(qs))

    def _scope_store(self, qs):
        """Recorte pela loja ATIVA (seleção da tela). A SEGURANÇA — só lojas
        permitidas — já veio do manager; aqui é só "mostre esta loja"."""
        store = getattr(self.request, "store", None)
        q = store_scope_q(qs.model, [store.pk]) if store is not None else None
        return qs.filter(q) if q is not None else qs

    def _wants_deleted(self):
        params = self.request.query_params
        return bool(params.get("updated_after")) and params.get("include_deleted") in {"1", "true"}

    def _delta(self, qs):
        raw = self.request.query_params.get("updated_after")
        moment = parse_datetime(raw) if raw else None
        return qs.filter(updated_at__gt=moment) if moment else qs

    def initial(self, request, *args, **kwargs):
        if request.method in {"POST", "PUT", "PATCH"} and not isinstance(request.data, Mapping):
            raise ParseError("O corpo da requisição precisa ser um objeto JSON.")
        super().initial(request, *args, **kwargs)

    def save_kwargs(self, serializer, creating):
        model = serializer.Meta.model
        names = {f.name for f in model._meta.fields}
        extra = {"updated_by": self.request.user} if "updated_by" in names else {}
        if creating:
            extra["account"] = self.request.account
            if "created_by" in names:
                extra["created_by"] = self.request.user
            field = _store_field(model)
            if field is not None and not serializer.validated_data.get("store"):
                store = getattr(self.request, "store", None)
                # Loja opcional vazia = vale para a REDE: só quem acessa todas
                # as lojas cria isso; o usuário de uma filial grava na dele.
                if field.null and not self._restricted():
                    return extra
                if store is None:
                    raise ValidationError({"store": "Selecione a filial (header X-Store-ID)."})
                extra["store"] = store
        return extra

    def _restricted(self):
        return getattr(self.request, "allowed_store_ids", None) is not None

    def check_writable(self, instance):
        """Usuário de filial não altera cadastro que vale para a rede inteira."""
        field = _store_field(type(instance))
        if field is not None and field.null and instance.store_id is None and self._restricted():
            raise PermissionDenied("Este cadastro vale para todas as filiais; só quem acessa a rede pode alterá-lo.")

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save(**self.save_kwargs(serializer, creating=True))
        if self.audit:
            record_audit(action=AuditLog.Action.CREATED, instance=instance, actor=self.request.user, request=self.request,
                         reason=getattr(instance, "history_note", ""))

    @transaction.atomic
    def perform_update(self, serializer):
        from starrp.services import history

        self.check_writable(serializer.instance)
        before = history.snapshot(serializer.instance) if self.audit else {}
        instance = serializer.save(**self.save_kwargs(serializer, creating=False))
        if self.audit:
            # O que mudou vai junto: o histórico mostra "Preço: 50.00 → 55.00".
            # `history_note`: o serializer pode explicar o que mudou fora dos campos (ex.: variantes que saíram).
            record_audit(action=AuditLog.Action.UPDATED, instance=instance, actor=self.request.user, request=self.request,
                         changes={"fields": history.diff(before, instance)}, reason=getattr(instance, "history_note", ""))

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """Histórico do registro, paginado (`?page=&page_size=`): auditoria + acontecimentos
        do próprio registro (confirmado, conferido, cancelado...). Ver `services/history.py`."""
        from starrp.services import history

        rows = history.events(self.get_object())
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(page) if page is not None else Response(rows)

    @transaction.atomic
    def perform_destroy(self, instance):
        self.check_writable(instance)
        instance.delete()
        if self.audit:
            record_audit(action=AuditLog.Action.DELETED, instance=instance, actor=self.request.user, request=self.request)


class SystemDataViewSet(TenantViewSet):
    """Cadastro FIXO do sistema (formas de pagamento, perfis fiscais): a conta lê e ajusta
    (ativar, taxa, prazo), mas criar e excluir — inclusive a exclusão em massa — é só do
    superusuário (admin do Django). Os dados nascem com a conta (`services/system_data.py`)."""

    SYSTEM_MESSAGE = "Cadastro fixo do sistema: só o suporte cria ou exclui."

    def _require_superuser(self):
        if not self.request.user.is_superuser:
            raise PermissionDenied(self.SYSTEM_MESSAGE)

    def perform_create(self, serializer):
        self._require_superuser()
        super().perform_create(serializer)

    def perform_destroy(self, instance):
        self._require_superuser()
        super().perform_destroy(instance)

    def _available(self, model):
        names = super()._available(model)
        return names if self.request.user.is_superuser else [n for n in names if n != "delete"]


class ReadOnlyTenantViewSet(TenantViewSet):
    http_method_names = ["get", "head", "options"]
