/**
 * Motor da venda LOCAL (local-first): o caixa monta a venda inteira neste PC, no mesmo formato
 * de `Sale` que a API devolve (a tela desenha igual), e manda PRONTA ao servidor no fim
 * (`POST /pdv/offline-sales/`) — na hora, com o servidor no ar, ou pela fila quando ele voltar.
 *
 * O que é decidido aqui e o que pergunta ao servidor:
 * - itens, quantidade, preço da vitrine guardada, serviços, cliente, vendedor, desconto, retirada
 *   e pagamentos: tudo aqui, online ou offline;
 * - desconto/preço/cancelamento acima do limite: o gerente autoriza pelo `authorize` do processo
 *   principal (online confere no servidor; offline pela senha que o PC já aprendeu);
 * - cupom e frete: só com o servidor (a prévia `?dry_run=1` calcula e a venda local adota);
 * - crediário e vale-troca: só com o servidor (limite/saldo do cliente são conferidos na
 *   validação antes de cobrar).
 * A venda tem um id fixo: reenviar nunca duplica. "OFF-n" é o número provisório deste PC (a
 * venda feita com o servidor no ar já sai com o número real dele).
 */
import type { PaymentInput } from "@/api/pdv";
import type { PaymentMethod, PdvProductView, Sale, SaleItem } from "@/api/types";

import type { Snapshot } from "../../../shared/ipc";

export const OFFLINE_PREFIX = "off:";
export const isLocal = (sale: { id: string } | null | undefined) => Boolean(sale?.id.startsWith(OFFLINE_PREFIX));

const cents = (v: number) => Math.round(v * 100) / 100;
const str = (v: number) => cents(v).toFixed(2);
const qty = (v: number) => v.toFixed(3);
export const SERVER_METHODS = new Set(["installment_plan", "store_credit"]);

/** Recusa do PDV local, com o MESMO código de erro que o backend daria (`pdv/rules.ts`). */
export class OfflineRefused extends Error {
  constructor(message: string, public code = "offline_refused") {
    super(message);
  }
}

type Meta = Record<string, unknown> & {
  offline?: boolean; _retirada?: boolean; _entrega?: Record<string, unknown>; replaces?: string; replaces_number?: number;
  _discount_approved_by?: number | null; _delivery?: { address: string; table: string } | null; _approved?: Record<string, number>;
  presale?: string; presale_number?: number;
};
export const metaOf = (sale: Sale) => (sale.metafields ?? {}) as Meta;

export function newLocalSale(number: number, seller: { id: number; name: string } | null, offline: boolean): Sale {
  const now = new Date().toISOString();
  return {
    id: `${OFFLINE_PREFIX}${crypto.randomUUID()}`, number, items: [], payments: [], balance_due: "0.00",
    seller_name: seller?.name ?? "", addresses: {}, status: "open", overall_status: "open", payment_status: "pending",
    fulfillment_status: "pending", parked_at: null, created_at: now, completed_at: null, customer_document: "",
    customer_name: "", subtotal: "0.00", discount: "0.00", coupon_code: "", coupon_discount: "0.00", freight: "0.00",
    total: "0.00", paid_amount: "0.00", change_amount: "0.00", notes: "",
    metafields: { offline, _retirada: true },
    seller: seller?.id ?? null, customer: null, shipping_address: null, cancel_reason: "",
  };
}

export function recalc(sale: Sale): Sale {
  const items = sale.items.map((i) => {
    if (i.status !== "active") return i;
    const total = Math.max(cents(Number(i.quantity) * Number(i.unit_price)) - Number(i.discount ?? 0), 0);
    return { ...i, total: str(total) };
  });
  const subtotal = cents(items.filter((i) => i.status === "active").reduce((s, i) => s + Number(i.total), 0));
  const discount = Math.min(Number(sale.discount), subtotal);
  const total = Math.max(cents(subtotal - discount - Number(sale.coupon_discount ?? 0) + Number(sale.freight ?? 0)), 0);
  const paid = cents(sale.payments.filter((p) => p.status !== "cancelled").reduce((s, p) => s + Number(p.amount), 0));
  return {
    ...sale, items, subtotal: str(subtotal), discount: str(discount), total: str(total), paid_amount: str(paid),
    balance_due: str(Math.max(total - paid, 0)),
  };
}

