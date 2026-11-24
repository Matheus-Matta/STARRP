/** Rotas que o PDV usa: autenticação, venda, caixa, catálogo, clientes e frete. */
import { http, idempotencyKey, type Page } from "./client";
import type {
  Approval, CashMovement, CashSession, Customer, FreightQuote, Me, PdvBootstrap, PdvProductView, Sale, SaleRow,
  VariantLookup,
} from "./types";

export type PaymentInput = {
  method: string;
  amount: string;
  tendered?: string;
  installments?: number;
  nsu?: string;
};

export type OrderAddress = {
  zip_code: string; street: string; number: string; complement: string; district: string; city: string; state: string;
  city_ibge: string; reference: string; recipient: string; text?: string; from_customer?: boolean;
};
export type OrderAddresses = { delivery: OrderAddress | null; billing: OrderAddress | null; billing_same_as_delivery: boolean };
export const blankAddress = (): OrderAddress => ({ zip_code: "", street: "", number: "", complement: "", district: "",
  city: "", state: "", city_ibge: "", reference: "", recipient: "" });

export const authApi = {
  /** `storeId`: força a loja no header (a do PDV); sem ela o backend escolhe a padrão do usuário. */
  me: (storeId?: string | null) => http.get<Me>("/me/", undefined, storeId ? { "X-Store-ID": storeId } : undefined),
};

const base = (id: string) => `/sales/${id}`;

export const salesApi = {
  bootstrap: (installation_id: string, name: string, app_version: string) =>
    http.post<PdvBootstrap>("/pdv/bootstrap/", { installation_id, name, device_type: "desktop", app_version }),
  create: (body: { seller?: number | null; customer?: string | null } = {}) => http.post<Sale>("/sales/", body),
  get: (id: string) => http.get<Sale>(`${base(id)}/`),
  list: (params: Record<string, string | number | undefined>) => http.get<Page<SaleRow>>("/sales/", params),
  addItem: (id: string, body: { code?: string; variant?: string; quantity?: string; approval?: Approval; services?: string[] }) =>
    http.post<Sale>(`${base(id)}/items/`, body),
  updateItem: (id: string, itemId: string, body: { quantity?: string; approval?: Approval }) =>
    http.patch<Sale>(`${base(id)}/items/${itemId}/`, body),
  cancelItem: (id: string, itemId: string, body: { reason?: string; approval?: Approval }) =>
    http.delete<Sale>(`${base(id)}/items/${itemId}/`, body),
  setCustomer: (id: string, body: { customer?: string | null; customer_document?: string; seller?: number | null }) =>
    http.post<Sale>(`${base(id)}/customer/`, body),
  discount: (id: string, body: { amount?: string; percent?: string; approval?: Approval }) =>
    http.post<Sale>(`${base(id)}/discount/`, body),
  applyCoupon: (id: string, code: string) => http.post<Sale>(`${base(id)}/coupon/`, { code }),
  removeCoupon: (id: string) => http.delete<Sale>(`${base(id)}/coupon/`),
  /** Paga e conclui numa transação; a chave impede cobrar duas vezes num reenvio. */
  checkout: (id: string, payments: PaymentInput[], key: string = idempotencyKey()) =>
    http.post<Sale>(`${base(id)}/checkout/`, { payments }, { "Idempotency-Key": key }),
  cancel: (id: string, body: { reason: string; approval?: Approval }) => http.post<Sale>(`${base(id)}/cancel/`, body),
  park: (id: string, note = "") => http.post<Sale>(`${base(id)}/park/`, { note }),
  resume: (id: string) => http.post<Sale>(`${base(id)}/resume/`, {}),
  myOpen: (userId: number) =>
    http.get<Page<Sale>>("/sales/", { status: "open", created_by: userId, ordering: "-created_at", page_size: 1 }),
  unlock: (password: string) => http.post<{ ok: boolean }>("/pdv/unlock/", { password }),
  delivery: (id: string, address: string, table: string) => http.post<Sale>(`${base(id)}/delivery/`, { address, table }),
  clearDelivery: (id: string) => http.delete<Sale>(`${base(id)}/delivery/`),
  addresses: (id: string) => http.get<OrderAddresses>(`${base(id)}/addresses/`),
  saveAddresses: (id: string, body: Partial<OrderAddresses>) => http.post<OrderAddresses>(`${base(id)}/addresses/`, body),
  fulfillment: (id: string, status: string, note = "") => http.post<Sale>(`${base(id)}/fulfillment/`, { status, note }),
  /** Correções da venda concluída (cada uma com a permissão própria; o motivo vai no histórico). */
  editDelivery: (id: string, body: { pickup?: boolean; address?: string; table?: string | null; reason: string }) =>
    http.post<Sale>(`${base(id)}/edit-delivery/`, body),
  changePayment: (id: string, payment: string, body: { method: string; installments: number; nsu: string; reason: string }) =>
    http.post<Sale>(`${base(id)}/payments/${payment}/change/`, body),
  cancelInvoice: (invoice: string, body: { reason: string; with_sale: boolean; approval?: Approval }) =>
    http.post(`/fiscal/invoices/${invoice}/cancel/`, body),
  danfe: (id: string, invoice: string) => http.get<Record<string, unknown>>(`${base(id)}/invoices/${invoice}/danfe/`),
  paymentMethods: () => http.get<Page<{ id: string; name: string; kind: string; max_installments: number }>>(
    "/payment-methods/", { is_active: true, page_size: 100, ordering: "position" }),
  /** A venda montada no PC, pronta: `dryRun` só valida/calcula (cupom, frete, crediário) sem gravar. */
  ready: (body: Record<string, unknown>, dryRun = false) =>
    http.post<Sale>(`/pdv/offline-sales/${dryRun ? "?dry_run=1" : ""}`, body),
  productView: (id: string) => http.get<PdvProductView>(`/pdv/products/${id}/`),
  lookup: (code: string) => http.get<VariantLookup>("/catalog/variants/lookup/", { code }),
};

