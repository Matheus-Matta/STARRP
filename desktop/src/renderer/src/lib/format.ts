/**
 * Formatação pt-BR. Dinheiro chega da API como TEXTO ("45.90") e assim volta: nunca passa
 * por float na ida e volta.
 */
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });
const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));

export function money(value: unknown) {
  const n = num(value);
  return n === null || Number.isNaN(n) ? "—" : brl.format(n);
}

export function quantity(value: unknown) {
  const n = num(value);
  return n === null || Number.isNaN(n) ? "—" : qty.format(n);
}

export function dateTime(value: unknown) {
  return value ? dateTimeFmt.format(new Date(String(value))) : "—";
}

export const hour = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

/** "12.5" / "12,5" → número; vazio/ inválido → null. */
export function parseDecimal(value: string): number | null {
  const clean = value.trim().replace(/\./g, "").replace(",", ".");
  if (!clean) return null;
  const n = Number(clean);
  return Number.isNaN(n) ? null : n;
}

export const cep = (value: string | null | undefined) => {
  const d = (value ?? "").replace(/\D/g, "");
  return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
};

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

export const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

/** Status do pedido (os mesmos rótulos da retaguarda). */
export const OVERALL_STATUS: Record<string, string> = {
  draft: "Pedido guardado", open: "Em atendimento", awaiting_payment: "Pagamento em andamento",
  awaiting_picking: "Aguardando separação", ready: "Pronto para entrega", in_transit: "Em rota de entrega",
  completed: "Concluído", returned: "Devolvido", cancelled: "Cancelado",
};
export const OVERALL_TONE: Record<string, string> = {
  draft: "info", open: "warning", awaiting_payment: "warning", awaiting_picking: "brand", ready: "brand",
  in_transit: "info", completed: "success", returned: "neutral", cancelled: "danger",
};
export const PAYMENT_STATUS: Record<string, string> = {
  pending: "A pagar", partial: "Pago em parte", paid: "Pago", partially_refunded: "Estorno parcial",
  refunded: "Estornado", cancelled: "Cancelado",
};
export const PAYMENT_TONE: Record<string, string> = {
  pending: "warning", partial: "warning", paid: "success", partially_refunded: "info",
  refunded: "neutral", cancelled: "danger",
};
export const FULFILLMENT_STATUS: Record<string, string> = {
  pending: "Pendente", ready: "Separado", shipped: "Saiu para entrega", delivered: "Entregue",
  picked_up: "Retirado na loja", returned: "Devolvido", cancelled: "Cancelado",
};
export const FULFILLMENT_TONE: Record<string, string> = {
  pending: "warning", ready: "brand", shipped: "info", delivered: "success",
  picked_up: "success", returned: "neutral", cancelled: "danger",
};
export const FULFILLMENT_FLOW = ["pending", "ready", "shipped", "delivered"];
