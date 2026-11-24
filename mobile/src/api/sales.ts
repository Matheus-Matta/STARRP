/**
 * Venda pelo celular ("PDV móvel", canal `mobile`): as MESMAS rotas de ação que o PDV usa
 * (`frontend/src/api/sales.ts` → backend `views/sales.py`): criar, itens, cliente, desconto, guardar
 * pedido (vai para o caixa), receber e concluir (`checkout`, com chave de idempotência), cancelar.
 */
import { api, type Page } from "@/api/client";

export type SaleItem = {
  id: string; variant: string | null; description: string; sku: string; unit: string; quantity: string;
  list_price: string; unit_price: string; discount: string; total: string; status: "active" | "cancelled";
  parent_item: string | null;
};
export type SalePayment = { id: string; method: string; method_name: string; method_kind: string; amount: string;
                            status: string; installments: number };
export type Sale = {
  id: string; number: number; channel: string; status: "open" | "draft" | "completed" | "cancelled";
  customer: string | null; customer_name: string; subtotal: string; discount: string; coupon_discount: string;
  freight: string; total: string; paid_amount: string; change_amount: string; balance_due: string;
  items: SaleItem[]; payments: SalePayment[];
};
export type PaymentMethod = { id: string; name: string; kind: string; requires_reference: boolean;
                              max_installments: number; is_active: boolean };
export type PaymentInput = { method: string; amount: string; tendered?: string; installments?: number; nsu?: string };

const base = (id: string) => `/sales/${id}`;
const newKey = () => `app-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export const salesApi = {
  create: (body: { customer?: string | null } = {}) => api.post<Sale>("/sales/", { channel: "mobile", ...body }),
  get: (id: string) => api.get<Sale>(`${base(id)}/`),
  /** A venda aberta que ficou pela metade neste usuário (continua de onde parou). */
  myOpen: (userId: number) =>
    api.get<Page<Sale>>("/sales/", { status: "open", created_by: userId, ordering: "-created_at", page_size: 1 }),
  parked: () => api.get<Page<Sale>>("/sales/", { status: "draft", ordering: "-parked_at", page_size: 30 }),
  addItem: (id: string, body: { code?: string; variant?: string; quantity?: string }) =>
    api.post<Sale>(`${base(id)}/items/`, body),
  updateItem: (id: string, itemId: string, body: { quantity?: string; discount?: string }) =>
    api.patch<Sale>(`${base(id)}/items/${itemId}/`, body),
  cancelItem: (id: string, itemId: string, reason: string) =>
    api.delete<Sale>(`${base(id)}/items/${itemId}/`, { reason }),
  setCustomer: (id: string, customer: string | null) => api.post<Sale>(`${base(id)}/customer/`, { customer }),
  discount: (id: string, amount: string) => api.post<Sale>(`${base(id)}/discount/`, { amount }),
  checkout: (id: string, payments: PaymentInput[], key = newKey()) =>
    api.post<Sale>(`${base(id)}/checkout/`, { payments }, { "Idempotency-Key": key }),
  park: (id: string, note = "") => api.post<Sale>(`${base(id)}/park/`, { note }),
  resume: (id: string) => api.post<Sale>(`${base(id)}/resume/`, {}),
  cancel: (id: string, reason: string) => api.post<Sale>(`${base(id)}/cancel/`, { reason }),
  methods: async () => {
    const data = await api.get<Page<PaymentMethod> | PaymentMethod[]>("/payment-methods/", { page_size: 100 });
    return (Array.isArray(data) ? data : data.results).filter((m) => m.is_active !== false);
  },
  /** Abre o turno de caixa do usuário (quando a filial exige caixa aberto para receber). */
  openCash: (register: string, opening_amount: string) =>
    api.post<{ id: string; status: string }>("/cash/sessions/", { register, opening_amount }),
};
