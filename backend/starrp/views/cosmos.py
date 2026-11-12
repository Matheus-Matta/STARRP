"""API REST da Cosmos. A conversa em si corre pelo WebSocket (`views/cosmos_socket.py`);
aqui ficam a lista de conversas, o histórico de mensagens, o download dos relatórios e os
alertas da supervisão.

    GET    /cosmos/status/                         ligada? o que este usuário pode
    GET    /cosmos/conversations/                  as conversas DELE (mais recente primeiro)
    GET    /cosmos/conversations/{id}/messages/    as falas visíveis, na ordem
    PATCH  /cosmos/conversations/{id}/             {"title": "..."}
    DELETE /cosmos/conversations/{id}/
    POST   /cosmos/attachments/                    multipart `file`: planilha/CSV/texto para a conversa
    GET    /cosmos/reports/{id}/export/?formato=xlsx|csv
    GET    /cosmos/findings/?status=open           alertas (quem supervisiona)
    POST   /cosmos/findings/{id}/resolve/          {"status": "resolved" | "dismissed"}
"""
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from starrp.core.permissions import has_permission_code
from starrp.core.viewsets import TenantViewSet
from starrp.models import CosmosConversation, CosmosFinding, CosmosReport, Module
from starrp.serializers.cosmos import CosmosConversationSerializer, CosmosFindingSerializer
from starrp.services.cosmos import agent, attachments, rpc
from starrp.services.cosmos import report as cosmos_report


class CosmosStatusView(APIView):
    def get(self, request):
        return Response(rpc.status_payload(request.user, request.account))


class CosmosConversationViewSet(TenantViewSet):
    model = CosmosConversation
    serializer_class = CosmosConversationSerializer
    permission_code = "cosmos"
    required_module = Module.COSMOS
    # A conversa é de quem conversa: renomear e apagar a própria não exige `cosmos.manage`.
    action_permissions = {"partial_update": "cosmos.view", "update": "cosmos.view", "destroy": "cosmos.view",
                          "messages": "cosmos.view"}
    http_method_names = ["get", "patch", "delete", "head", "options"]
    audit = False

    def get_queryset(self):
        # Sem o recorte pela filial ativa: a conversa acompanha o usuário em qualquer filial.
        return rpc.conversations_of(self.request.user, self.request.query_params.get("q", ""))

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        rows = [agent.message_payload(m) for m in conversation.messages.order_by("position") if agent.visible(m)]
        return Response({"conversation": agent.conversation_payload(conversation), "messages": rows})


class CosmosAttachmentView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        if not (request.account.cosmos_active and has_permission_code(request.user, "cosmos.view")):
            raise PermissionDenied("Você não tem permissão para usar a Cosmos.")
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Envie o arquivo."})
        try:
            attachment = attachments.create(request.account, request.user, upload)
        except attachments.AttachmentError as error:
            raise ValidationError({"file": str(error)}) from error
        return Response(attachments.payload(attachment), status=201)


class CosmosReportExportView(APIView):
    def get(self, request, pk):
        if not request.account.cosmos_active:
            raise PermissionDenied("Você não tem permissão para usar a Cosmos.")
        report = CosmosReport.objects.filter(pk=pk, created_by=request.user).first()
        if report is None:
            raise NotFound("Relatório não encontrado.")
        formato = "csv" if request.query_params.get("formato") == "csv" and report.data.get("blocks") else "xlsx"
        content, kind, name = cosmos_report.export(report, request.user, formato)
        response = HttpResponse(content, content_type=kind)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response


class CosmosFindingViewSet(TenantViewSet):
    model = CosmosFinding
    serializer_class = CosmosFindingSerializer
    permission_code = "cosmos"
    required_module = Module.COSMOS
    action_permissions = {"list": "cosmos.supervise", "retrieve": "cosmos.supervise", "resolve": "cosmos.supervise"}
    http_method_names = ["get", "post", "head", "options"]
    select_related = ("actor", "store")
    filterset_fields = ("status", "severity", "rule", "actor")
    audit = False

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        finding = self.get_object()
        status = request.data.get("status", CosmosFinding.Status.RESOLVED)
        if status not in (CosmosFinding.Status.RESOLVED, CosmosFinding.Status.DISMISSED):
            raise ValidationError({"status": "Use resolved ou dismissed."})
        finding.status, finding.resolved_by, finding.resolved_at = status, request.user, timezone.now()
        finding.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])
        return Response(self.get_serializer(finding).data)
