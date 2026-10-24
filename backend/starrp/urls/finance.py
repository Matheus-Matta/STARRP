from starrp.views import finance, fiscal, modules


def register(router):
    router.register("finance/accounts", finance.FinancialAccountViewSet, basename="financial-accounts")
    router.register("finance/categories", finance.FinancialCategoryViewSet, basename="financial-categories")
    router.register("finance/titles", finance.FinancialTitleViewSet, basename="financial-titles")
    router.register("finance/installments", finance.InstallmentViewSet, basename="installments")
    router.register("finance/transactions", finance.FinancialTransactionViewSet, basename="financial-transactions")
    router.register("fiscal/profiles", modules.FiscalProfileViewSet, basename="fiscal-profiles")
    router.register("fiscal/configs", fiscal.FiscalConfigViewSet, basename="fiscal-configs")
    router.register("fiscal/series", modules.FiscalSeriesViewSet, basename="fiscal-series")
    router.register("fiscal/invoices", fiscal.InvoiceViewSet, basename="invoices")
