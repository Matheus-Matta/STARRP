"""Ações em massa nas listas, como as "actions" do Django admin.

Toda view de cadastro ganha:

    GET  /<recurso>/bulk/   → ações disponíveis para este usuário (rótulo, ícone, se pede parâmetro)
    POST /<recurso>/bulk/   → executa: {"action": "delete", "ids": [...]}
                              ou {"action": "delete", "all": true} + os MESMOS filtros da lista na URL
                              (?search=…&category=…) para valer para todos os que a tela mostra.

Padrões, quando fazem sentido para o model: excluir, ativar/desativar,
ligar/desligar e exportar CSV. Cada view acrescenta as suas com o decorador
(o método se chama `bulk_<nome>`; a ação é `<nome>`):

    @bulk_action("Definir categoria", icon="pi pi-sitemap",
                 params=[{"name": "category", "label": "Categoria", "type": "relation",
                          "relation": {"endpoint": "/catalog/categories/"}, "required": True}])
    def bulk_set_category(self, request, queryset, params):
        ...
        return {"affected": n}

Excluir passa objeto a objeto pela MESMA regra da exclusão unitária
(`perform_destroy`): o que não pode sair volta em `skipped` com o motivo.
"""
import csv
import io
import re
from decimal import Decimal

from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response

from starrp.core.audit import record_audit
from starrp.core.errors import BusinessError
from starrp.core.permissions import has_permission_code
from starrp.models.system import AuditLog

MAX_ITEMS = 5000
DECIMAL_TEXT = re.compile(r"^-?\d+\.\d+$")


def bulk_action(label, *, icon="pi pi-bolt", danger=False, confirm="", params=None, permission="manage"):
    """Marca o método da view como ação em massa. `permission`: "manage", "view" ou um código completo."""
    def mark(func):
        func.bulk = {"label": label, "icon": icon, "danger": danger, "confirm": confirm, "params": params or [],
                     "permission": permission}
        return func
    return mark


def _has_field(model, name):
    return any(f.name == name for f in model._meta.fields)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if isinstance(value, (Decimal, float)):
        return f"{value}".replace(".", ",")
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(v) for v in value)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("label") or value.get("id") or "")
    # Decimal vem do serializer como texto ("25.00"): no Excel BR o separador é vírgula.
    if isinstance(value, str) and DECIMAL_TEXT.match(value):
        return value.replace(".", ",")
    return str(value)


