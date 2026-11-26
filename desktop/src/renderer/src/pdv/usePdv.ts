/**
 * Estado e ações do PDV. A tela só desenha; tudo que mexe na venda passa aqui.
 *
 * LOCAL-FIRST no caixa: a venda é montada e calculada NESTE PC (`offline.ts`), com o catálogo
 * guardado, e vai PRONTA ao servidor no fim (`/pdv/offline-sales/`) — junto com a nota emitida
 * pelo ACBr local. Com o servidor no ar a venda é validada antes de cobrar (crediário, cupom,
 * frete) e já sai com o número real; sem ele, fica na fila e vai quando ele voltar.
 *
 * - a venda em andamento fica guardada no PC (criptografada): fechou o app, volta igual;
 * - desconto, preço e cancelamento acima do limite pedem gerente (`authorize`: online confere
 *   no servidor e aprende a senha; offline confere pela senha aprendida);
 * - cupom e entrega/frete pedem o servidor (a prévia calcula e a venda adota);
 * - "guardar": com o servidor, vira pedido guardado da loja (qualquer caixa retoma); sem ele,
 *   fica guardado neste PC;
 * - retomar um pedido do servidor (do vendedor) traz para o PC; concluir conclui O MESMO pedido;
 * - modo "seller" (vendedor): monta o pedido aqui também. "Enviar ao caixa": com o servidor vira
 *   pedido guardado da loja; sem ele vai pela fila E vira uma pré-venda com QR (tela/ticket) que o
 *   caixa lê — funciona sem rede nenhuma entre os PCs;
 * - o TURNO de caixa é do terminal (como no mercado): abrir, sangria/suprimento e fechar funcionam
 *   sem servidor e vão pela mesma fila, em ordem (abertura → vendas → fechamento). Turno aberto
 *   sem servidor ("off:...") segue local até o fim, mesmo que o servidor volte.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import { cashApi, type PaymentInput, salesApi } from "@/api/pdv";
import { ApiError } from "@/api/errors";
import { idempotencyKey } from "@/api/client";
import type { CashSession, PdvBootstrap, PdvProductView, Sale, SaleItem } from "@/api/types";
import { ApprovalCancelled, withApproval } from "@/state/approval";
import { isNetworkError, isOffline, net } from "@/state/net";
import { useStore } from "@/state/store";

import type { AuthorizeRequest, CashState, Snapshot } from "../../../shared/ipc";
import * as off from "./offline";
import { decodePresale, isPresaleCode } from "./presale";
import * as rules from "./rules";

/** Venda local da versão anterior (localStorage): migra uma vez para o arquivo do PC. */
const legacyKey = (userId: number) => `starrp.pdv.localSale:${userId}`;
function takeLegacy(userId: number): Sale | null {
  try {
    const raw = localStorage.getItem(legacyKey(userId));
    localStorage.removeItem(legacyKey(userId));
    return raw ? (JSON.parse(raw) as Sale) : null;
  } catch {
    return null;
  }
}

const NEEDS_SERVER = "precisa do servidor. Espere a conexão voltar ou siga sem isso.";

const lockKey = (userId: number) => `starrp.pdv.locked:${userId}`;
const readLock = (userId: number) => {
  try {
    return localStorage.getItem(lockKey(userId)) === "1";
  } catch {
    return false;
  }
};

export type PdvOperator = { id: number; username: string; name: string; permissions: string[] };

