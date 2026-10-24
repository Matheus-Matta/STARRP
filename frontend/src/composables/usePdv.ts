/**
 * Estado e ações do PDV web. A tela só desenha; tudo que mexe na venda passa aqui.
 *
 * - a venda nasce no primeiro item lido (não deixa venda vazia no servidor);
 * - a venda aberta é lembrada na aba: recarregar a página retoma a mesma venda;
 * - desconto, cancelamento e preço acima do limite pedem gerente (`withApproval`);
 * - o checkout leva uma chave de idempotência FIXA por tentativa: se a rede cair
 *   e o operador clicar de novo, o backend devolve a mesma venda, sem cobrar 2x;
 * - fechou a aba no meio? Ao voltar, a venda aberta do operador é retomada sozinha;
 * - pedido pela metade pode ser GUARDADO (vendedor envia ao caixa) e retomado depois;
 * - modo "seller" (vendedor): monta e guarda pedidos, não cobra nem mexe no caixa;
 *   modo "cashier": cobra, abre/fecha o turno e a tela BLOQUEIA sem uso (senha para voltar).
 */
import { computed, ref } from "vue";

import { cashApi } from "@/api/cash";
import { idempotencyKey } from "@/api/http";
import { salesApi, type PaymentInput } from "@/api/sales";
import type { CashSession, PdvBootstrap, Sale, SaleItem } from "@/api/types";

import { withApproval } from "./useApproval";

const SALE_KEY = "starrp.pdv.sale";
const LOCK_KEY = "starrp.pdv.locked";
const TERMINAL_KEY = "starrp.pdv.terminal";

function terminalId() {
  let id = localStorage.getItem(TERMINAL_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(TERMINAL_KEY, id);
  }
  return id;
}

