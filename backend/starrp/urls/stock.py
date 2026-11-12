from starrp.views import inbound_nfe, modules, rules, stock, wms


def register(router):
    router.register("stock/rules", rules.StockRuleViewSet, basename="stock-rules")
    router.register("stock/warehouses", stock.WarehouseViewSet, basename="warehouses")
    router.register("stock/balances", stock.StockBalanceViewSet, basename="stock-balances")
    router.register("stock/lots", stock.StockLotViewSet, basename="stock-lots")
    router.register("stock/documents", stock.StockDocumentViewSet, basename="stock-documents")
    router.register("stock/movements", stock.StockMovementViewSet, basename="stock-movements")
    router.register("stock/divergences", stock.ReceivingDivergenceViewSet, basename="receiving-divergences")
    router.register("stock/label-templates", stock.LabelTemplateViewSet, basename="label-templates")
    router.register("stock/bins", wms.StorageBinViewSet, basename="storage-bins")
    router.register("stock/bin-balances", wms.BinBalanceViewSet, basename="bin-balances")
    router.register("stock/advices", wms.StockAdviceViewSet, basename="stock-advices")
    router.register("inbound-nfe/items", inbound_nfe.InboundNFeItemViewSet, basename="inbound-nfe-items")
    router.register("inbound-nfe/events", modules.NFeEventViewSet, basename="nfe-events")
    router.register("inbound-nfe/issues", modules.NFeIssueViewSet, basename="nfe-issues")
    router.register("inbound-nfe", inbound_nfe.InboundNFeViewSet, basename="inbound-nfe")
    router.register("assets/movements", modules.AssetMovementViewSet, basename="asset-movements")
    router.register("assets/disposals", modules.AssetDisposalViewSet, basename="asset-disposals")
    router.register("assets", modules.AssetViewSet, basename="assets")
