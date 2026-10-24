from starrp.views import modules


def register(router):
    router.register("audit-logs", modules.AuditLogViewSet, basename="audit-logs")
    router.register("notifications", modules.NotificationViewSet, basename="notifications")
    router.register("imports", modules.ImportJobViewSet, basename="imports")
    router.register("sync/nodes", modules.SyncNodeViewSet, basename="sync-nodes")
    router.register("sync/events", modules.SyncEventViewSet, basename="sync-events")
    router.register("sync/runs", modules.SyncRunViewSet, basename="sync-runs")
    router.register("sync/conflicts", modules.SyncConflictViewSet, basename="sync-conflicts")