export function usePdv() {
  const boot = ref<PdvBootstrap | null>(null);
  const session = ref<CashSession | null>(null);
  const sale = ref<Sale | null>(null);
  const busy = ref(false);
  /** Tela bloqueada (sobrevive ao recarregar: recarregar não "desbloqueia"). */
  const locked = ref(sessionStorage.getItem(LOCK_KEY) === "1");
  let checkoutKey: string | null = null;

  const items = computed(() => (sale.value?.items ?? []).filter((i: SaleItem) => i.status === "active"));
  const mode = computed(() => boot.value?.mode ?? "cashier");
  const isSeller = computed(() => mode.value === "seller");
  /** Só o caixa precisa de turno aberto; o vendedor monta pedidos sem caixa. */
  const needsCash = computed(() => !isSeller.value && Boolean(boot.value?.store.require_open_cash_session) && !session.value);

  function remember(next: Sale | null) {
    sale.value = next;
    if (next && next.status === "open") sessionStorage.setItem(SALE_KEY, next.id);
    else sessionStorage.removeItem(SALE_KEY);
  }

  async function run<T>(action: () => Promise<T>) {
    busy.value = true;
    try {
      return await action();
    } finally {
      busy.value = false;
    }
  }

  async function init(userId?: number) {
    boot.value = await salesApi.bootstrap(terminalId(), "Navegador");
    session.value = boot.value.cash_session;
    const saved = sessionStorage.getItem(SALE_KEY);
    if (saved) remember(await salesApi.get(saved).catch(() => null));
    // Aba fechada no meio da venda: retoma a venda aberta deste operador (nada se perde).
    if (!sale.value && userId) {
      const open = (await salesApi.myOpen(userId).catch(() => ({ results: [] as Sale[] }))).results[0];
      if (open) remember(await salesApi.get(open.id));
    }
  }

  async function ensureSale() {
    if (!sale.value || sale.value.status !== "open") {
      // Vendedor: o pedido já nasce com ele como vendedor (a comissão é dele).
      const me = isSeller.value ? boot.value?.sellers.find((s) => s.user_id === currentUser) : undefined;
      remember(await salesApi.create(me ? { seller: me.user_id } : {}));
    }
    return sale.value!;
  }
  let currentUser: number | null = null;
  const setUser = (id: number | null) => (currentUser = id);

  /** Guarda o pedido (vendedor: "enviar ao caixa") e libera a tela para o próximo. */
  const park = (note = "") => run(async () => {
    if (!sale.value) return null;
    const parked = await salesApi.park(sale.value.id, note);
    remember(null);
    return parked;
  });

  /** Retoma um pedido guardado — vira a venda aberta desta tela. Se já havia uma pela
   *  metade, ela é guardada antes (nada fica perdido). */
  const resume = (id: string) => run(async () => {
    if (sale.value && sale.value.id !== id && items.value.length) await salesApi.park(sale.value.id);
    remember(await salesApi.resume(id));
    return sale.value!;
  });

  function lock() {
    locked.value = true;
    sessionStorage.setItem(LOCK_KEY, "1");
  }
  async function unlock(password: string) {
    await salesApi.unlock(password);
    locked.value = false;
    sessionStorage.removeItem(LOCK_KEY);
  }

  /** Leitor de código: aceita "3*789..." para lançar 3 unidades. */
  const scan = (raw: string) => run(async () => {
    const [qty, code] = raw.includes("*") ? raw.split("*", 2) : [undefined, raw];
    const current = await ensureSale();
    remember(await withApproval((approval) =>
      salesApi.addItem(current.id, { code: code!.trim(), quantity: qty?.replace(",", "."), approval })));
  });

  /** Clique no cartão do catálogo: lança a variante (quantidade em kg para produto de balança)
   *  e, junto, os serviços escolhidos na vitrine — tudo numa chamada (entra tudo ou nada). */
  const addVariant = (variant: string, quantity = "1", services: string[] = []) => run(async () => {
    const current = await ensureSale();
    remember(await withApproval((approval) => salesApi.addItem(current.id, {
      variant, quantity, approval, ...(services.length ? { services } : {}) })));
  });

  const setQuantity = (item: SaleItem, quantity: string) => run(async () => {
    remember(await withApproval((approval) => salesApi.updateItem(sale.value!.id, item.id, { quantity, approval })));
  });

  const removeItem = (item: SaleItem, reason: string) => run(async () => {
    remember(await withApproval((approval) => salesApi.cancelItem(sale.value!.id, item.id, { reason, approval })));
  });

  const setCustomer = (body: { customer?: string | null; customer_document?: string; seller?: number | null }) => run(async () => {
    remember(await salesApi.setCustomer((await ensureSale()).id, body));
  });

  const setDelivery = (address: string, table: string) => run(async () => {
    remember(await salesApi.delivery(sale.value!.id, address, table));
  });
  const clearDelivery = () => run(async () => {
    remember(await salesApi.clearDelivery(sale.value!.id));
  });

  const discount = (body: { amount?: string; percent?: string }) => run(async () => {
    remember(await withApproval((approval) => salesApi.discount(sale.value!.id, { ...body, approval })));
  });

  const coupon = (code: string | null) => run(async () => {
    remember(code ? await salesApi.applyCoupon(sale.value!.id, code) : await salesApi.removeCoupon(sale.value!.id));
  });

  const checkout = (payments: PaymentInput[]) => run(async () => {
    checkoutKey ??= idempotencyKey();
    const done = await salesApi.checkout(sale.value!.id, payments, checkoutKey);
    checkoutKey = null;
    remember(null);
    return done;
  });

  const cancel = (reason: string) => run(async () => {
    if (!sale.value) return;
    await withApproval((approval) => salesApi.cancel(sale.value!.id, { reason, approval }));
    remember(null);
  });

  const openCash = (register: string, amount: string) => run(async () => {
    session.value = await cashApi.open(register, amount, boot.value?.terminal.id);
  });

  const closeCash = (counted: string) => run(async () => {
    const closed = await cashApi.close(session.value!.id, counted);
    session.value = null;
    return closed;
  });

  const cashMovement = (kind: "withdrawal" | "supply", amount: string, reason: string) =>
    run(() => cashApi.movement(session.value!.id, kind, amount, reason));

  return { boot, session, sale, items, busy, needsCash, mode, isSeller, locked, init, setUser, scan, addVariant, setQuantity,
    removeItem, setCustomer, setDelivery, clearDelivery, discount, coupon, checkout, cancel, park, resume, lock, unlock, openCash, closeCash, cashMovement };
}

export type Pdv = ReturnType<typeof usePdv>;
