/** Ações da venda no PDV. Cada função é uma rota de ação do backend. */
import type { Approval, PdvBootstrap, PdvProductView, Sale, VariantLookup } from "./types";
import { http, idempotencyKey } from "./http";

const base = (id: string) => `/sales/${id}`;
const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export type PaymentInput = {
  method: string;
  amount: string;
  tendered?: string;
  installments?: number;
  nsu?: string;
  authorization_code?: string;
  card_brand?: string;
};

export const salesApi = {
  bootstrap: (installation_id: string, name: string) =>
    data(http.post<PdvBootstrap>("/pdv/bootstrap/", { installation_id, name, device_type: "web" })),
  create: (body: { seller?: number | null; customer?: string | null } = {}) => data(http.post<Sale>("/sales/", body)),
  get: (id: string) => data(http.get<Sale>(`${base(id)}/`)),
  /** `services`: serviços (montagem, garantia) lançados junto, presos ao item; `service_for`: o item do serviço. */
  addItem: (id: string, body: { code?: string; variant?: string; quantity?: string; approval?: Approval;
                                services?: string[]; service_for?: string }) =>
    data(http.post<Sale>(`${base(id)}/items/`, body)),
  updateItem: (id: string, itemId: string, body: { quantity?: string; discount?: string; approval?: Approval }) =>
    data(http.patch<Sale>(`${base(id)}/items/${itemId}/`, body)),
  cancelItem: (id: string, itemId: string, body: { reason?: string; approval?: Approval }) =>
    data(http.delete<Sale>(`${base(id)}/items/${itemId}/`, { data: body })),
  setCustomer: (id: string, body: { customer?: string | null; customer_document?: string; seller?: number | null }) =>
    data(http.post<Sale>(`${base(id)}/customer/`, body)),
  discount: (id: string, body: { amount?: string; percent?: string; approval?: Approval }) =>
    data(http.post<Sale>(`${base(id)}/discount/`, body)),
  applyCoupon: (id: string, code: string) => data(http.post<Sale>(`${base(id)}/coupon/`, { code })),
  removeCoupon: (id: string) => data(http.delete<Sale>(`${base(id)}/coupon/`)),
  /** Paga e conclui numa transação; a chave impede cobrar duas vezes num reenvio. */
  checkout: (id: string, payments: PaymentInput[], key: string = idempotencyKey()) =>
    data(http.post<Sale>(`${base(id)}/checkout/`, { payments }, { headers: { "Idempotency-Key": key } })),
  cancel: (id: string, body: { reason: string; approval?: Approval }) =>
    data(http.post<Sale>(`${base(id)}/cancel/`, body)),
  /** Guarda o pedido (ou envia ao caixa); volta para a lista "Pedidos" até alguém retomar. */
  park: (id: string, note = "") => data(http.post<Sale>(`${base(id)}/park/`, { note })),
  resume: (id: string) => data(http.post<Sale>(`${base(id)}/resume/`, {})),
  /** Venda aberta minha (a que ficou pela metade se a aba fechou). */
  myOpen: (userId: number) =>
    data(http.get<{ results: Sale[] }>("/sales/", { params: { status: "open", created_by: userId, ordering: "-created_at", page_size: 1 } })),
  /** Desbloqueia a tela: a senha do operador ou a de ações do caixa. */
  unlock: (password: string) => data(http.post<{ ok: boolean }>("/pdv/unlock/", { password })),
  /** Entrega no endereço do cliente pela tabela de frete (o frete entra no total); `clearDelivery` = retirada. */
  delivery: (id: string, address: string, table: string) => data(http.post<Sale>(`${base(id)}/delivery/`, { address, table })),
  clearDelivery: (id: string) => data(http.delete<Sale>(`${base(id)}/delivery/`)),
  /** Vitrine do produto: fotos, grade, variantes com preço/saldo e serviços oferecidos. */
  productView: (id: string) => data(http.get<PdvProductView>(`/pdv/products/${id}/`)),
  lookup: (code: string) => data(http.get<VariantLookup>("/catalog/variants/lookup/", { params: { code } })),
};