export const cashApi = {
  /** Abertura com conferência cega: `opening_amount` = o que o operador CONTOU na gaveta. */
  open: (register: string, opening_amount: string, terminal?: string, notes = "") =>
    http.post<CashSession>("/cash/sessions/", { register, opening_amount, terminal, notes }),
  get: (id: string) => http.get<CashSession>(`/cash/sessions/${id}/`),
  history: (register: string) =>
    http.get<Page<CashSession>>("/cash/sessions/", { register, ordering: "-opened_at", page_size: 10 }),
  approveOpening: (id: string, approval?: Approval, reason = "") =>
    http.post<CashSession>(`/cash/sessions/${id}/approve-opening/`, { approval, reason }),
  close: (id: string, counted_amount: string, notes = "") =>
    http.post<CashSession>(`/cash/sessions/${id}/close/`, { counted_amount, notes }),
  movement: (id: string, kind: "withdrawal" | "supply", amount: string, reason = "", approval?: Approval) =>
    http.post<CashMovement>(`/cash/sessions/${id}/movements/`, { kind, amount, reason, approval }),
  movements: (id: string) => http.get<CashMovement[]>(`/cash/sessions/${id}/movements/`),
  approveMovement: (id: string, reason = "", approval?: Approval) =>
    http.post<CashMovement>(`/cash/movements/${id}/approve/`, { reason, approval }),
  rejectMovement: (id: string, reason = "") => http.post<CashMovement>(`/cash/movements/${id}/reject/`, { reason }),
  approveClosing: (id: string, reason: string, approval?: Approval) =>
    http.post<CashSession>(`/cash/sessions/${id}/approve/`, { reason, approval }),
};

export type ProductRow = Record<string, unknown> & { id: string; name: string };
export type CategoryRow = { id: string; name: string; parent: string | null };

export const catalogApi = {
  products: (params: Record<string, string | number | boolean | undefined | null>) =>
    http.get<Page<ProductRow>>("/catalog/products/", params),
  categories: () => http.get<Page<CategoryRow>>("/catalog/categories/", { is_active: true, page_size: 200, ordering: "name" }),
};

export const customersApi = {
  list: (search: string, page = 1, ordering = "name", pageSize = 20) =>
    http.get<Page<Customer>>("/customers/", { is_active: "true", ordering, search, page, page_size: pageSize }),
  get: (id: string) => http.get<Customer>(`/customers/${id}/`),
  create: (body: Record<string, unknown>) => http.post<Customer>("/customers/", body),
  update: (id: string, body: Record<string, unknown>) => http.patch<Customer>(`/customers/${id}/`, body),
};

export const logisticsApi = {
  quote: (zip: string) => http.get<FreightQuote[]>("/logistics/freight-tables/quote/", { zip }),
  estimate: (params: Record<string, string>) =>
    http.get<{ zip_code: string | null; address: Record<string, string> | null; point: [string, string] | null; quotes: FreightQuote[] }>(
      "/logistics/freight-tables/estimate/", params),
};
