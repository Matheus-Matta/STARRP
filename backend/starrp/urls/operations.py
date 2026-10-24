from starrp.views import modules, operations


def register(router):
    router.register("payment-methods", operations.PaymentMethodViewSet, basename="payment-methods")
    router.register("cash/registers", operations.CashRegisterViewSet, basename="cash-registers")
    router.register("cash/sessions", operations.CashSessionViewSet, basename="cash-sessions")
    router.register("cash/movements", operations.CashMovementViewSet, basename="cash-movements")
    router.register("cash/discrepancies", operations.CashDiscrepancyViewSet, basename="cash-discrepancies")
    router.register("devices/printers", modules.PrinterViewSet, basename="printers")
    router.register("devices/print-jobs", modules.PrintJobViewSet, basename="print-jobs")
    router.register("devices/scales", modules.ScaleViewSet, basename="scales")
    router.register("devices/scale-readings", modules.ScaleReadingViewSet, basename="scale-readings")
