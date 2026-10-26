/** Estoque e financeiro: ações e relatórios que não são CRUD simples. */
import { cleanParams, http, type ListParams } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

// ── Estoque ──────────────────────────────────────────────────────────────────
export type PickingLine = {
  bin: string; variant: string; description: string; sku: string; lot: string; expires_at: string | null; quantity: string;
};
export type Picking = {
  document: number; warehouse: string; lines: PickingLine[];
  shortages: { variant: string; description: string; missing_quantity: string }[];
  load: { box_count: number; gross_weight: string; cubic_meters: string;
          boxes: { description: string; label: string; contents: string; barcode: string; quantity: number }[] };
};
export type ConferenceRow = {
  variant: string; description: string; sku: string; expected_quantity: string; counted_quantity: string;
  difference_quantity: string; loose_volumes: string[]; missing_volumes: string[]; unexpected: boolean;
};
export type Conference = { document: number; ok: boolean; rows: ConferenceRow[]; unknown_codes: string[] };
/** Conferência manual: item correto, ou a diferença (motivo, quantos chegaram, quantos entram). */
export type ManualLine = { item: string; ok: true }
  | { item: string; ok: false; arrived: string; accepted: string; reason: string; notes: string };
export type StockAlert = { id: string; product: string; product_name: string; name: string; sku: string; min_stock: string; stock: string };

export const stockApi = {
  post: (id: string) => data(http.post(`/stock/documents/${id}/post/`, {})),
  cancel: (id: string, reason = "") => data(http.post(`/stock/documents/${id}/cancel/`, { reason })),
  picking: (id: string) => data(http.get<Picking>(`/stock/documents/${id}/picking-list/`)),
  conference: (id: string, codes: string[]) => data(http.post<Conference>(`/stock/documents/${id}/conference/`, { codes })),
  /** Conclui a conferência: `codes` (leituras) grava o contado; `lines` é a manual (se a Logística permitir). */
  check: (id: string, body: { codes?: string[]; lines?: ManualLine[] } = {}) =>
    data(http.post(`/stock/documents/${id}/check/`, body)),
  alerts: () => data(http.get<StockAlert[]>("/stock/balances/alerts/")),
  /** URL da página de impressão de etiquetas (abre em nova aba; o cookie autentica). */
  labelsUrl: (id: string, template: string) => `/api/v1/stock/documents/${id}/labels/?template=${template}`,
};

// ── Financeiro ───────────────────────────────────────────────────────────────
export type Balances = { accounts: { id: string; name: string; kind: string; balance: string }[]; total: string };
export type Aging = Record<"receivable" | "payable", Record<"overdue" | "next_7_days" | "next_30_days" | "later", string>>;
export type CashFlow = {
  period: { from: string; to: string };
  opening_balance: string; inflow: string; outflow: string; closing_balance: string;
  by_day: { date: string; inflow: string; outflow: string }[];
  by_category: { category__name: string; kind: string; total: string }[];
  forecast: Partial<Record<"receivable" | "payable", string>>;
};
export type Dre = {
  period: { from: string; to: string };
  gross_revenue: string; freight: string; discounts: string; returns: string; net_revenue: string; cmv: string;
  gross_profit: string; gross_margin_percent: string; card_fees: string; commissions: string; cash_differences: string;
  expenses: { category: string; amount: string }[]; expenses_total: string;
  operating_result: string; operating_margin_percent: string;
};
export type CashReport = {
  session: { register: string; terminal: string; status: string; opened_at: string; closed_at: string | null;
             opened_by: string; closed_by: string; approved_by: string };
  sales: { count: number; total: string; average_ticket: string; discounts: string; cancelled_count: number;
           cancelled_total: string; cost: string; gross_margin: string };
  by_payment_method: { method__name: string; method__kind: string; count: number; total: string; change: string | null }[];
  drawer: Record<string, string | number | null>;
};
export type CashStatement = CashReport & {
  movements: { id: string; created_at: string; kind: string; kind_label: string; amount: string; status: string;
               status_label: string; reason: string; destination: string; operator: string }[];
  sales_list: { id: string; number: number; status: string; status_label: string; created_at: string; completed_at: string | null;
                customer: string; seller: string; subtotal: string; discount: string; total: string; payments: string;
                cancel_reason: string }[];
  items: { variant: string; description: string; sku: string; unit: string; quantity: string; total: string; cost: string;
           margin: string; sales: number }[];
  occurrences: { kind: string; tone: "warning" | "danger"; text: string }[];
};
export type AccountStatement = {
  account: string; opening_balance: string; closing_balance: string;
  lines: { date: string; description: string; kind: "in" | "out"; amount: string; category: string; balance: string }[];
};
export type SettleInput = {
  financial_account: string; amount: string; interest?: string; fine?: string; discount?: string; date?: string;
};

const report = <T>(name: string, params: ListParams = {}) =>
  data(http.get<T>(`/reports/${name}/`, { params: cleanParams(params) }));

export const financeApi = {
  balances: () => report<Balances>("balances"),
  aging: () => report<Aging>("aging"),
  cashFlow: (params: ListParams) => report<CashFlow>("cash-flow", params),
  dre: (params: ListParams) => report<Dre>("dre", params),
  settle: (installment: string, body: SettleInput) => data(http.post(`/finance/installments/${installment}/settle/`, body)),
  transfer: (body: { source: string; target: string; amount: string; description?: string }) =>
    data(http.post<Balances>("/finance/accounts/transfer/", body)),
  reverse: (id: string, reason = "") => data(http.post(`/finance/transactions/${id}/reverse/`, { reason })),
  cashReport: (session: string) => data(http.get<CashReport>(`/cash/sessions/${session}/report/`)),
  cashStatement: (session: string) => data(http.get<CashStatement>(`/cash/sessions/${session}/statement/`)),
  accountStatement: (account: string, params: ListParams) =>
    data(http.get<AccountStatement>(`/finance/accounts/${account}/statement/`, { params: cleanParams(params) })),
};
