"""Views dos módulos com CRUD declarativo: promoções, fiscal, NF-e de entrada,
patrimônio, dispositivos, sistema e sincronização."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from starrp.core.errors import StateConflict
from starrp.core.permissions import IsAccountAdmin
from starrp.core.viewsets import ReadOnlyTenantViewSet, TenantViewSet
from starrp.models import (
    Asset, AssetDisposal, AssetMovement, AuditLog, Coupon, DiscountTable, FiscalProfile, FiscalSeries,
    ImportJob, Integration, NFeEvent, NFeIssue, Notification, Printer, PrintJob,
    Promotion, PromotionProduct, Scale, ScaleReading, SyncConflict, SyncEvent, SyncNode, SyncRun,
)
from starrp.models.platform import Module
from starrp.serializers import misc as s


def crud(name, model, serializer, code, module=Module.BASE, base=TenantViewSet, **attrs):
    """Monta um viewset declarativo. Só para cadastros SEM regra própria."""
    return type(name, (base,), {"model": model, "serializer_class": serializer, "permission_code": code,
                                "required_module": module, **attrs})


DiscountTableViewSet = crud("DiscountTableViewSet", DiscountTable, s.DiscountTableSerializer, "promotions",
                            filterset_fields=["store", "is_enabled"], search_fields=["name"],
                            prefetch_related=("rules__categories", "rules__brands", "rules__product_links__product"))
PromotionViewSet = crud("PromotionViewSet", Promotion, s.PromotionSerializer, "promotions",
                        filterset_fields=["table", "target", "is_enabled"], search_fields=["name"])
PromotionProductViewSet = crud("PromotionProductViewSet", PromotionProduct, s.PromotionProductSerializer,
                               "promotions", filterset_fields=["promotion", "product"])
CouponViewSet = crud("CouponViewSet", Coupon, s.CouponSerializer, "promotions",
                     filterset_fields=["is_enabled", "kind", "store"], search_fields=["code", "name"])

class FiscalProfileViewSet(TenantViewSet):
    """Perfis fiscais: a conta cria os seus; os pré-prontos do sistema não são excluídos."""

    model = FiscalProfile
    serializer_class = s.FiscalProfileSerializer
    permission_code = "fiscal"
    filterset_fields = ["is_active", "is_system"]
    search_fields = ["name"]

    def perform_destroy(self, instance):
        if instance.is_system:
            raise StateConflict("Perfil pré-pronto do sistema: desative em vez de excluir.")
        super().perform_destroy(instance)
FiscalSeriesViewSet = crud("FiscalSeriesViewSet", FiscalSeries, s.FiscalSeriesSerializer, "fiscal", Module.FISCAL,
                           filterset_fields=["config", "document_model"])

NFeEventViewSet = crud("NFeEventViewSet", NFeEvent, s.NFeEventSerializer, "inbound_nfe", Module.INBOUND_NFE,
                       ReadOnlyTenantViewSet, filterset_fields=["nfe", "direction", "status", "event_code"])
NFeIssueViewSet = crud("NFeIssueViewSet", NFeIssue, s.NFeIssueSerializer, "inbound_nfe", Module.INBOUND_NFE,
                       http_method_names=["get", "patch", "head", "options"], filterset_fields=["nfe", "status"])


AssetViewSet = crud("AssetViewSet", Asset, s.AssetSerializer, "assets", Module.ASSETS,
                    filterset_fields=["status", "location", "product", "responsible"],
                    search_fields=["code", "description", "serial_number"])
AssetMovementViewSet = crud("AssetMovementViewSet", AssetMovement, s.AssetMovementSerializer, "assets",
                            Module.ASSETS, filterset_fields=["asset"])
AssetDisposalViewSet = crud("AssetDisposalViewSet", AssetDisposal, s.AssetDisposalSerializer, "assets",
                            Module.ASSETS, filterset_fields=["kind"])

PrinterViewSet = crud("PrinterViewSet", Printer, s.PrinterSerializer, "devices",
                      filterset_fields=["terminal", "purpose", "is_active"])
ScaleViewSet = crud("ScaleViewSet", Scale, s.ScaleSerializer, "devices", filterset_fields=["terminal", "is_active"])
ScaleReadingViewSet = crud("ScaleReadingViewSet", ScaleReading, s.ScaleReadingSerializer, "devices",
                           http_method_names=["get", "post", "head", "options"], filterset_fields=["scale"],
                           action_permissions={"create": None, "list": None})
PrintJobViewSet = crud("PrintJobViewSet", PrintJob, s.PrintJobSerializer, "devices",
                       filterset_fields=["printer", "status", "kind", "sale"],
                       action_permissions={"list": None, "retrieve": None, "partial_update": None})

AuditLogViewSet = crud("AuditLogViewSet", AuditLog, s.AuditLogSerializer, "users", base=ReadOnlyTenantViewSet,
                       filterset_fields=["entity", "object_id", "action", "actor"], audit=False)
ImportJobViewSet = crud("ImportJobViewSet", ImportJob, s.ImportJobSerializer, "settings",
                        http_method_names=["get", "post", "head", "options"])


class NotificationViewSet(TenantViewSet):
    model = Notification
    serializer_class = s.NotificationSerializer
    http_method_names = ["get", "post", "head", "options"]
    audit = False

    def get_queryset(self):
        from django.db.models import Q

        return super().get_queryset().filter(Q(recipient=self.request.user) | Q(recipient__isnull=True))

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        item = self.get_object()
        item.read_at = timezone.now()
        item.save(update_fields=["read_at", "updated_at"])
        return Response(self.get_serializer(item).data)


class IntegrationViewSet(viewsets.ModelViewSet):
    queryset = Integration.objects.none()
    serializer_class = s.IntegrationSerializer
    permission_classes = [IsAccountAdmin]

    def get_queryset(self):
        return Integration.objects.filter(account=self.request.account)

    def perform_create(self, serializer):
        serializer.save(account=self.request.account)


class _SyncReadOnly(viewsets.ReadOnlyModelViewSet):
    required_module = Module.SYNC
    permission_code = "sync"
    sync_model = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.queryset = cls.sync_model.objects.none() if cls.sync_model else None

    def get_queryset(self):
        return self.sync_model.objects.filter(account=self.request.account)


SyncNodeViewSet = type("SyncNodeViewSet", (_SyncReadOnly,), {"sync_model": SyncNode,
                                                             "serializer_class": s.SyncNodeSerializer})
SyncEventViewSet = type("SyncEventViewSet", (_SyncReadOnly,), {"sync_model": SyncEvent,
                                                               "serializer_class": s.SyncEventSerializer,
                                                               "filterset_fields": ["status", "direction",
                                                                                    "entity_type"]})
SyncRunViewSet = type("SyncRunViewSet", (_SyncReadOnly,), {"sync_model": SyncRun,
                                                           "serializer_class": s.SyncRunSerializer})
SyncConflictViewSet = type("SyncConflictViewSet", (_SyncReadOnly,), {"sync_model": SyncConflict,
                                                                     "serializer_class": s.SyncConflictSerializer})