export function usePdv(operator: PdvOperator) {
  const userId = operator.id;
  const [boot, setBoot] = useState<PdvBootstrap | null>(null);
  const [session, setSession] = useState<CashSession | null>(null);
  const [sale, setSaleState] = useState<Sale | null>(null);
  const [busyCount, setBusyCount] = useState(0);
  const [locked, setLocked] = useState(() => readLock(userId));
  const [cashChanged, setCashChanged] = useState(0);
  const saleRef = useRef<Sale | null>(null);
  const bootRef = useRef<PdvBootstrap | null>(null);
  const sessionRef = useRef<CashSession | null>(null);
  const checkoutKey = useRef<string | null>(null);
  const installationRef = useRef("");
  const snapshotRef = useRef<Snapshot | null>(null);
  /** Vitrines vistas online (produto novo que ainda não está no catálogo guardado). */
  const viewsRef = useRef(new Map<string, { product: off.SnapProduct; services: PdvProductView["services"] }>());
  const saving = useRef<Promise<unknown>>(Promise.resolve());
  const [bootOffline, setBootOffline] = useState(false);
  const netState = useStore(net);
  const offline = !netState.online || bootOffline;

  const remember = useCallback((next: Sale | null) => {
    const open = next && next.status === "open" ? next : null;
    saleRef.current = open;
    setSaleState(open);
    // Grava em ordem (a última versão sempre ganha): a venda sobrevive a fechar o app.
    const local = open && off.isLocal(open) ? (open as unknown as Record<string, unknown>) : null;
    saving.current = saving.current.then(() => window.starrp.local.saveCurrentSale(userId, local)).catch(() => undefined);
  }, [userId]);

  async function snapshot() {
    snapshotRef.current ??= await window.starrp.offline.snapshot();
    if (!snapshotRef.current) throw new off.OfflineRefused("Sem catálogo guardado neste PC: conecte ao servidor uma vez para baixar.");
    return snapshotRef.current;
  }
  const reloadSnapshot = async () => {
    snapshotRef.current = await window.starrp.offline.snapshot();
  };
  const local = () => off.isLocal(saleRef.current);
  const serverDown = () => offline || isOffline();
  const cashier = () => bootRef.current?.mode !== "seller";
  const sessionId = () => sessionRef.current?.id ?? null;
  const payload = (s: Sale, extra: Record<string, unknown> = {}) =>
    off.salePayload(s, installationRef.current, sessionId(), { operator: userId, ...extra });

  /** Venda do servidor (vendedor): falha de rede vira um aviso claro. */
  async function online<T>(action: () => Promise<T>): Promise<T> {
    try {
      return await action();
    } catch (error) {
      if (isNetworkError(error)) {
        throw new off.OfflineRefused(saleRef.current && cashier()
          ? "O servidor não respondeu. Use \"Continuar offline\" no pedido para terminar esta venda neste PC."
          : "O servidor não respondeu. Tente de novo quando a conexão voltar.");
      }
      throw error;
    }
  }
  const setCash = (next: CashSession | null) => {
    sessionRef.current = next;
    setSession(next);
  };
  /** O turno guardado neste PC (verdade do terminal) + o último bootstrap em cache. */
  async function saveCash(change: (state: CashState) => CashState) {
    const state = change(await window.starrp.local.cash());
    // Turno do servidor: guarda QUANDO o "esperado agora" foi lido (a gaveta offline parte dele).
    const s = state.session as (Record<string, unknown> & { id: string; expected_at?: string }) | null;
    if (s && !s.id.startsWith(off.OFFLINE_PREFIX) && !s.expected_at) s.expected_at = new Date().toISOString();
    await window.starrp.local.saveCash(state);
    const cache = await window.starrp.offline.cache();
    if (cache.boot) await window.starrp.offline.saveCache({ ...cache, boot: { ...(cache.boot as object), cash_session: state.session } });
    setCashChanged((n) => n + 1);
    return state;
  }
  const isLocalShift = (s: CashSession | null) => Boolean(s?.id.startsWith(off.OFFLINE_PREFIX));
  /** Dinheiro em gaveta para a regra da sangria, quando o PC SABE: turno aberto aqui (tudo passou
   *  por este PC) ou turno do servidor com o "esperado" já lido dele. Sem isso (fechamento cego
   *  e nunca lido), null: a regra fica com o servidor, que aceita a sangria offline como fato. */
  async function drawerNow(shift: CashSession): Promise<number | null> {
    const [state, history] = await Promise.all([window.starrp.local.cash(), window.starrp.local.history()]);
    const known = isLocalShift(shift)
      || (Boolean(shift.expected_now) && (state.session as { expected_at?: string } | null)?.expected_at !== undefined);
    return known ? rules.drawerOf(shift, state, history).expected : null;
  }

  /**
   * Quem autoriza a ação na venda local: o próprio operador (permissão/limite dele) ou um
   * superior pelo diálogo — conferido no servidor quando ele está no ar, senão pelas senhas
   * que este PC aprendeu. Devolve o id de quem autorizou (null = senha de ações do caixa).
   */
  async function authorize(code: AuthorizeRequest["code"], percent?: number, what?: Record<string, unknown>): Promise<number | null> {
    const own = code === "sales.discount"
      ? (percent ?? 0) <= Number(bootRef.current?.operator?.max_discount_percent ?? 0) + 1e-9
      : operator.permissions.includes(code) || operator.permissions.includes("*"); // "*" = administrador da conta
    if (own) return userId;
    return withApproval(async (approval) => {
      const result = await window.starrp.local.authorize({ code, percent, what, approval: approval as AuthorizeRequest["approval"] });
      if (!result.ok) throw new ApiError(result.status, result.code, result.message);
      return result.approver?.id ?? null;
    });
  }

  const items = useMemo(() => (sale?.items ?? []).filter((i: SaleItem) => i.status === "active"), [sale]);
  const mode = boot?.mode ?? "cashier";
  const isSeller = mode === "seller";
  /** Só vende com o turno ABERTO (a abertura com diferença espera o gerente). */
  const needsCash = !isSeller && Boolean(boot?.rules.require_open_cash_session) && session?.status !== "open";
  const pendingOpening = session?.status === "pending_opening";

  async function run<T>(action: () => Promise<T>): Promise<T> {
    setBusyCount((n) => n + 1);
    try {
      return await action();
    } finally {
      setBusyCount((n) => n - 1);
    }
  }

  async function init(installationId: string, terminalName: string, version: string) {
    installationRef.current = installationId;
    let data: PdvBootstrap;
    let fromCache = false;
    try {
      data = await salesApi.bootstrap(installationId, terminalName, version);
      const cache = await window.starrp.offline.cache();
      await window.starrp.offline.saveCache({ ...cache, boot: data });
      setBootOffline(false);
      // Abriu online: o catálogo guardado é atualizado já (preço novo vale desde a abertura).
      void window.starrp.offline.refreshSnapshot().then(reloadSnapshot);
    } catch (error) {
      if (!isNetworkError(error)) throw error;
      const cached = (await window.starrp.offline.cache()).boot as PdvBootstrap | undefined;
      if (!cached) throw error;
      data = cached; // servidor fora: o último bootstrap (formas de pagamento, turno, vendedores)
      setBootOffline(true);
      fromCache = true;
    }
    bootRef.current = data;
    setBoot(data);
    // Turno: o deste PC manda (aberto sem servidor, ou fechado aqui com o fechamento ainda na fila).
    const shift = await window.starrp.local.cash();
    let current = data.cash_session;
    if (isLocalShift(shift.session as CashSession | null)) current = shift.session as unknown as CashSession;
    else if (current && shift.closing.includes(current.id)) current = null;
    else if (fromCache) current = (shift.session as unknown as CashSession | null) ?? current;
    setCash(current);
    await saveCash((s) => ({ ...s, session: current as unknown as Record<string, unknown> | null }));
    // A venda em andamento neste PC (app fechado no meio) volta primeiro.
    const pending = ((await window.starrp.local.currentSale(userId)) as Sale | null) ?? takeLegacy(userId);
    if (pending) return remember(pending);
    // Venda aberta no servidor (versão antiga do PDV ou vendedor), menos a que já está na fila.
    const replaced = new Set((await window.starrp.offline.outbox()).map((e) => String(e.payload.replaces ?? "")));
    const open = (await salesApi.myOpen(userId).catch(() => ({ results: [] as Sale[] }))).results[0];
    if (!open || replaced.has(open.id)) return;
    const full = await salesApi.get(open.id).catch(() => null);
    if (!full) return;
    {
      try {
        return remember(off.fromServerSale(full, await window.starrp.offline.nextLocalNumber(), false));
      } catch {
        // já tem pagamento no servidor: segue como venda do servidor
      }
    }
    remember(full);
  }

  /** O servidor voltou depois de abrir offline: refaz o bootstrap (turno, formas de pagamento). */
  async function reconnect(terminalName: string, version: string) {
    if (!bootOffline || isOffline()) return;
    try {
      const data = await salesApi.bootstrap(installationRef.current, terminalName, version);
      bootRef.current = data;
      setBoot(data);
      setCash(data.cash_session);
      setBootOffline(false);
    } catch {
      // continua offline
    }
  }

  async function newLocal() {
    const me = bootRef.current?.sellers.find((s) => s.user_id === userId);
    const seller = bootRef.current?.mode === "seller" && me ? { id: me.user_id, name: me.name } : null;
    const created = off.newLocalSale(await window.starrp.offline.nextLocalNumber(), seller, serverDown());
    remember(created);
    return created;
  }

  async function ensureSale() {
    const current = saleRef.current;
    if (current && current.status === "open") return current;
    // Caixa e vendedor: a venda/pedido nasce neste PC (o vendedor já como vendedor dele).
    await snapshot();
    return newLocal();
  }
  const current = () => saleRef.current!;

  /** Produto que não está no catálogo guardado (cadastrado agora): busca no servidor. */
  async function findOnline(code: string) {
    if (serverDown()) return null;
    try {
      const found = await salesApi.lookup(code);
      const product = {
        id: found.id, name: found.display_name, unit: "UN", reference: "",
        variants: [{ id: found.id, name: found.display_name, sku: found.sku, price: found.list_price, current_price: found.current_price }],
      } as unknown as off.SnapProduct;
      const weight = (found as { scale_quantity?: string | null }).scale_quantity;
      const total = (found as { scale_total?: string | null }).scale_total;
      return { product, variant: product.variants[0]!, quantity: weight ? Number(weight) : null, total: total ? Number(total) : null };
    } catch (error) {
      if (isNetworkError(error) || (error instanceof ApiError && error.status === 404)) return null;
      throw error;
    }
  }

  /** Guarda o pedido e libera a tela. Vendedor: "enviar ao caixa". Caixa: pedido guardado da loja
   *  (servidor no ar) ou guardado neste PC (servidor fora). */
  const park = (note = "") => run(async (): Promise<(Sale & { presaleQueued?: boolean }) | null> => {
    const open = saleRef.current;
    if (!open) return null;
    if (!local()) {
      const parked = await online(() => salesApi.park(open.id, note));
      remember(null);
      return parked;
    }
    if (!open.items.some((i) => i.status === "active")) throw new off.OfflineRefused("Pedido vazio não é guardado: lance ao menos um item.");
    if (!serverDown()) {
      try {
        const parked = await salesApi.ready(payload(open, { park: true, park_note: note, payments: [], total: null }));
        remember(null);
        return parked;
      } catch (error) {
        if (!isNetworkError(error)) throw error;
      }
    }
    if (!cashier()) {
      // Vendedor sem servidor: o pedido vai pela fila (vira pedido guardado quando ele voltar) e
      // a tela mostra o QR da pré-venda para o caixa ler agora.
      await window.starrp.offline.enqueueSale(payload(open, { park: true, park_note: note || "Enviado ao caixa", payments: [], total: null }),
        `Pré-venda ${open.number}`);
      remember(null);
      return { ...open, presaleQueued: true };
    }
    await window.starrp.local.park({ ...open, notes: [open.notes, note].filter(Boolean).join("\n") } as unknown as Record<string, unknown>);
    remember(null);
    return { ...open, parked_at: new Date().toISOString() };
  });

  /** Retoma um pedido (do servidor ou guardado neste PC). A venda pela metade é guardada antes. */
  const resume = (id: string) => run(async () => {
    const open = saleRef.current;
    if (open && open.id !== id && open.items.some((i) => i.status === "active")) {
      if (off.isLocal(open)) await window.starrp.local.park(open as unknown as Record<string, unknown>);
      else await online(() => salesApi.park(open.id));
    }
    if (id.startsWith(off.OFFLINE_PREFIX)) {
      const found = (await window.starrp.local.unpark(id)) as Sale | null;
      if (!found) throw new off.OfflineRefused("Pedido guardado não encontrado neste PC.");
      remember({ ...found, parked_at: null });
      return found;
    }
    const resumed = await online(() => salesApi.resume(id));
    // O pedido vem para o PC; concluir (ou enviar de novo ao caixa) usa ESTE pedido (mesmo número).
    const converted = off.fromServerSale(resumed, await window.starrp.offline.nextLocalNumber(), false);
    remember(converted);
    return resumed;
  });

  function lock() {
    setLocked(true);
    try {
      localStorage.setItem(lockKey(userId), "1");
    } catch {
      // sem storage: o bloqueio vale até fechar o app
    }
  }
  async function unlock(password: string) {
    if (!(await window.starrp.local.unlock(operator.username, password))) {
      throw new off.OfflineRefused(serverDown()
        ? "Senha incorreta (sem o servidor vale a senha do operador ou a senha de ações do caixa já usada neste PC)."
        : "Senha incorreta.");
    }
    setLocked(false);
    try {
      localStorage.removeItem(lockKey(userId));
    } catch {
      // idem
    }
  }

  /** Leitor de código: aceita "3*789..." para lançar 3 unidades. */
  const scan = (raw: string) => run(async () => {
    if (isPresaleCode(raw)) return loadPresale(raw);
    const [qty, code] = raw.includes("*") ? raw.split("*", 2) : [undefined, raw];
    const open = await ensureSale();
    if (off.isLocal(open)) {
      const snap = await snapshot();
      const read = (code ?? "").trim();
      const found: { product: off.SnapProduct; variant: off.SnapVariant; quantity?: number | null; total?: number | null } | null =
        off.lookupCode(snap, read) ?? off.scaleLabel(snap, read, bootRef.current?.rules) ?? await findOnline(read);
      if (!found) throw new off.OfflineRefused(`Código ${code} não encontrado${serverDown() ? " no catálogo guardado deste PC" : ""}.`);
      if (!qty && found.quantity) {
        return remember(off.addLocalItem(open, found.product, found.variant, found.quantity, [], found.total ?? null));
      }
      return remember(off.addLocalItem(open, found.product, found.variant, Number((qty ?? "1").replace(",", ".")) || 1));
    }
    remember(await online(() => withApproval((approval) =>
      salesApi.addItem(open.id, { code: (code ?? "").trim(), quantity: qty?.replace(",", "."), approval }))));
  });

  /** Vitrine: lança a variante e, junto, os serviços escolhidos (entra tudo ou nada). */
  const addVariant = (variant: string, quantity = "1", services: string[] = []) => run(async () => {
    const open = await ensureSale();
    if (off.isLocal(open)) {
      const seen = viewsRef.current.get(variant);
      const found = seen ? { product: seen.product, variant: seen.product.variants.find((v) => v.id === variant)! } : off.findVariant(await snapshot(), variant);
      if (!found) throw new off.OfflineRefused("Produto fora do catálogo guardado.");
      const chosen = (seen?.services ?? []).filter((s) => services.includes(s.variant));
      if (services.length && chosen.length !== services.length) throw new off.OfflineRefused(`Serviços (montagem, garantia) ${NEEDS_SERVER}`);
      return remember(off.addLocalItem(open, found.product, found.variant, Number(quantity.replace(",", ".")) || 1, chosen));
    }
    remember(await online(() => withApproval((approval) =>
      salesApi.addItem(open.id, { variant, quantity, approval, ...(services.length ? { services } : {}) }))));
  });

  const setQuantity = (item: SaleItem, quantity: string) => run(async () => {
    if (local()) return remember(off.setLocalQuantity(current(), item.id, Number(quantity.replace(",", "."))));
    remember(await online(() => withApproval((approval) => salesApi.updateItem(current().id, item.id, { quantity, approval }))));
  });

  const removeItem = (item: SaleItem, reason: string) => run(async () => {
    if (local()) {
      await authorize("sales.cancel_item");
      return remember(off.removeLocalItem(current(), item.id));
    }
    remember(await online(() => withApproval((approval) => salesApi.cancelItem(current().id, item.id, { reason, approval }))));
  });

  const setCustomer = (body: { customer?: string | null; customer_document?: string; seller?: number | null },
    known?: { id: string; name: string; document: string } | null) => run(async () => {
    const open = await ensureSale();
    if (off.isLocal(open)) return remember(off.setLocalCustomer(open, await snapshot(), body, bootRef.current?.sellers ?? [], known));
    remember(await online(() => salesApi.setCustomer(open.id, body)));
  });

  /** Prévia no servidor (nada grava): cupom, frete e endereços calculados lá. */
  async function preview(s: Sale, extra: Record<string, unknown>) {
    if (serverDown()) throw new off.OfflineRefused(`Isso ${NEEDS_SERVER}`);
    try {
      return await salesApi.ready(payload(s, { payments: [], total: null, ...extra }), true);
    } catch (error) {
      if (isNetworkError(error)) throw new off.OfflineRefused(`O servidor não respondeu: isso ${NEEDS_SERVER}`);
      throw error;
    }
  }

  const setDelivery = (address: string, table: string) => run(async () => {
    if (local()) {
      if (!current().customer) throw new off.OfflineRefused("Identifique o cliente antes de lançar a entrega.");
      const delivery = { address, table };
      return remember(off.adoptPreview(current(), await preview(current(), { delivery }), delivery));
    }
    remember(await online(() => salesApi.delivery(current().id, address, table)));
  });
  const clearDelivery = () => run(async () => {
    if (local()) return remember(off.clearLocalDelivery(current()));
    remember(await online(() => salesApi.clearDelivery(current().id)));
  });

  const discount = (body: { amount?: string; percent?: string }) => run(async () => {
    if (local()) {
      const open = current();
      const amount = off.discountAmount(open, body);
      const percent = Number(open.subtotal) ? (amount / Number(open.subtotal)) * 100 : 0;
      const approver = amount ? await authorize("sales.discount", Math.round(percent * 100) / 100) : null;
      return remember(off.setLocalDiscount(open, amount, approver));
    }
    remember(await online(() => withApproval((approval) => salesApi.discount(current().id, { ...body, approval }))));
  });

  const coupon = (code: string | null) => run(async () => {
    if (local()) {
      const open = current();
      if (!code) return remember(off.recalc({ ...open, coupon_code: "", coupon_discount: "0.00" }));
      const result = await preview(open, { coupon_code: code });
      if (!result.coupon_code) throw new off.OfflineRefused("Cupom não aplicado.");
      return remember(off.adoptPreview(open, result));
    }
    remember(await online(() => (code ? salesApi.applyCoupon(current().id, code) : salesApi.removeCoupon(current().id))));
  });

  /** Venda do servidor (ainda sem pagamento) passa para este PC: termina sem depender dele. */
  const continueOffline = () => run(async () => {
    const open = saleRef.current;
    if (!open || off.isLocal(open)) return open;
    await snapshot();
    const converted = off.fromServerSale(open, await window.starrp.offline.nextLocalNumber(), true);
    remember(converted);
    return converted;
  });

  /**
   * Cobra a venda local. Servidor no ar: valida ANTES (prévia com os pagamentos: crediário,
   * limite, cupom e frete recalculados) — recusou, a venda continua aberta para corrigir.
   * Depois conclui aqui e põe na fila SEGURADA: a tela emite a nota e chama `send`, que manda
   * venda + nota juntas. Sem servidor: conclui do mesmo jeito e vai quando ele voltar.
   */
  const checkout = (payments: PaymentInput[]) => run(async () => {
    if (local()) {
      const methods = bootRef.current?.payment_methods ?? [];
      let open = current();
      let checked = false;
      // As mesmas regras do checkout do servidor, aqui: o que vai pela fila não volta recusado.
      rules.checkSale(open, payments, bootRef.current, sessionRef.current, !serverDown());
      if (!serverDown()) {
        try {
          const meta = off.metaOf(open);
          if (open.coupon_code || meta._delivery) {
            const fresh = off.adoptPreview(open, await salesApi.ready(payload(open, { payments: [], total: null }), true));
            if (fresh.total !== open.total) {
              remember(fresh);
              throw new off.OfflineRefused(`O servidor recalculou cupom/frete: o total agora é R$ ${fresh.total.replace(".", ",")}. Confira o pagamento.`);
            }
            open = fresh;
          }
          await salesApi.ready(payload(off.completeLocal(open, payments, methods, true)), true);
          checked = true;
        } catch (error) {
          if (!isNetworkError(error)) throw error;
        }
      }
      const done = off.completeLocal({ ...open, metafields: { ...off.metaOf(open), offline: !checked } }, payments, methods, checked);
      await window.starrp.offline.enqueueSale(payload(done), checked ? `Venda ${done.number}` : `Venda offline OFF-${done.number}`, true);
      await window.starrp.local.remember({ ...done, cash_session: sessionId() } as unknown as Record<string, unknown>);
      remember(null);
      return done;
    }
    checkoutKey.current ??= idempotencyKey();
    const done = await salesApi.checkout(current().id, payments, checkoutKey.current);
    checkoutKey.current = null;
    remember(null);
    return done;
  });

  /** Solta a venda concluída para o servidor (com a nota, se saiu). Devolve a venda do servidor
   *  (número real) ou null se ficou na fila. */
  async function send(done: Sale): Promise<Sale | null> {
    if (!off.isLocal(done)) return done;
    const result = await window.starrp.offline.flush(done.id.slice(off.OFFLINE_PREFIX.length));
    return result.status === "done" && result.sale ? (result.sale as unknown as Sale) : null;
  }

  const cancel = (reason: string) => run(async () => {
    const open = saleRef.current;
    if (!open) return;
    if (off.isLocal(open)) {
      const replaces = off.metaOf(open).replaces;
      if (replaces && !serverDown()) {
        // O pedido veio do servidor: cancela lá (com o gerente, se pedir).
        await withApproval((approval) => salesApi.cancel(replaces, { reason, approval }));
      } else if (open.items.some((i) => i.status === "active")) {
        await authorize("sales.cancel");
      }
      return remember(null); // a venda local nunca chegou ao servidor: só some daqui
    }
    await withApproval((approval) => salesApi.cancel(open.id, { reason, approval }));
    remember(null);
  });

  /** Vitrine: online pela API (e guarda para lançar); sem servidor, o produto como foi guardado. */
  async function productView(id: string): Promise<PdvProductView> {
    if (!serverDown()) {
      try {
        const view = await salesApi.productView(id);
        const product = view as unknown as off.SnapProduct;
        for (const v of view.variants) viewsRef.current.set(v.id, { product, services: view.services ?? [] });
        return view;
      } catch (error) {
        if (!isNetworkError(error)) throw error;
      }
    }
    const product = ((await snapshot()).products as unknown as off.SnapProduct[]).find((p) => p.id === id);
    if (!product) throw new off.OfflineRefused("Produto fora do catálogo guardado.");
    return { ...product, services: [] } as unknown as PdvProductView;
  }

  /** Atualiza a venda da tela (ex.: endereços confirmados antes do pagamento). */
  const replaceSale = (next: Sale) => remember(next);

  /** Ticket da pré-venda lido no caixa: a venda nasce com os itens, o vendedor e o cliente dele. */
  async function loadPresale(raw: string) {
    const open = saleRef.current;
    if (open?.items.some((i) => i.status === "active")) throw new off.OfflineRefused("Conclua ou guarde a venda atual antes de ler a pré-venda.");
    const pre = await decodePresale(raw).catch(() => {
      throw new off.OfflineRefused("Código de pré-venda ilegível: leia de novo.");
    });
    const outbox = await window.starrp.offline.outbox();
    const history = await window.starrp.local.history();
    if (history.some((s) => (s.metafields as { presale?: string } | null)?.presale === pre.offlineId)
      || outbox.some((e) => e.payload.presale === pre.offlineId)) {
      throw new off.OfflineRefused(`A pré-venda ${pre.number} já foi cobrada neste caixa.`);
    }
    const snap = await snapshot();
    const base = off.newLocalSale(await window.starrp.offline.nextLocalNumber(),
      pre.seller ? { id: pre.seller, name: pre.sellerName } : null, serverDown());
    const known = pre.customer ? snap.customers.find((c) => c.id === pre.customer) : undefined;
    const ids = pre.items.map(() => crypto.randomUUID());
    const items: SaleItem[] = pre.items.map((row, index) => {
      const found = off.findVariant(snap, row.variant);
      return {
        id: ids[index]!, description: row.description, sku: found?.variant.sku ?? "", unit: found?.product.unit ?? "UN",
        quantity: row.quantity, list_price: row.parent === null ? found?.variant.price ?? row.unit_price : row.unit_price, unit_price: row.unit_price, discount: row.discount,
        total: "0.00", status: "active", variant: row.variant,
        promotion: row.parent === null && found && found.variant.current_price !== found.variant.price
          && Number(row.unit_price) === Number(found.variant.current_price) ? found.variant.promotion ?? "shelf" : null,
        parent_item: row.parent === null ? null : ids[row.parent] ?? null,
      };
    });
    const sale = off.recalc({
      ...base, items, customer: pre.customer, customer_name: known?.name ?? pre.customerName, customer_document: pre.document,
      discount: pre.discount,
      metafields: { ...off.metaOf(base), presale: pre.offlineId, presale_number: pre.number, _discount_approved_by: Number(pre.discount) ? pre.seller : null },
    });
    remember(sale);
    return sale;
  }

  const openCash = (register: string, amount: string, notes = "") => run(async () => {
    if (!serverDown()) {
      try {
        const opened = await cashApi.open(register, amount, bootRef.current?.terminal.id, notes);
        setCash(opened);
        await saveCash((s) => ({ ...s, session: opened as unknown as Record<string, unknown>, movements: [] }));
        return opened;
      } catch (error) {
        if (!isNetworkError(error)) throw error;
      }
    }
    // Sem servidor: o turno abre NESTE PC (a conferência cega é feita no servidor quando chegar),
    // depois das mesmas regras que o servidor aplicaria.
    rules.checkOpen(bootRef.current?.cash_registers ?? [], sessionRef.current, register, amount);
    const id = crypto.randomUUID();
    const now = new Date().toISOString();
    const name = bootRef.current?.cash_registers.find((r) => r.id === register)?.name ?? "Caixa";
    const opened: CashSession = {
      id: `${off.OFFLINE_PREFIX}${id}`, register, register_name: name, opened_by_name: operator.name, status: "open",
      opened_at: now, opening_amount: Number(amount).toFixed(2), expected_now: Number(amount).toFixed(2), expected_amount: "0.00",
      difference: "0.00", closed_at: null, counted_amount: null, pending_movements: 0,
    };
    await window.starrp.offline.enqueueCash({
      event: "open", offline_id: id, register, opening_amount: opened.opening_amount, notes, opened_at: now,
      installation_id: installationRef.current, operator: userId,
    }, `Abertura do ${name}`);
    setCash(opened);
    await saveCash((s) => ({ ...s, session: opened as unknown as Record<string, unknown>, movements: [] }));
    return opened;
  });

  /** O turno (aberto ou fechado aqui) para o comprovante sem servidor. */
  async function shiftFor(id: string): Promise<CashSession | null> {
    const state = await window.starrp.local.cash();
    const found = [state.session, ...state.closed].find((s) => s?.id === id);
    return (found as unknown as CashSession) ?? null;
  }

  /** Gerente confere a abertura com diferença (pede a senha dele ou a do caixa). */
  const approveOpening = (reason = "") => run(async () => {
    if (serverDown()) throw new off.OfflineRefused("Abrir, fechar e movimentar o caixa precisa do servidor.");
    const approved = await withApproval((approval) => cashApi.approveOpening(sessionRef.current!.id, approval, reason));
    setCash(approved);
    return approved;
  });

  /**
   * Fecha o turno. Turno do servidor, servidor no ar e nada na fila: fecha lá na hora (o gerente
   * aprova a diferença ali mesmo). Senão fecha AQUI: o fechamento entra na fila depois das vendas
   * do turno e o servidor faz a conferência cega quando receber (diferença fica para o gerente).
   */
  const closeCash = (counted: string) => run(async () => {
    const shift = sessionRef.current!;
    if (!serverDown() && !isLocalShift(shift)) {
      if ((await window.starrp.offline.status()).pending) await window.starrp.offline.syncNow();
      if (!(await window.starrp.offline.status()).pending) {
        try {
          const closed = await cashApi.close(shift.id, counted);
          setCash(null);
          await saveCash((s) => ({ ...s, session: null, movements: [], closed: [closed as unknown as Record<string, unknown>, ...s.closed] }));
          return closed;
        } catch (error) {
          if (!isNetworkError(error)) throw error;
        }
      }
    }
    const state = await window.starrp.local.cash();
    rules.checkClose(shift, counted, rules.drawerOf(shift, state, []).pending);
    const id = crypto.randomUUID();
    const now = new Date().toISOString();
    await window.starrp.offline.enqueueCash({
      event: "close", offline_id: id, session: shift.id, counted_amount: Number(counted).toFixed(2), closed_at: now, operator: userId,
    }, `Fechamento do ${shift.register_name}`);
    const closed: CashSession = { ...shift, status: "closed", counted_amount: Number(counted).toFixed(2), closed_at: now };
    setCash(null);
    await saveCash((s) => ({
      ...s, session: null, movements: [], closed: [closed as unknown as Record<string, unknown>, ...s.closed], closing: [...s.closing, shift.id],
    }));
    void window.starrp.offline.syncNow();
    return closed;
  });

  /** Sangria/suprimento: lança e, se ficou pendente, já pede a autorização. Cancelar deixa pendente. */
  const cashMovement = (kind: "withdrawal" | "supply", amount: string, reason: string) => run(async () => {
    const shift = sessionRef.current!;
    if (serverDown() || isLocalShift(shift)) {
      // Sem servidor (ou turno deste PC): o gerente/senha do caixa aprova AGORA (conferida pela
      // senha que o PC aprendeu) e o movimento entra na fila. Cancelar desiste do movimento.
      // As mesmas regras do servidor ANTES de lançar (sangria até a gaveta, turno aberto...).
      rules.checkMovement(shift, kind, amount, await drawerNow(shift));
      const approver = await authorize("cash.approve", undefined, { event: "movement", kind, amount: Number(amount).toFixed(2) });
      const id = crypto.randomUUID();
      const now = new Date().toISOString();
      const label = kind === "withdrawal" ? "Sangria" : "Suprimento";
      await window.starrp.offline.enqueueCash({
        event: "movement", offline_id: id, session: shift.id, kind, amount: Number(amount).toFixed(2), reason, at: now,
        approved_by: approver, by_password: approver === null, operator: userId,
      }, `${label} ${Number(amount).toFixed(2).replace(".", ",")}`);
      const movement = {
        id: `${off.OFFLINE_PREFIX}${id}`, session: shift.id, kind, amount: Number(amount).toFixed(2), status: "approved", reason,
        operator_name: operator.name, created_at: now,
      };
      await saveCash((s) => ({ ...s, movements: [...s.movements, movement] }));
      return movement as unknown as Awaited<ReturnType<typeof cashApi.movement>>;
    }
    const movement = await cashApi.movement(shift.id, kind, amount, reason);
    setCashChanged((n) => n + 1);
    if (movement.status !== "pending") return movement;
    try {
      const approved = await withApproval((approval) => cashApi.approveMovement(String(movement.id), "", approval));
      setCashChanged((n) => n + 1);
      return approved;
    } catch (error) {
      if (error instanceof ApprovalCancelled) return movement;
      throw error;
    }
  });

  /** Fechamento com diferença: o gerente (ou a senha do caixa) aprova ali mesmo, com justificativa. */
  const approveClosing = (id: string) => run(() =>
    withApproval((approval, reason) => cashApi.approveClosing(id, reason ?? "", approval), {
      reason: "Justificativa da diferença (ex.: troco dado errado)",
      message: "A gaveta não bateu com o esperado. O gerente confere e aprova o fechamento.",
    }));

  return {
    boot, session, sale, items, busy: busyCount > 0, needsCash, mode, isSeller, locked, pendingOpening, cashChanged,
    offline, isLocalSale: off.isLocal(sale), installationId: () => installationRef.current,
    init, reconnect, reloadSnapshot, productView, continueOffline, scan, addVariant, setQuantity, removeItem, setCustomer, setDelivery, clearDelivery, discount, coupon, checkout,
    send, shiftFor, cancel, park, resume, lock, unlock, openCash, approveOpening, closeCash, cashMovement, approveClosing, replaceSale,
  };
}

export type Pdv = ReturnType<typeof usePdv>;
