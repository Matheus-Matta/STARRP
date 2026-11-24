/** Estoque, produtos e documentos (entrada, saída, transferência, ajuste, inventário). */
import { api, ApiError, type Page } from "@/api/client";
import type {
  Balance, DocItem, DocKind, Movement, StockAlert, StockDocument, Variant, Warehouse,
} from "@/api/types";

export const DOC_KINDS: Record<DocKind, { label: string; short: string; icon: "arrow-down-circle" | "arrow-up-circle" |
  "shuffle" | "sliders" | "clipboard" | "corner-up-left" | "move"; description: string }> = {
  entry: { label: "Entrada / recebimento", short: "Entrada", icon: "arrow-down-circle",
           description: "Mercadoria que chegou (compra, bonificação, implantação)." },
  exit: { label: "Saída (consumo, perda)", short: "Saída", icon: "arrow-up-circle",
          description: "Consumo interno, perda/avaria ou vencimento." },
  transfer: { label: "Transferência", short: "Transferência", icon: "shuffle",
              description: "De um depósito para outro." },
  adjustment: { label: "Ajuste", short: "Ajuste", icon: "sliders",
                description: "Corrige o saldo com a diferença (+ ou −)." },
  inventory: { label: "Inventário (contagem)", short: "Inventário", icon: "clipboard",
               description: "Conte o que há na prateleira; o sistema acerta a diferença." },
  supplier_return: { label: "Devolução ao fornecedor", short: "Devolução", icon: "corner-up-left",
                     description: "Mercadoria devolvida ao fornecedor." },
  relocation: { label: "Movimentação entre endereços", short: "Endereços", icon: "move",
                description: "Troca de endereço dentro do depósito (WMS)." },
};

export const EXIT_REASONS = [
  { value: "consumption", label: "Consumo interno" },
  { value: "loss", label: "Perda / avaria" },
  { value: "expiration", label: "Vencimento" },
];

export const DOC_STATUS: Record<string, { label: string; tone: "warning" | "success" | "danger" }> = {
  draft: { label: "Rascunho", tone: "warning" },
  posted: { label: "Confirmado", tone: "success" },
  cancelled: { label: "Cancelado", tone: "danger" },
};

/** Código de barras, SKU, etiqueta de balança ou de volume → variante (null se não achar). */
export async function lookupCode(code: string): Promise<Variant | null> {
  try {
    return await api.get<Variant>("/catalog/variants/lookup/", { code: code.trim() });
  } catch (error) {
    if (error instanceof ApiError && (error.code === "product_not_found" || error.status === 404)) return null;
    throw error;
  }
}

export function searchVariants(search: string, page = 1) {
  return api.get<Page<Variant>>("/catalog/variants/", {
    search, page, page_size: 30, is_active: true, product__is_active: true, with_stock: 1,
  });
}

export function getVariant(id: string) {
  return api.get<Variant>(`/catalog/variants/${id}/`);
}

export async function listWarehouses() {
  const page = await api.get<Page<Warehouse>>("/stock/warehouses/", { is_active: true, page_size: 200 });
  return page.results;
}

export function listBalances(params: { search?: string; variant?: string; warehouse?: string; page?: number }) {
  return api.get<Page<Balance>>("/stock/balances/", { ...params, page_size: 40, ordering: "variant_name" });
}

export function stockAlerts() {
  return api.get<StockAlert[]>("/stock/balances/alerts/");
}

export function listMovements(params: { variant?: string; warehouse?: string; kind?: string; page?: number }) {
  return api.get<Page<Movement>>("/stock/movements/", { ...params, page_size: 30, ordering: "-created_at" });
}

export function listDocuments(params: { status?: string; kind?: string; search?: string; page?: number }) {
  return api.get<Page<StockDocument>>("/stock/documents/", { ...params, page_size: 30, ordering: "-created_at" });
}

export function getDocument(id: string) {
  return api.get<StockDocument>(`/stock/documents/${id}/`);
}

export type DocumentDraft = {
  kind: DocKind;
  warehouse: string;
  destination?: string | null;
  exit_reason?: string;
  reason?: string;
  external_number?: string;
  effective_date: string;
  items: Pick<DocItem, "variant" | "quantity" | "unit_cost" | "lot_number" | "expires_at" | "notes">[];
};

export function createDocument(draft: DocumentDraft) {
  return api.post<StockDocument>("/stock/documents/", draft);
}

export function updateDocument(id: string, draft: Partial<DocumentDraft>) {
  return api.patch<StockDocument>(`/stock/documents/${id}/`, draft);
}

export function postDocument(id: string) {
  return api.post<StockDocument>(`/stock/documents/${id}/post/`);
}

export function cancelDocument(id: string, reason: string) {
  return api.post<StockDocument>(`/stock/documents/${id}/cancel/`, { reason });
}

export function deleteDocument(id: string) {
  return api.delete<void>(`/stock/documents/${id}/`);
}
