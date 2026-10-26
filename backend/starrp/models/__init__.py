"""Todas as models do Starrp, organizadas por domínio (um arquivo por assunto).

Importe sempre daqui: `from starrp.models import Sale`.
"""
from starrp.models.platform import (  # noqa: F401
    Module,
    Plan,
    Account,
    Subscription,
    SystemSetting,
    Integration,
)
from starrp.models.company import (  # noqa: F401
    Store,
    Terminal,
)
from starrp.models.users import (  # noqa: F401
    Permission,
    Role,
    UserProfile,
    PasswordResetRequest,
    FirstAccessState,
)
from starrp.models.media import (  # noqa: F401
    Image,
    ProductImage,
)
from starrp.models.catalog import (  # noqa: F401
    Unit,
    Category,
    Brand,
    Product,
    ServiceRule,
    KitComponent,
    SupplierProduct,
)
from starrp.models.variants import (  # noqa: F401
    Attribute,
    AttributeValue,
    ProductVariant,
    VariantValue,
    ProductBarcode,
)
from starrp.models.volumes import (  # noqa: F401
    ProductVolume,
)
from starrp.models.tags import (  # noqa: F401
    Tag,
)
from starrp.models.logistics import (  # noqa: F401
    FreightTable,
    FreightZipRange,
    LogisticsSettings,
    ZipCoordinate,
    ZipDistance,
)
from starrp.models.metafields import MetafieldDefinition  # noqa: F401
from starrp.models.partners import (  # noqa: F401
    PersonType,
    CustomerGroup,
    Customer,
    CustomerAddress,
    Supplier,
)
from starrp.models.promotions import (  # noqa: F401
    DiscountTable,
    Promotion,
    PromotionProduct,
    Coupon,
    CouponRedemption,
)
from starrp.models.sales import (  # noqa: F401
    SaleChannel,
    PaymentStatus,
    FulfillmentStatus,
    OverallStatus,
    Sale,
    SaleItem,
    Commission,
)
from starrp.models.returns import (  # noqa: F401
    SaleReturn,
    SaleReturnItem,
    CustomerCredit,
)
from starrp.models.payments import (  # noqa: F401
    PaymentMethod,
    Payment,
)
from starrp.models.cash import (  # noqa: F401
    CashRegister,
    CashSession,
    CashMovement,
    CashDiscrepancy,
)
from starrp.models.fiscal import (  # noqa: F401
    DocumentModel,
    Environment,
    FiscalProfile,
    FiscalConfig,
    FiscalSeries,
)
from starrp.models.invoices import (  # noqa: F401
    Invoice,
    InvoiceItem,
)
from starrp.models.inbound_nfe import (  # noqa: F401
    DFeSyncState,
    DFeDocument,
    InboundNFe,
    InboundNFeItem,
)
from starrp.models.nfe_events import (  # noqa: F401
    NFeEvent,
    NFeIssue,
)
from starrp.models.stock import (  # noqa: F401
    StockSettings,
    Warehouse,
    StockBalance,
    StockLot,
    StockMovement,
)
from starrp.models.stock_documents import (  # noqa: F401
    ConferenceMode,
    DivergenceReason,
    ReceivingDivergence,
    StockDocument,
    StockDocumentItem,
)
from starrp.models.labels import (  # noqa: F401
    LabelTemplate,
)
from starrp.models.wms import (  # noqa: F401
    BinBalance,
    StorageBin,
)
from starrp.models.assets import (  # noqa: F401
    Asset,
    AssetMovement,
    AssetDisposal,
)
from starrp.models.finance import (  # noqa: F401
    FinancialAccount,
    FinancialCategory,
    TitleStatus,
    FinancialTitle,
    Installment,
    FinancialTransaction,
)
from starrp.models.devices import (  # noqa: F401
    Printer,
    Scale,
    ScaleReading,
    PrintJob,
)
from starrp.models.system import (  # noqa: F401
    AuditLog,
    IdempotencyRecord,
    NumberSequence,
    Notification,
    ImportJob,
)
from starrp.models.reviews import Review  # noqa: F401
from starrp.models.sync import (  # noqa: F401
    SyncEnvironment,
    NodeType,
    NodeStatus,
    Direction,
    Operation,
    EventStatus,
    RunType,
    RunStatus,
    ConflictResolution,
    ConflictStatus,
    SyncNode,
    SyncEvent,
)
from starrp.models.sync_records import (  # noqa: F401
    SyncRun,
    SyncConflict,
    SyncDiscard,
    SyncDirty,
    SyncFileTransfer,
    SyncEnrollmentTicket,
)

# Por último, com todas as models importadas: histórico em todas (ver models/history.py).
from starrp.models.base import TimeStampedModel  # noqa: E402
from starrp.models.history import track_history  # noqa: E402

HISTORY_TRACKED = track_history(TimeStampedModel)
