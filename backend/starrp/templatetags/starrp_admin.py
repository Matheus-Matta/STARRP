"""Agrupamento do menu administrativo pelos domínios do ERP."""
from django import template

register = template.Library()

GROUPS = (
    ("Usuários e acesso", "users-round", {"Group", "User", "Permission", "Role", "UserProfile", "PasswordResetRequest", "FirstAccessState"}),
    ("Plataforma", "settings-2", {"Plan", "Account", "Subscription", "SystemSetting", "Integration", "Store", "Terminal"}),
    ("Catálogo", "package", {"Image", "ProductImage", "Category", "Brand", "Product", "ServiceRule", "KitComponent", "SupplierProduct", "Attribute", "AttributeValue", "ProductVariant", "VariantValue", "ProductBarcode", "ProductVolume", "Tag"}),
    ("Clientes e fornecedores", "users-round", {"CustomerGroup", "Customer", "CustomerAddress", "Supplier"}),
    ("Regras e logística", "truck", {"StoreRule", "LogisticsRule", "StockRule", "FreightTable", "FreightZipRange", "ZipCoordinate", "ZipDistance", "MetafieldDefinition", "Warehouse", "StorageBin"}),
    ("Promoções", "star", {"DiscountTable", "Promotion", "PromotionProduct", "Coupon", "CouponRedemption"}),
    ("Vendas e caixa", "shopping-cart", {"Sale", "SaleItem", "Commission", "SaleAddress", "SaleReturn", "SaleReturnItem", "CustomerCredit", "PaymentMethod", "Payment", "CashRegister", "CashSession", "CashMovement", "CashDiscrepancy"}),
    ("Fiscal", "file-text", {"FiscalProfile", "FiscalConfig", "FiscalSeries", "Invoice", "InvoiceItem", "DFeSyncState", "DFeDocument", "InboundNFe", "InboundNFeItem", "NFeEvent", "NFeIssue"}),
    ("Estoque", "archive", {"StockBalance", "StockLot", "StockMovement", "StockDocument", "StockDocumentItem", "ReceivingDivergence", "LabelTemplate", "BinBalance", "StockAdvice"}),
    ("Patrimônio", "folder", {"Asset", "AssetMovement", "AssetDisposal"}),
    ("Financeiro", "wallet", {"FinancialAccount", "FinancialCategory", "FinancialTitle", "Installment", "FinancialTransaction"}),
    ("Dispositivos", "plug", {"Printer", "Scale", "ScaleReading", "PrintJob"}),
    ("Avaliações", "message-square-text", {"Review", "ReviewLink"}),
    ("Cosmos", "message-square-text", {"CosmosConversation", "CosmosMessage", "CosmosAction", "CosmosAttachment", "CosmosReport", "CosmosFinding", "CosmosUsage"}),
    ("Mercado e SEO", "trending-up", {"PriceSourceToken", "PriceUsage", "PriceCheck", "MarketOffer", "CompetitorPrice", "SeoCredential", "SeoUsage", "KeywordMetric", "SeoCheck"}),
    ("Sincronização", "plug", {"SyncNode", "SyncEvent", "SyncRun", "SyncConflict", "SyncDiscard", "SyncDirty", "SyncFileTransfer", "SyncEnrollmentTicket"}),
    ("Sistema", "settings-2", {"AuditLog", "IdempotencyRecord", "NumberSequence", "Notification", "ImportJob", "BackgroundTask", "BlacklistedToken", "OutstandingToken"}),
)


@register.simple_tag
def admin_menu_groups(app_list):
    models = [model for app in app_list for model in app.get("models", ()) if model.get("admin_url")]
    by_name = {model.get("object_name"): model for model in models}
    grouped = []
    used = set()
    for label, icon, object_names in GROUPS:
        items = [by_name[name] for name in object_names if name in by_name]
        if items:
            items.sort(key=lambda item: str(item["name"]).casefold())
            grouped.append({"name": label, "icon": icon, "items": items})
            used.update(item["object_name"] for item in items)
    remaining = sorted((model for model in models if model.get("object_name") not in used), key=lambda item: str(item["name"]).casefold())
    if remaining:
        grouped.append({"name": "Outros", "icon": "layout-list", "items": remaining})
    return grouped
