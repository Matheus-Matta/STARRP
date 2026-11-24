/**
 * PDV em tela cheia: barra de status · trilho de atalhos · área principal · pedido.
 *
 * A área principal troca DENTRO do PDV (sem janela por cima): catálogo, pedidos da loja, clientes,
 * entrega, caixa e o pagamento. Dois modos (vêm do bootstrap, pela permissão `cash.manage`):
 * - Vendedor: monta o pedido e "Envia ao caixa" (fica guardado); não vê caixa nem cobra.
 * - Caixa: turno aberto obrigatório, cobra, guarda/retoma pedidos e bloqueia a tela
 *   (F12 ou sozinha depois de `lock_minutes` parada; volta só com senha).
 *
 * Teclas: F1 venda · F2 pedidos · F3 cliente · F4 caixa · F5 preço (⇧F5 frete) · F6 desconto ·
 * F7 cupom · F8 sair · F9 guardar · F10 pagar/enviar (no pagamento: concluir) · Shift+F11 entrega · F12 bloquear.
 * Esc no pagamento volta para a venda. Toda regra está em `usePdv` e no backend; aqui só se desenha.
 *
 * Concluída a venda: com a nota fiscal ligada neste PC (Configurações), a NFC-e/NF-e sai pelo
 * comunicador ACBr local e o DANFE vai para a impressora da nota; sem nota, o recibo vai para a
 * impressora de recibos. Sem servidor, a venda é offline (ver `offline.ts`) e a nota também sai.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { cashApi, type OrderAddresses, type PaymentInput, salesApi } from "@/api/pdv";
import type { PdvProductView, Sale, SaleItem } from "@/api/types";
import { emitInvoice } from "@/lib/invoice";
import { printDanfe, printReceipt } from "@/lib/print";
import type { LocalInvoice } from "../../../shared/ipc";
import SettingsDialog from "@/pages/SettingsDialog";
import { net } from "@/state/net";
import PromptDialog, { type PromptAnswer, type PromptSpec } from "@/components/PromptDialog";
import { money } from "@/lib/format";
import { CANCEL_SALE_REASONS, PARK_REASONS, REMOVE_ITEM_REASONS } from "@/lib/reasons";
import { saleReceipt, shiftReceipt } from "@/lib/receipt";
import { ApprovalCancelled } from "@/state/approval";
import { logout, session } from "@/state/session";
import { useStore } from "@/state/store";
import { notify } from "@/state/toast";
import { Button, Dialog } from "@/ui";

import AddressConfirm from "./AddressConfirm";
import CashDialog, { type CashMode } from "./CashDialog";
import CashPanel, { type CashAction } from "./CashPanel";
import CatalogPanel, { type CatalogHandle } from "./CatalogPanel";
import type { Known } from "./CustomersPanel";
import { encodePresale, presaleQr, presaleTicket } from "./presale";
import Checkout, { type CheckoutHandle, type PaymentLine } from "./Checkout";
import CustomersPanel from "./CustomersPanel";
import DeliveryPanel from "./DeliveryPanel";
import FreightDialog from "./FreightDialog";
import Lock from "./Lock";
import OrderPanel from "./OrderPanel";
import OrdersPanel from "./OrdersPanel";
import PriceDialog from "./PriceDialog";
import ProductDialog from "./ProductDialog";
import Rail, { type RailAction } from "./Rail";
import StatusBar from "./StatusBar";
import { type CatalogProduct, useCatalog } from "./useCatalog";
import { usePdv } from "./usePdv";

type View = "sale" | "orders" | "customer" | "cash" | "delivery" | "address" | "payment";

export default function PdvPage() {
  const { me, storeId, config } = useStore(session);
  const pdv = usePdv({ id: me!.id, username: me!.username, name: me!.name, permissions: me!.permissions ?? [] });
  const [presale, setPresale] = useState<{ sale: Sale; code: string; qr: string } | null>(null);
  const catalog = useCatalog(storeId, pdv.offline);
  const client = useQueryClient();
  const catalogRef = useRef<CatalogHandle>(null);
  const checkoutRef = useRef<CheckoutHandle>(null);

  const [view, setView] = useState<View>("sale");
  /** Pagamentos lançados: sobrevivem à ida ao cliente/entrega e voltar; somem ao concluir ou trocar de venda. */
  const [paymentLines, setPaymentLines] = useState<PaymentLine[]>([]);
  const returnTo = useRef<View>("sale");
  const [cashMode, setCashMode] = useState<CashMode>("open");
  const [cashOpen, setCashOpen] = useState(false);
  const [priceOpen, setPriceOpen] = useState(false);
  const [freightOpen, setFreightOpen] = useState(false);
  const [viewing, setViewing] = useState<PdvProductView | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<PromptSpec | null>(null);
  const answerPrompt = useRef<(value: PromptAnswer | null) => void>(() => undefined);
  const [closedAlert, setClosedAlert] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const netState = useStore(net);

  useEffect(() => setPaymentLines([]), [pdv.sale?.id]);

  const seller = pdv.isSeller;
  const noCash = !pdv.boot || pdv.needsCash;
  const paying = view === "payment";
  const operator = me?.name ?? "";
  const screenLocked = pdv.locked && !seller && Boolean(pdv.boot);
  const myRegisters = pdv.boot?.cash_registers ?? [];

  const ask = (spec: PromptSpec) => new Promise<PromptAnswer | null>((resolve) => {
    setPrompt(spec);
    answerPrompt.current = (value) => {
      setPrompt(null);
      resolve(value);
    };
  });

  const focusSearch = useCallback(() => setTimeout(() => catalogRef.current?.focus()), []);

  async function guard(action: () => Promise<unknown>, title = "Não foi possível concluir") {
    try {
      await action();
    } catch (error) {
      if (!(error instanceof ApprovalCancelled)) notify.error(error, title);
    } finally {
      if (view === "sale") focusSearch();
    }
  }

  function show(next: View) {
    if ((next === "customer" || next === "delivery") && view !== next) returnTo.current = view === "payment" ? "payment" : "sale";
    setView(next);
    if (next === "sale") focusSearch();
  }

  /* ---- Impressão (bobina 80 mm, pelo processo principal) ---- */
  async function printSale(sale: Sale) {
    const cash = sale.payments.some((p) => p.method_kind === "cash" && (!p.status || p.status === "approved"));
    await printReceipt(saleReceipt(sale, pdv.boot, operator), { drawer: cash });
  }
  async function printShift(id: string, title?: string) {
    try {
      // Turno deste PC (aberto/fechado sem servidor) ou servidor fora: o comprovante sai do que o PC guardou.
      const here = id.startsWith("off:") || !net.get().online ? await pdv.shiftFor(id) : null;
      const shift = here ?? await cashApi.get(id);
      await printReceipt(shiftReceipt(shift, pdv.boot, title));
    } catch (error) {
      notify.error(error, "Comprovante não impresso");
    }
  }
  /** Reimprime: a venda concluída neste PC vem do histórico local (sem servidor também). */
  const reprint = (id: string) => void guard(async () => {
    if (id.startsWith("off:")) {
      const found = ((await window.starrp.local.history()) as unknown as (Sale & { server_id?: string })[]).find((s) => s.id === id);
      if (!found) throw new Error("Venda não encontrada neste PC.");
      if (!found.server_id || net.get().online === false) return printSale(found);
      id = found.server_id;
    }
    await printSale(await salesApi.get(id));
  }, "Recibo não impresso");

  /* ---- Venda ---- */
  async function pick(product: CatalogProduct) {
    if (opening) return;
    setOpening(product.id);
    try {
      setViewing(await pdv.productView(product.id));
    } catch (error) {
      notify.error(error, "Produto não carregado");
    } finally {
      setOpening(null);
    }
  }

  const confirmView = (variant: string, quantity: string, services: string[]) => void guard(async () => {
    await pdv.addVariant(variant, quantity, services);
    setViewing(null);
  }, "Item não lançado");

  const scan = (value: string) => void guard(() => pdv.scan(value), "Item não lançado");

  async function removeItem(item: SaleItem) {
    const services = pdv.items.filter((i) => i.parent_item === item.id);
    const answer = await ask({
      title: "Remover item", kind: "text", options: REMOVE_ITEM_REASONS, danger: true, confirmLabel: "Remover",
      label: `Por que remover "${item.description}"?${services.length ? ` Os serviços dele (${services.map((s) => s.description).join(", ")}) saem junto.` : ""}`,
    });
    if (answer) await guard(() => pdv.removeItem(item, answer.text ?? ""));
  }

  async function discount() {
    if (!pdv.sale) return;
    const answer = await ask({ title: "Desconto no total", label: "Desconto", kind: "discount", confirmLabel: "Aplicar" });
    if (answer) await guard(() => pdv.discount(answer));
  }

  async function coupon() {
    if (!pdv.sale) return;
    const answer = await ask({ title: "Cupom", label: "Código do cupom (vazio remove)", kind: "text", confirmLabel: "Aplicar" });
    if (answer) await guard(() => pdv.coupon(answer.text || null), "Cupom recusado");
  }

  async function cancelSale() {
    const answer = await ask({
      title: seller ? "Cancelar pedido" : "Cancelar venda", label: "Qual o motivo do cancelamento?", kind: "text", required: true,
      options: CANCEL_SALE_REASONS, danger: true, confirmLabel: seller ? "Cancelar pedido" : "Cancelar venda",
    });
    if (answer) await guard(async () => {
      await pdv.cancel(answer.text!);
      show("sale");
    });
  }

  /** F9: guarda o pedido para terminar depois. */
  async function park() {
    if (!pdv.items.length) return;
    const answer = await ask({ title: "Guardar pedido", label: "Por que o pedido fica guardado?", kind: "text", confirmLabel: "Guardar", options: PARK_REASONS });
    if (!answer) return;
    await guard(async () => {
      const parked = await pdv.park(answer.text ?? "");
      if (parked) {
        const here = parked.id.startsWith("off:");
        notify.success(here ? `Pedido OFF-${parked.number} guardado neste PC` : `Pedido ${parked.number} guardado`,
          here ? "Sem servidor: retome em Pedidos (F2), no quadro \"Guardados neste PC\"." : "Retome em Pedidos (F2) → Guardados.");
      }
      show("sale");
    }, "Pedido não guardado");
  }

  /** Vendedor: o pedido fica guardado na loja e qualquer caixa retoma para cobrar. */
  async function send() {
    if (!pdv.items.length) return;
    await guard(async () => {
      const parked = await pdv.park("Enviado ao caixa");
      if (parked?.presaleQueued) {
        // Sem servidor: o caixa lê o QR (na tela ou no ticket). O pedido também vai pela fila.
        const code = await encodePresale(parked);
        setPresale({ sale: parked, code, qr: await presaleQr(code) });
        if (config?.printing.autoReceipt ?? true) {
          void printReceipt(await presaleTicket(parked, code, pdv.boot?.store.name ?? "Starrp"));
        }
      } else if (parked) notify.success(`Pedido ${parked.number} enviado ao caixa`, `Total ${money(parked.total)}. Já pode atender o próximo.`);
    }, "Pedido não enviado");
  }

  /** Antes de pagar: com a regra ligada e o pedido COM endereço, confirma o endereço primeiro. */
  function openPayment() {
    if (seller || noCash || !pdv.sale || !Number(pdv.sale.total)) return;
    const addresses = pdv.sale.addresses as unknown as OrderAddresses | undefined;
    if (pdv.boot?.rules.confirm_address_at_checkout !== false && addresses?.delivery && view !== "address") return show("address");
    show("payment");
  }
  function addressConfirmed(addresses: OrderAddresses) {
    if (pdv.sale) pdv.replaceSale({ ...pdv.sale, addresses } as Sale);
    show("payment");
  }

  /** Concluiu: a tela JÁ é a próxima venda; o recibo sai sozinho se a filial imprime ao concluir. */
  /**
   * Concluiu: a tela JÁ é a próxima venda. A venda foi montada neste PC; a nota sai pelo ACBr
   * local e só então a venda vai ao servidor, PRONTA e junto com a nota (`pdv.send`). O DANFE
   * ou o recibo saem com o número real do servidor (ou OFF-n, se ele estiver fora).
   */
  const pay = (payments: PaymentInput[]) => void guard(async () => {
    const done = await pdv.checkout(payments);
    setPaymentLines([]);
    show("sale");
    const printing = config?.printing;
    const autoPrint = (printing?.autoReceipt ?? true) && pdv.boot?.rules.auto_print_receipt !== false;
    const cash = done.payments.some((p) => p.method_kind === "cash");
    let invoice: LocalInvoice | null = null;
    if (config?.fiscal.enabled && config.fiscal.autoEmit) {
      invoice = await emitInvoice(done, config.fiscal.model, { print: false });
      if (invoice && invoice.status !== "authorized" && invoice.status !== "contingency") invoice = null;
    }
    const server = await pdv.send(done).catch(() => null);
    const final = server ?? done;
    const change = Number(done.change_amount ?? 0);
    const sent = Boolean(server) || !done.id.startsWith("off:");
    notify.success(`${sent ? `Venda ${final.number}` : `Venda OFF-${done.number}`} concluída · ${money(done.total)}`,
      [change ? `Troco ${money(change)}.` : "", sent ? "" : "Ficou neste PC: vai para o servidor assim que ele responder."].filter(Boolean).join(" "));
    // O DANFE substitui o recibo (o cliente leva a nota).
    if (invoice && (printing?.autoInvoice ?? true)) {
      void printDanfe({ ...invoice, danfe: { ...invoice.danfe, sale_number: server ? server.number : `OFF-${done.number}` } }, undefined, cash);
    } else if (autoPrint) void printSale(final);
    void catalog.refresh(); // saldo dos cartões
    void client.invalidateQueries({ queryKey: ["pdv-cash"] });
  }, "Pagamento não concluído");

  const resume = (id: string) => void guard(async () => {
    const sale = await pdv.resume(id);
    notify.success(`Pedido ${sale.number} retomado`);
    show("sale");
  }, "Pedido não retomado");

  const pickCustomer = (body: { customer?: string | null; customer_document?: string }, known?: Known) => void guard(async () => {
    await pdv.setCustomer(body, known ?? null);
    show(returnTo.current);
  }, "Cliente não vinculado");

  const applyDelivery = (address: string, table: string) => void guard(async () => {
    await pdv.setDelivery(address, table);
    show(returnTo.current);
  }, "Entrega não lançada");

  const pickup = () => void guard(async () => {
    await pdv.clearDelivery();
    show(returnTo.current);
  }, "Não foi possível tirar a entrega");

  /* ---- Caixa ---- */
  function openCashDialog(mode: CashMode) {
    setCashMode(mode);
    setCashOpen(true);
  }
  function openingDone(id: string) {
    notify.success("Caixa aberto", "Comprovante de abertura enviado para a impressora.");
    void printShift(id, "ABERTURA DE CAIXA");
  }
  const managerApproves = () => void guard(async () => {
    const opened = await pdv.approveOpening("Conferido pelo gerente no PDV");
    setClosedAlert(false);
    if (opened?.status === "open") openingDone(opened.id);
  }, "Abertura não aprovada");

  function cashAction(action: CashAction) {
    if (action === "lock") pdv.lock();
    else if (action === "report") {
      if (pdv.session) void printShift(pdv.session.id, "COMPROVANTE DO TURNO");
    } else openCashDialog(action);
  }

  const confirmCash = (data: { register?: string; amount: string; reason: string }) => void guard(async () => {
    if (cashMode === "open") {
      const opened = await pdv.openCash(data.register!, data.amount, data.reason);
      setCashOpen(false);
      if (opened?.status === "open") openingDone(opened.id);
      else setClosedAlert(true); // não bateu: o aviso pede o gerente
    } else if (cashMode === "close") {
      const closed = await pdv.closeCash(data.amount);
      setCashOpen(false);
      if (closed.status !== "pending_approval") return notify.success("Caixa fechado");
      // Fechamento cego: o operador não vê a diferença; o gerente (ou a senha do caixa) aprova ali mesmo.
      try {
        await pdv.approveClosing(String(closed.id));
        notify.success("Caixa fechado", "Diferença aprovada pelo gerente.");
      } catch (error) {
        if (!(error instanceof ApprovalCancelled)) throw error;
        notify.warn("Caixa fechado", `${closed.difference != null ? `Diferença de ${money(closed.difference)}: ` : "Conferência enviada: "}aguardando aprovação do gerente.`);
      }
    } else {
      const label = cashMode === "withdrawal" ? "Sangria" : "Suprimento";
      const movement = await pdv.cashMovement(cashMode, data.amount, data.reason);
      setCashOpen(false);
      if (movement.status === "pending") {
        notify.warn(`${label} aguardando aprovação`, `${money(data.amount)}: o gerente aprova depois em Caixa. O caixa só fecha com ela aprovada ou recusada.`);
      } else notify.success(cashMode === "withdrawal" ? "Sangria lançada" : "Suprimento lançado", money(data.amount));
    }
  }, "Operação de caixa não concluída");

  async function exit() {
    await logout();
  }

  function rail(action: RailAction) {
    if (action === "price") setPriceOpen(true);
    else if (action === "freight") setFreightOpen(true);
    else if (action === "exit") void exit();
    else if (action === "settings") setSettingsOpen(true);
    else if (action === "cash" && seller) return;
    else show(action);
  }

  const continueOffline = () => void guard(async () => {
    const converted = await pdv.continueOffline();
    if (converted) notify.warn(`Venda continua offline como OFF-${converted.number}`, "Ao voltar, ela conclui o mesmo pedido no servidor.");
  }, "Não dá para continuar offline");

  // Servidor voltou: refaz o bootstrap (se abriu offline) e recarrega o catálogo guardado.
  useEffect(() => {
    if (!netState.online) return;
    void pdv.reconnect(config?.terminalName ?? "PDV", "");
  }, [netState.online]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void pdv.reloadSnapshot();
  }, [netState.snapshotAt]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- Início ---- */
  async function start() {
    setBootError(null);
    setBooting(true);
    try {
      if (!storeId) throw new Error("Seu usuário não tem acesso a nenhuma filial.");
      const [installation, version] = await Promise.all([window.starrp.config.installationId(storeId), window.starrp.app.version()]);
      await pdv.init(installation, config?.terminalName ?? "PDV", version);
    } catch (error) {
      setBootError(notify.error(error, "Não foi possível iniciar o PDV").message);
    } finally {
      setBooting(false);
    }
  }
  useEffect(() => {
    void start();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!booting && pdv.boot && pdv.needsCash && !pdv.locked) setClosedAlert(true);
  }, [booting]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- Teclado, bloqueio por inatividade e fechar com venda aberta ---- */
  const idleTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const touch = useCallback(() => {
    clearTimeout(idleTimer.current);
    const minutes = pdv.boot?.lock_minutes ?? 0;
    if (seller || !minutes || pdv.locked || paying) return;
    idleTimer.current = setTimeout(() => pdv.lock(), minutes * 60_000);
  }, [pdv.boot, pdv.locked, seller, paying]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    touch();
    return () => clearTimeout(idleTimer.current);
  }, [touch]);

  // O ouvinte é registrado uma vez e sempre chama a versão mais nova (sem closures velhas).
  const onKey = useRef<(event: KeyboardEvent) => void>(() => undefined);
  onKey.current = (event: KeyboardEvent) => {
    touch();
    if (screenLocked || bootError) return;
    const dialogOpen = Boolean(document.querySelector("[data-dialog]"));
    if (event.key === "Escape" && view === "payment" && !dialogOpen) {
      event.preventDefault();
      return show("sale");
    }
    if (event.key === "Tab" && view === "sale" && !dialogOpen && document.activeElement?.id !== "pdv-scanner") {
      event.preventDefault();
      return focusSearch();
    }
    const actions: Record<string, () => void> = {
      F1: () => rail("sale"), F2: () => rail("orders"), F3: () => rail("customer"), F4: () => rail("cash"),
      F5: () => rail(event.shiftKey ? "freight" : "price"), F6: () => void discount(), F7: () => void coupon(),
      F8: () => rail("exit"), F9: () => void park(), F11: () => event.shiftKey && pdv.sale && show("delivery"),
      F10: () => (seller ? void send() : view === "payment" ? checkoutRef.current?.finish() : openPayment()),
      F12: () => !seller && pdv.lock(),
    };
    const action = actions[event.key];
    if (!action) return;
    // A tecla é sempre do PDV; com um diálogo aberto ela só vale se for o F10.
    event.preventDefault();
    if (!dialogOpen || event.key === "F10") action();
  };
  const hasItems = useRef(false);
  hasItems.current = pdv.items.length > 0;

  useEffect(() => {
    const keydown = (e: KeyboardEvent) => onKey.current(e);
    const pointer = () => touch();
    // Fechar o app no meio de um pedido: o processo principal pergunta antes (a venda fica salva).
    const leave = (e: BeforeUnloadEvent) => {
      if (hasItems.current) e.preventDefault();
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("pointerdown", pointer);
    window.addEventListener("beforeunload", leave);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("pointerdown", pointer);
      window.removeEventListener("beforeunload", leave);
    };
  }, [touch]);

  /* ---- Tela ---- */
  const active: RailAction = view === "delivery" || view === "address" || view === "payment" ? "sale" : view;
  const sale = pdv.sale;
  let main;
  if (bootError) {
    main = (
      <div className="grid flex-1 place-items-center p-6">
        <div className="flex max-w-md flex-col items-center gap-3 text-center">
          <span className="grid size-14 place-items-center rounded-full bg-danger-subtle text-xl text-danger-text"><i className="pi pi-exclamation-triangle" /></span>
          <h2 className="text-lg font-bold text-strong">O PDV não iniciou</h2>
          <p className="text-[13.5px] text-muted">{bootError}</p>
          <div className="flex gap-2">
            <Button icon="pi pi-refresh" onClick={() => void start()}>Tentar de novo</Button>
            <Button variant="secondary" icon="pi pi-sign-out" onClick={() => void exit()}>Sair</Button>
          </div>
        </div>
      </div>
    );
  } else if (view === "payment" && sale) {
    main = (
      <Checkout ref={checkoutRef} sale={sale} items={pdv.items} methods={pdv.boot?.payment_methods ?? []} sellers={pdv.boot?.sellers ?? []}
        operator={operator} busy={pdv.busy} requireReference={!!pdv.boot?.rules.require_payment_reference}
        requireSeller={!!pdv.boot?.rules.require_seller} lines={paymentLines} setLines={setPaymentLines}
        onFinish={pay} onBack={() => show("sale")} onCustomer={() => show("customer")} onDelivery={() => show("delivery")}
        onDiscount={() => void discount()} onCoupon={() => void coupon()}
        onSeller={(id) => void guard(() => pdv.setCustomer({ seller: id }))} />
    );
  } else if (view === "orders") {
    main = <OrdersPanel seller={seller} busy={pdv.busy} boot={pdv.boot} operator={operator} onResume={resume} onPrint={reprint} onBack={() => show("sale")} />;
  } else if (view === "customer") {
    main = (
      <CustomersPanel busy={pdv.busy} offline={pdv.offline} onPick={pickCustomer} onBack={() => show(returnTo.current)}
        current={sale?.customer_name || sale?.customer_document ? { name: sale.customer_name, document: sale.customer_document ?? "" } : null} />
    );
  } else if (view === "address" && sale) {
    main = <AddressConfirm sale={sale} onConfirmed={addressConfirmed} onBack={() => show("sale")} />;
  } else if (view === "delivery") {
    main = <DeliveryPanel sale={sale} busy={pdv.busy} onApply={applyDelivery} onPickup={pickup} onCustomer={() => show("customer")} onBack={() => show(returnTo.current)} />;
  } else if (view === "cash" && !seller) {
    main = (
      <CashPanel session={pdv.session} operator={operator} seesDrawer={!!pdv.boot?.sees_drawer} version={pdv.cashChanged}
        register={pdv.boot?.my_register ?? null} onAction={cashAction} onBack={() => show("sale")} />
    );
  } else {
    main = (
      <CatalogPanel ref={catalogRef} catalog={catalog} disabled={(!seller && noCash) || pdv.busy || booting} opening={opening} offline={pdv.offline}
        onPick={(p) => void pick(p)} onCode={scan} />
    );
  }

  return (
    <div className="flex h-full flex-col bg-ground">
      <StatusBar cashOpen={!!pdv.session && pdv.session.status === "open"} operator={operator} since={pdv.session?.opened_at ?? null}
        terminal={pdv.boot?.terminal?.name ?? ""} seller={seller} canSwitchStore={!sale && !pdv.session}
        onLock={() => pdv.lock()} onCash={() => setClosedAlert(true)} onSettings={() => setSettingsOpen(true)} />
      <div className="flex min-h-0 flex-1">
        <Rail active={active} seller={seller} onSelect={rail} />
        {main}
        {view !== "payment" && !bootError && (
          <OrderPanel sale={sale} items={pdv.items} sellers={pdv.boot?.sellers ?? []} busy={pdv.busy} seller={seller}
            onCustomer={() => show("customer")} onSeller={(id) => void guard(() => pdv.setCustomer({ seller: id }))}
            onQuantity={(item, qty) => void guard(() => pdv.setQuantity(item, qty))} onRemove={(i) => void removeItem(i)}
            onDiscount={() => void discount()} onCoupon={() => void coupon()} onPay={openPayment} onCancel={() => void cancelSale()}
            onPark={() => void park()} onSend={() => void send()} onDelivery={() => show("delivery")}
            offline={pdv.offline} localSale={pdv.isLocalSale} onContinueOffline={continueOffline} />
        )}
      </div>

      <ProductDialog product={viewing} busy={pdv.busy} onConfirm={confirmView} onClose={() => { setViewing(null); focusSearch(); }} />
      <PriceDialog open={priceOpen} onClose={() => { setPriceOpen(false); focusSearch(); }} />
      <FreightDialog open={freightOpen} onClose={() => { setFreightOpen(false); focusSearch(); }} />
      <CashDialog open={cashOpen} mode={cashMode} registers={pdv.boot?.cash_registers ?? []} myRegister={pdv.boot?.my_register ?? null}
        busy={pdv.busy} onClose={() => setCashOpen(false)} onConfirm={confirmCash} />
      <Dialog open={presale !== null} onClose={() => setPresale(null)} width={420} title={`Pré-venda ${presale?.sale.number ?? ""}`}
        footer={<>
          <Button variant="secondary" icon="pi pi-print" onClick={() => presale && void presaleTicket(presale.sale, presale.code, pdv.boot?.store.name ?? "Starrp").then((html) => printReceipt(html))}>Imprimir ticket</Button>
          <Button icon="pi pi-check" autoFocus onClick={() => setPresale(null)}>Próximo cliente</Button>
        </>}>
        {presale && (
          <div className="flex flex-col items-center gap-2 text-center">
            <p className="text-[13px] text-muted">Sem servidor: o caixa lê este código com o leitor (na tela ou no ticket) e cobra na hora. O pedido também vai ao servidor quando ele voltar.</p>
            <img src={presale.qr} alt="QR da pré-venda" className="size-[260px] rounded-lg bg-white p-2" />
            <strong className="text-[18px] text-strong">Total {money(presale.sale.total)}</strong>
            <small className="text-muted">{presale.sale.items.filter((i) => i.status === "active").length} itens · {presale.sale.customer_name || "sem cliente"}</small>
          </div>
        )}
      </Dialog>
      <Dialog open={closedAlert && noCash && !seller && !!pdv.boot} onClose={() => setClosedAlert(false)} width={400}
        title={pdv.pendingOpening ? "Abertura aguardando o gerente" : "Caixa fechado"}
        footer={<>
          <Button variant="ghost" onClick={() => setClosedAlert(false)}>Agora não</Button>
          {pdv.pendingOpening ? <Button icon="pi pi-verified" autoFocus loading={pdv.busy} onClick={managerApproves}>Gerente aprova</Button>
            : myRegisters.length ? <Button icon="pi pi-lock-open" autoFocus onClick={() => { setClosedAlert(false); openCashDialog("open"); }}>Abrir caixa</Button>
              : null}
        </>}>
        <div className="flex flex-col items-center gap-2.5 px-1 pt-1.5 text-center">
          <span className="grid size-14 place-items-center rounded-full bg-warning-subtle text-[22px] text-warning-text"><i className="pi pi-lock" /></span>
          <p className="text-[13.5px] text-muted">
            {pdv.pendingOpening
              ? "O dinheiro contado não bate com o que o último fechamento deixou na gaveta. Chame o gerente para conferir: ele aprova com a senha dele (ou a senha de ações do caixa)."
              : myRegisters.length ? "Para vender, abra o caixa: conte o dinheiro que está na gaveta e informe."
                : <>Você não está vinculado a nenhum caixa desta filial. Peça ao gerente para vincular em <b>Financeiro → Caixas</b>.</>}
          </p>
        </div>
      </Dialog>
      <PromptDialog spec={prompt} onAnswer={(v) => answerPrompt.current(v)} />
      <SettingsDialog open={settingsOpen} onClose={() => { setSettingsOpen(false); focusSearch(); }} />
      {screenLocked && <Lock operator={operator} managerPassword={!!pdv.boot?.has_cash_action_password} unlock={pdv.unlock} onLogout={() => void exit()} />}
    </div>
  );
}
