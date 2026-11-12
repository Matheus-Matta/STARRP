"""Tarefas em segundo plano (Configurações → Tarefas): as rodando agora e as antigas.

GET  /api/v1/background-tasks/             lista (filtros: status, kind)
GET  /api/v1/background-tasks/<id>/        o progresso
POST /api/v1/background-tasks/<id>/stop/   para a rodada: o lote em andamento termina, e o próximo não começa

Só da conta da requisição. Ver pede `catalog.view`; parar, `catalog.manage`.
"""
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.viewsets import TenantViewSet
from starrp.models import BackgroundTask
from starrp.services import background


class BackgroundTaskSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    percent = serializers.IntegerField(read_only=True)
    can_stop = serializers.BooleanField(read_only=True)
    started_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BackgroundTask
        fields = ("id", "kind", "kind_display", "status", "status_display", "done", "total", "percent", "error", "can_stop",
                  "started_by_name", "started_at", "finished_at", "updated_at")
        read_only_fields = fields

    def get_started_by_name(self, obj) -> str:
        return (obj.started_by.get_full_name() or obj.started_by.username) if obj.started_by_id else "Automática"


class BackgroundTaskViewSet(TenantViewSet):
    model = BackgroundTask
    serializer_class = BackgroundTaskSerializer
    permission_code = "catalog"
    action_permissions = {"stop": "catalog.manage"}
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("started_by",)
    filterset_fields = ("status", "kind")
    search_fields = []
    audit = False

    def get_queryset(self):
        background.expire(self.request.account)
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        from starrp.core.errors import BusinessError

        raise BusinessError("A tarefa nasce do botão que a inicia.", code="task_readonly")

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        return Response(self.get_serializer(background.stop(self.get_object())).data)
