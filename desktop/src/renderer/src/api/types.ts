/**
 * Tipos de domínio do PDV, espelhando os serializers do backend (o frontend web os gera do
 * OpenAPI em `frontend/src/api/schema.d.ts`; aqui só o que o PDV usa).
 */
export type Approval = { username: string; password: string } | { cash_password: string };

export type Me = {
  id: number;
  username: string;
  name: string;
  email: string;
  account: { id: string; name: string; modules: string[]; logo_url: string | null } | null;
  role: { code: string; name: string } | null;
  roles: { code: string; name: string }[];
  all_stores: boolean;
  stores: { id: string; name: string }[];
  active_store_id: string | null;
  default_store_id: string | null;
  permissions: string[];
};

export type Seller = { user_id: number; name: string; code: string };

export type SaleItem = {
  id: string;
  description: string;
  sku?: string;
  unit?: string;
  quantity?: string;
  list_price?: string;
  unit_price?: string;
  discount?: string;
  total?: string;
  status?: "active" | "cancelled" | string;
  variant: string;
  promotion?: string | null;
  parent_item?: string | null;
};

export type Payment = {
  id: string;
  method?: string;
  method_name: string;
  method_kind: string;
  amount?: string;
  tendered_amount?: string;
  change_amount?: string;
  installments?: number;
  status?: string;
  nsu?: string;
};

export type Sale = {
  id: string;
  number: number;
  items: SaleItem[];
  payments: Payment[];
  balance_due: string;
  seller_name: string;
  addresses: Record<string, unknown>;
  status: "open" | "draft" | "completed" | "cancelled" | string;
  overall_status: string;
  payment_status: string;
  fulfillment_status: string;
  parked_at: string | null;
  created_at: string;
  completed_at: string | null;
  customer_document: string;
  customer_name: string;
  customer_credit_balance?: string;
  store_credit_refund_allowed?: boolean;
  subtotal: string;
  discount: string;
  coupon_code: string;
  coupon_discount: string;
  freight: string;
  total: string;
  paid_amount: string;
  change_amount: string;
  notes: string;
  metafields: unknown;
  seller: number | null;
  customer: string | null;
  shipping_address: string | null;
  cancel_reason: string;
  invoices?: InvoiceSummary[];
  operator_name?: string;
  channel?: string;
  refunded_amount?: string;
  ready_at?: string | null;
  shipped_at?: string | null;
  delivered_at?: string | null;
  shipping_address_detail?: Record<string, string> | null;
};

/** Linha da lista de pedidos (`GET /sales/`). */
export type SaleRow = Pick<Sale, "id" | "number" | "created_at" | "customer_name" | "seller_name" | "total" | "status"
  | "overall_status" | "payment_status" | "fulfillment_status" | "channel"> & { item_count?: number };

export type PaymentMethod = {
  id: string;
  name: string;
  kind: string;
  requires_reference?: boolean;
  max_installments?: number;
};

export type CashSession = {
  id: string;
  register: string;
  register_name: string;
  opened_by_name: string;
  status: "open" | "pending_opening" | "pending_approval" | "closed" | string;
  opened_at: string;
  opening_amount: string;
  expected_now: string;
  expected_amount: string;
  difference: string;
  closed_at: string | null;
  counted_amount: string | null;
  pending_movements: number;
};

export type CashRegister = { id: string; name: string; in_use_by?: string | null; operator_name?: string };

export type CashMovement = {
  id: string;
  kind: "withdrawal" | "supply" | string;
  amount: string;
  status: "pending" | "approved" | "rejected" | string;
  reason: string;
  operator_name: string;
  created_at: string;
};

export type StoreRule = {
  require_open_cash_session?: boolean;
  require_seller?: boolean;
  auto_print_receipt?: boolean;
  confirm_address_at_checkout?: boolean;
  require_payment_reference?: boolean;
  allow_store_credit_refund?: boolean;
};

export type PdvBootstrap = {
  sees_drawer: boolean;
  server_time: string;
  store: { id: string; name: string; legal_name?: string; document?: string; phone?: string; [key: string]: unknown };
  rules: StoreRule;
  terminal: { id: string; name?: string };
  payment_methods: PaymentMethod[];
  cash_registers: CashRegister[];
  my_register: string | null;
  cash_session: CashSession | null;
  sellers: Seller[];
  mode: "seller" | "cashier";
  lock_minutes: number;
  has_cash_action_password: boolean;
  /** Limites do operador (o PDV local decide o que pede gerente). */
  operator?: { max_discount_percent: string };
};

export type PdvProductView = {
  id: string;
  name: string;
  type: string;
  unit: string;
  sale_method: string;
  reference: string;
  category_name: string | null;
  brand_name: string | null;
  /** HTML já limpo no backend. */
  description: string;
  images: string[];
  axes: { id: string; name: string; values: { id: string; value: string }[] }[];
  variants: {
    id: string;
    sku: string;
    name: string;
    is_default: boolean;
    price: string;
    current_price: string;
    stock: string | null;
    barcode: string;
    options: Record<string, string>;
    images: string[];
  }[];
  services: { variant: string; name: string; sku: string; price: string; description: string }[];
  specs: { key: string; label: string; value: unknown; text: string }[];
};

export type VariantLookup = {
  id: string;
  display_name: string;
  sku: string;
  current_price: string;
  list_price: string;
  sold_by_weight: boolean;
  stock_quantity: string | null;
};

export type Address = {
  id?: string;
  label: string;
  zip_code: string;
  street: string;
  number: string;
  complement: string;
  district: string;
  city: string;
  state: string;
  city_ibge?: string;
  reference: string;
  is_default: boolean;
};

export type Customer = {
  id: string;
  name: string;
  document: string;
  phone: string;
  email: string;
  credit_balance?: string;
  addresses?: Address[];
};

export type FreightQuote = {
  table: string;
  table_name: string;
  value: string | null;
  lead_days: number | null;
  detail: string;
  error: string;
};

/** Metacampos do sistema na venda: entrega lançada ou retirada escolhida. */
export type DeliveryInfo = { table: string; table_name: string; lead_days: number | null; address_label: string };
export const deliveryOf = (sale: Sale | null) => {
  const meta = (sale?.metafields ?? {}) as Record<string, unknown>;
  const delivery = sale?.shipping_address ? (meta._entrega as DeliveryInfo | undefined) ?? null : null;
  return { delivery, pickup: !delivery && Boolean(meta._retirada) };
};

/** Nota do pedido como o `SaleSerializer` resume (a principal primeiro). */
export type InvoiceSummary = {
  id: string; document_model: "65" | "55"; model_label: string; number: number | null; series: number | null; status: string;
  status_label: string; access_key: string; protocol: string; authorized_at: string | null; total: string; environment: string;
  label: string;
};