/** Uma variante do catálogo guardado (o mesmo formato da vitrine online). */
export type SnapVariant = PdvProductView["variants"][number] & { barcodes?: string[]; scale_code?: string; promotion?: string | null };
export type SnapProduct = Omit<PdvProductView, "variants"> & { variants: SnapVariant[]; category?: string | null };

export function findVariant(snapshot: Snapshot | null, id: string) {
  for (const product of (snapshot?.products ?? []) as unknown as SnapProduct[]) {
    const variant = product.variants.find((v) => v.id === id);
    if (variant) return { product, variant };
  }
  return null;
}

/** Leitor: código de barras, SKU ou referência — exatos. */
export function lookupCode(snapshot: Snapshot | null, code: string) {
  const wanted = code.trim();
  for (const product of (snapshot?.products ?? []) as unknown as SnapProduct[]) {
    for (const variant of product.variants) {
      if (variant.barcode === wanted || variant.barcodes?.includes(wanted) || variant.sku.toLowerCase() === wanted.toLowerCase()) {
        return { product, variant };
      }
    }
  }
  return null;
}

type Service = PdvProductView["services"][number];

export function addLocalItem(sale: Sale, product: SnapProduct, variant: SnapVariant, quantity: number, services: Service[] = []): Sale {
  if (!(quantity > 0)) throw new OfflineRefused("Quantidade precisa ser maior que zero.");
  // Com serviço (montagem, garantia) o item entra separado: cada um com os serviços dele.
  const existing = services.length ? undefined
    : sale.items.find((i) => i.status === "active" && i.variant === variant.id && !i.parent_item
      && !sale.items.some((s) => s.parent_item === i.id && s.status === "active"));
  if (existing) {
    return recalc({ ...sale, items: sale.items.map((i) => (i === existing ? { ...i, quantity: qty(Number(i.quantity) + quantity) } : i)) });
  }
  const parent: SaleItem = {
    id: crypto.randomUUID(), description: product.variants.length > 1 && variant.name !== product.name ? `${product.name} ${variant.name}` : product.name,
    sku: variant.sku, unit: product.unit, quantity: qty(quantity), list_price: variant.price, unit_price: variant.current_price,
    discount: "0.00", total: "0.00", status: "active", variant: variant.id,
    promotion: variant.current_price !== variant.price ? variant.promotion ?? "shelf" : null, parent_item: null,
  };
  const children: SaleItem[] = services.map((s) => ({
    id: crypto.randomUUID(), description: s.name, sku: s.sku, unit: "UN", quantity: qty(quantity), list_price: s.price,
    unit_price: s.price, discount: "0.00", total: "0.00", status: "active", variant: s.variant, promotion: null, parent_item: parent.id,
  }));
  return recalc({ ...sale, items: [...sale.items, parent, ...children] });
}

export function setLocalQuantity(sale: Sale, itemId: string, quantity: number): Sale {
  if (!(quantity > 0)) throw new OfflineRefused("Quantidade precisa ser maior que zero.");
  // 2 guarda-roupas = 2 montagens: o serviço acompanha o item.
  return recalc({ ...sale, items: sale.items.map((i) => (i.id === itemId || i.parent_item === itemId ? { ...i, quantity: qty(quantity) } : i)) });
}

export function removeLocalItem(sale: Sale, itemId: string): Sale {
  return recalc({ ...sale, items: sale.items.map((i) => (i.id === itemId || i.parent_item === itemId ? { ...i, status: "cancelled" } : i)) });
}

/** Desconto no total da venda (valor ou %), já autorizado por quem pode. */
export function setLocalDiscount(sale: Sale, amount: number, approvedBy: number | null): Sale {
  const subtotal = Number(sale.subtotal);
  if (amount < 0 || amount > subtotal) throw new OfflineRefused("Desconto maior que o subtotal da venda.");
  return recalc({ ...sale, discount: str(amount), metafields: { ...metaOf(sale), _discount_approved_by: amount ? approvedBy : null } });
}

export const discountAmount = (sale: Sale, body: { amount?: string; percent?: string }) =>
  body.percent !== undefined ? cents(Number(sale.subtotal) * Number(body.percent.replace(",", ".")) / 100)
    : cents(Number((body.amount ?? "0").replace(",", ".")));

