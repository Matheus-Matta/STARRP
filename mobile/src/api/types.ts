/** Tipos das respostas da API usados no app (só os campos que as telas leem). */

export type Me = {
  id: number;
  username: string;
  name: string;
  email: string;
  is_superuser: boolean;
  is_account_admin: boolean;
  account: { id: string; name: string; modules: string[]; logo_url: string | null } | null;
  role: { code: string; name: string; rank: number } | null;
  roles: { code: string; name: string }[];
  all_stores: boolean;
  stores: { id: string; name: string }[];
  active_store_id: string | null;
  default_store_id: string | null;
  is_seller: boolean;
  permissions: string[];
};

export type Warehouse = {
  id: string;
  name: string;
  kind: string;
  is_default: boolean;
  is_active: boolean;
  uses_bins: boolean;
  store: string;
};

export type Variant = {
  id: string;
  product: string;
  product_name: string;
  display_name: string;
  name: string;
  sku: string;
  price: string;
  promotional_price: string | null;
  current_price?: string;
  unit: string;
  sold_by_weight: boolean;
  barcodes: { code: string; is_primary: boolean }[];
  image: string | null;
  category_name: string | null;
  is_active: boolean;
  stock_quantity?: string | null;
  scale_quantity?: string | null;
};

export type Balance = {
  id: string;
  variant: string;
  variant_name: string;
  sku: string;
  warehouse: string;
  warehouse_name: string;
  quantity: string;
  updated_at: string;
};

export type StockAlert = {
  id: string;
  product: string;
  product_name: string;
  name: string;
  sku: string;
  min_stock: string;
  stock: string;
};

export type Movement = {
  id: string;
  variant: string;
  variant_name: string;
  sku: string;
  warehouse_name: string;
  kind: string;
  kind_label: string;
  quantity: string;
  balance_after: string;
  operator_name: string;
  reason: string;
  created_at: string;
};

export type DocKind = "entry" | "exit" | "transfer" | "adjustment" | "inventory" | "supplier_return" | "relocation";
export type DocStatus = "draft" | "posted" | "cancelled";

export type DocItem = {
  id?: string;
  variant: string;
  variant_name?: string;
  sku?: string;
  quantity: string;
  expected_quantity?: string | null;
  unit_cost?: string;
  lot_number?: string;
  expires_at?: string | null;
  notes?: string;
};

export type StockDocument = {
  id: string;
  kind: DocKind;
  status: DocStatus;
  number: number;
  warehouse: string;
  warehouse_name: string;
  destination: string | null;
  destination_name: string | null;
  supplier: string | null;
  supplier_name: string | null;
  external_number: string;
  effective_date: string;
  exit_reason: string;
  reason: string;
  inbound_nfe: string | null;
  checked_at: string | null;
  posted_at: string | null;
  item_count: number;
  items: DocItem[];
  created_at: string;
};

export type SaleListItem = {
  id: string;
  number: number;
  channel: string;
  status: string;
  customer_name: string;
  seller_name: string;
  item_count: number;
  total: string;
  paid_amount: string;
  created_at: string;
  completed_at: string | null;
  overall_status: string;
  payment_status: string;
  fulfillment_status: string;
};

export type Sale = SaleListItem & {
  subtotal: string;
  discount: string;
  items: { id: string; description: string; sku: string; quantity: string; unit: string; unit_price: string;
           total: string; status: string }[];
  payments: { id: string; method_name?: string; method?: string; amount: string; installments: number; status: string }[];
};

export type CashSession = {
  id: string;
  register_name: string;
  opened_by_name: string;
  opened_at: string;
  closed_at: string | null;
  status: string;
  opening_amount?: string;
  expected_now: string;
  pending_movements: number;
};

export type Kpi = { label: string; value: string | number | null; format?: string; delta?: number | string | null;
                    good?: "up" | "down"; hint?: string };

export type ReportRow = { label: string; value: string | number | null; sub?: string; [key: string]: unknown };

export type ReportBlock = {
  type: "line" | "bars" | "ranking" | "share" | "heatmap" | "waterfall" | "table" | string;
  title: string;
  description?: string;
  format?: string;
  limit?: number;
  rows?: ReportRow[];
  columns?: { key: string; label: string; format?: string }[];
  x?: string[];
  series?: { name: string; values: (string | number | null)[] }[];
  [key: string]: unknown;
};

export type ReportBook = {
  title: string;
  subtitle?: string;
  period?: { from: string; to: string };
  kpis: Kpi[];
  blocks: ReportBlock[];
  filters?: { name: string; label: string; options: { label: string; value: string }[] }[];
};