class BulkActionsMixin:
    bulk_disabled = ()  # nomes de ações padrão que a view não quer

    # ── Ações padrão ─────────────────────────────────────────────────────────
    @bulk_action("Excluir selecionados", icon="pi pi-trash", danger=True,
                 confirm="Excluir os itens selecionados? A ação fica registrada na auditoria.")
    def bulk_delete(self, request, queryset, params):
        done, skipped = 0, []
        for obj in queryset:
            try:
                with transaction.atomic():
                    self.perform_destroy(obj)
                done += 1
            except (APIException, ProtectedError, PermissionError) as error:
                reason = getattr(error, "detail", None) or "Está em uso em outro cadastro."
                skipped.append({"id": str(obj.pk), "label": str(obj), "reason": str(reason)})
        return {"affected": done, "skipped": skipped}

    def _set_flag(self, request, queryset, field, value):
        done = 0
        for obj in queryset.exclude(**{field: value}):
            self.check_writable(obj)
            setattr(obj, field, value)
            fields = [field, "updated_at"] + (["updated_by"] if _has_field(type(obj), "updated_by") else [])
            if "updated_by" in fields:
                obj.updated_by = request.user
            obj.save(update_fields=fields)
            if self.audit:
                record_audit(action=AuditLog.Action.UPDATED, instance=obj, actor=request.user, request=request,
                             changes={field: value}, reason="ação em massa")
            done += 1
        return {"affected": done}

    @bulk_action("Ativar", icon="pi pi-check-circle")
    def bulk_activate(self, request, queryset, params):
        return self._set_flag(request, queryset, "is_active", True)

    @bulk_action("Desativar", icon="pi pi-ban")
    def bulk_deactivate(self, request, queryset, params):
        return self._set_flag(request, queryset, "is_active", False)

    @bulk_action("Ligar", icon="pi pi-play")
    def bulk_enable(self, request, queryset, params):
        return self._set_flag(request, queryset, "is_enabled", True)

    @bulk_action("Desligar", icon="pi pi-pause")
    def bulk_disable(self, request, queryset, params):
        return self._set_flag(request, queryset, "is_enabled", False)

    @bulk_action("Exportar CSV", icon="pi pi-file-export", permission="view")
    def bulk_export(self, request, queryset, params):
        """CSV com as colunas da tela (`params.columns`: [{key, label}]), separado por ";" para o Excel BR."""
        columns = params.get("columns") or [{"key": "id", "label": "id"}]
        rows = self.get_serializer(queryset, many=True).data
        out = io.StringIO()
        out.write("﻿")  # BOM: o Excel abre os acentos certos
        writer = csv.writer(out, delimiter=";")
        writer.writerow([c.get("label") or c["key"] for c in columns])
        for row in rows:
            writer.writerow([_text((c.get("map") or {}).get(str(row.get(c["key"])), row.get(c["key"]))) for c in columns])
        name = f"{getattr(self.model, '__name__', 'dados').lower()}-{timezone.localdate():%Y%m%d}.csv"
        response = HttpResponse(out.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    # ── Descoberta e execução ────────────────────────────────────────────────
    def _available(self, model):
        names = []
        for attr in dir(type(self)):
            func = getattr(type(self), attr, None)
            name = attr.removeprefix("bulk_")
            if not attr.startswith("bulk_") or not hasattr(func, "bulk") or name in self.bulk_disabled:
                continue
            if name in {"delete", "activate", "deactivate", "enable", "disable"}:
                writable = "delete" in getattr(self, "http_method_names", []) if name == "delete" else (
                    "patch" in getattr(self, "http_method_names", []))
                field = {"activate": "is_active", "deactivate": "is_active", "enable": "is_enabled",
                         "disable": "is_enabled"}.get(name)
                if not writable or (field and not _has_field(model, field)):
                    continue
            names.append(name)
        return names

    def _allowed(self, request, meta):
        code = meta["permission"]
        if code in {"manage", "view"}:
            base = getattr(self, "permission_code", None)
            if base is None:
                return True
            code = f"{base}.{code}"
        return has_permission_code(request.user, code)

    @action(detail=False, methods=["get", "post"], url_path="bulk")
    def bulk(self, request):
        model = self.model
        meta = {n: getattr(type(self), f"bulk_{n}").bulk for n in self._available(model)}
        available = [n for n in meta if self._allowed(request, meta[n])]
        if request.method == "GET":
            # Exportar primeiro, ações do cadastro no meio, ligar/desligar depois, excluir por último.
            rank = {"export": -1, "activate": 1, "deactivate": 2, "enable": 3, "disable": 4, "delete": 9}
            available.sort(key=lambda n: (rank.get(n, 0), meta[n]["label"]))
            return Response([{"name": n, **{k: v for k, v in meta[n].items() if k != "permission"}} for n in available])
        name = request.data.get("action")
        if name not in available:
            raise PermissionDenied("Ação indisponível para este cadastro ou para o seu cargo.")
        queryset = self.filter_queryset(self.get_queryset())
        if not request.data.get("all"):
            ids = request.data.get("ids")
            if not isinstance(ids, list) or not ids:
                raise ValidationError({"ids": "Selecione ao menos um item."})
            queryset = queryset.filter(pk__in=ids)
        total = queryset.count()
        if total > MAX_ITEMS:
            raise BusinessError(f"São {total} itens: o limite por vez é {MAX_ITEMS}. Filtre a lista antes.",
                                code="bulk_too_many")
        params = request.data.get("params") or {}
        result = getattr(self, f"bulk_{name}")(request, queryset, params)
        if isinstance(result, HttpResponse):
            return result
        result.setdefault("skipped", [])
        result["total"] = total
        return Response(result)