export function setLocalCustomer(sale: Sale, snapshot: Snapshot | null, body: { customer?: string | null; customer_document?: string; seller?: number | null },
  sellers: { user_id: number; name: string }[], known?: { id: string; name: string; document: string; credit_balance?: string } | null): Sale {
  let next = { ...sale };
  if (body.seller !== undefined) {
    const seller = sellers.find((s) => s.user_id === body.seller);
    next = { ...next, seller: seller?.user_id ?? null, seller_name: seller?.name ?? "" };
  }
  if (body.customer !== undefined || body.customer_document !== undefined) {
    const customer = body.customer ? known ?? snapshot?.customers.find((c) => c.id === body.customer) : null;
    const changed = (customer?.id ?? null) !== next.customer;
    next = {
      ...next, customer: customer?.id ?? null, customer_name: customer?.name ?? "",
      customer_document: customer?.document ?? body.customer_document ?? "",
      customer_credit_balance: customer?.credit_balance ?? "0.00",
    };
    // Trocou o cliente: a entrega (endereço dele) e o cupom (pode ser só dele) saem.
    if (changed) next = clearLocalDelivery({ ...next, coupon_code: "", coupon_discount: "0.00", addresses: {} });
  }
  return recalc(next);
}

export function clearLocalDelivery(sale: Sale): Sale {
  const { _entrega: _drop, _delivery: _gone, ...rest } = metaOf(sale);
  return recalc({ ...sale, freight: "0.00", shipping_address: null, metafields: { ...rest, _retirada: true } });
}

/** A prévia do servidor (`?dry_run=1`): a venda local adota cupom, frete, entrega e endereços. */
export function adoptPreview(local: Sale, preview: Sale, delivery?: { address: string; table: string } | null): Sale {
  const meta = metaOf(local);
  const server = metaOf(preview);
  const keepDelivery = delivery === undefined ? meta._delivery ?? null : delivery;
  const { _entrega: _old, _retirada: _pick, ...rest } = meta;
  return recalc({
    ...local, coupon_code: preview.coupon_code ?? "", coupon_discount: preview.coupon_discount ?? "0.00",
    freight: preview.freight ?? "0.00", shipping_address: preview.shipping_address ?? null,
    customer_credit_balance: preview.customer_credit_balance ?? local.customer_credit_balance ?? "0.00",
    addresses: preview.addresses ?? local.addresses,
    metafields: {
      ...rest, _delivery: keepDelivery,
      ...(server._entrega ? { _entrega: server._entrega } : { _retirada: true }),
    },
  });
}

/** Fecha a venda local: confere os pagamentos e calcula o troco (só dinheiro). */
export function completeLocal(sale: Sale, payments: PaymentInput[], methods: PaymentMethod[], serverChecked: boolean): Sale {
  const total = Number(sale.total);
  if (!sale.items.some((i) => i.status === "active")) throw new OfflineRefused("A venda não tem itens.");
  let due = total;
  let change = 0;
  const rows = payments.map((p) => {
    const method = methods.find((m) => m.id === p.method);
    if (!method) throw new OfflineRefused("Forma de pagamento desconhecida.");
    if (SERVER_METHODS.has(method.kind) && !serverChecked) {
      throw new OfflineRefused(`${method.name} precisa do servidor (limite/saldo do cliente). Use outra forma.`);
    }
    let amount = cents(Number(p.amount));
    let tendered = amount;
    let rowChange = 0;
    if (method.kind === "cash") {
      tendered = cents(Number(p.tendered ?? p.amount));
      amount = Math.min(tendered, cents(due));
      rowChange = cents(tendered - amount);
    } else if (amount > cents(due) + 0.001) {
      throw new OfflineRefused("Pagamento maior que o saldo da venda (troco só em dinheiro).");
    }
    due = cents(due - amount);
    change = cents(change + rowChange);
    return {
      id: crypto.randomUUID(), method: method.id, method_name: method.name, method_kind: method.kind, amount: str(amount),
      tendered_amount: str(tendered), change_amount: str(rowChange), installments: p.installments ?? 1, status: "approved",
      nsu: p.nsu ?? "",
    };
  });
  if (due > 0.001) throw new OfflineRefused(`Falta receber R$ ${due.toFixed(2).replace(".", ",")}.`);
  const now = new Date().toISOString();
  return {
    ...recalc({ ...sale, payments: rows }), change_amount: str(change), status: "completed", overall_status: "completed",
    payment_status: "paid", completed_at: now,
  };
}

/** O corpo de `POST /pdv/offline-sales/` (a venda pronta). */
export function salePayload(sale: Sale, installationId: string, cashSession: string | null, extra: Record<string, unknown> = {}) {
  const meta = metaOf(sale);
  const addresses = sale.addresses as { delivery?: unknown } | undefined;
  return {
    offline_id: sale.id.slice(OFFLINE_PREFIX.length), installation_id: installationId, local_number: sale.number,
    created_at: sale.created_at, completed_at: sale.completed_at, cash_session: cashSession,
    customer: sale.customer, customer_document: sale.customer_document, customer_name: sale.customer_name,
    seller: sale.seller, discount: sale.discount, discount_approved_by: meta._discount_approved_by ?? null,
    coupon_code: sale.coupon_code || null, delivery: meta._delivery ?? null,
    addresses: addresses?.delivery ? sale.addresses : null, notes: sale.notes || "",
    replaces: meta.replaces ?? null, presale: meta.presale ?? null, was_offline: Boolean(meta.offline), total: sale.total,
    items: sale.items.filter((i) => i.status === "active").map((i) => ({
      id: i.id, variant: i.variant, description: i.description, quantity: i.quantity, unit_price: i.unit_price,
      discount: i.discount ?? "0", parent: i.parent_item, promotion: i.promotion ?? null,
      approved_by: meta._approved?.[i.id] ?? null,
    })),
    payments: sale.payments.map((p) => ({
      method: (p as { method?: string }).method, amount: p.amount, tendered: p.tendered_amount, installments: p.installments, nsu: p.nsu,
    })),
    ...extra,
  };
}

/** Uma venda/pedido do servidor ainda sem pagamento vira local (retomado no caixa). */
export function fromServerSale(server: Sale, number: number, offline: boolean): Sale {
  if (server.payments.some((p) => !p.status || p.status === "approved")) {
    throw new OfflineRefused("Esta venda já tem pagamento no servidor: conclua por lá (Pedidos) ou estorne o pagamento.");
  }
  const local = newLocalSale(number, server.seller ? { id: server.seller, name: server.seller_name } : null, offline);
  const idMap = new Map(server.items.map((i) => [i.id, crypto.randomUUID()]));
  const meta = (server.metafields ?? {}) as Meta;
  const entrega = meta._entrega as { table?: string } | undefined;
  return recalc({
    ...local, customer: server.customer, customer_name: server.customer_name, customer_document: server.customer_document,
    discount: server.discount ?? "0.00", coupon_code: server.coupon_code ?? "", coupon_discount: server.coupon_discount ?? "0.00",
    freight: server.freight ?? "0.00", shipping_address: server.shipping_address ?? null, addresses: server.addresses ?? {},
    notes: server.notes ?? "",
    items: server.items.filter((i) => i.status === "active")
      .map((i) => ({ ...i, id: idMap.get(i.id)!, parent_item: i.parent_item ? idMap.get(i.parent_item) ?? null : null })),
    metafields: {
      offline, replaces: server.id, replaces_number: server.number,
      ...(entrega && server.shipping_address
        ? { _entrega: entrega, _delivery: { address: server.shipping_address, table: String(entrega.table ?? "") } }
        : { _retirada: true }),
    },
  });
}

/** Número para a tela: o do servidor, o do pedido retomado ou o provisório deste PC (OFF-n). */
export function saleLabel(sale: Sale) {
  if (!isLocal(sale)) return String(sale.number);
  const meta = metaOf(sale);
  if (meta.replaces_number) return String(meta.replaces_number);
  return meta.presale_number ? `OFF-${sale.number} (pré-venda ${meta.presale_number})` : `OFF-${sale.number}`;
}

/** Catálogo guardado no formato do cartão da grade. */
export function searchSnapshot(snapshot: Snapshot | null, term: string, category: string | null, childIds: (id: string) => string[]) {
  const words = term.toLowerCase().split(/\s+/).filter(Boolean);
  const allowed = category ? new Set([category, ...childIds(category)]) : null;
  return ((snapshot?.products ?? []) as unknown as SnapProduct[]).filter((p) => {
    if (allowed && !allowed.has(p.category ?? "")) return false;
    if (!words.length) return true;
    const text = `${p.name} ${p.reference ?? ""} ${p.variants.map((v) => `${v.sku} ${v.barcode} ${(v.barcodes ?? []).join(" ")}`).join(" ")}`.toLowerCase();
    return words.every((w) => text.includes(w));
  });
}
