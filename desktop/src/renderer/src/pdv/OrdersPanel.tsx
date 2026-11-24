/**
 * Pedidos da loja DENTRO do PDV (só os desta loja: a API recorta pela loja ativa). Clicar abre o
 * pedido aqui mesmo, como na retaguarda web: situação, nota fiscal, cliente, itens, pagamentos,
 * entrega e valores, e as ações que o cargo permite (`OrderActions.tsx`).
 *
 * Sem servidor: mostra as vendas feitas offline neste PC que ainda esperam o envio.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { salesApi } from "@/api/pdv";
import { deliveryOf, type PdvBootstrap, type Sale } from "@/api/types";
import { emitInvoice } from "@/lib/invoice";
import { printDanfe, printReceipt } from "@/lib/print";
import { fromServerDanfe } from "@/lib/danfe";
import { saleReceipt } from "@/lib/receipt";
import { net } from "@/state/net";
import { can, session } from "@/state/session";
import { useStore } from "@/state/store";
import { notify } from "@/state/toast";
import {
  dateTime, FULFILLMENT_FLOW, FULFILLMENT_STATUS, FULFILLMENT_TONE, money, OVERALL_STATUS, OVERALL_TONE,
  PAYMENT_STATUS, PAYMENT_TONE, quantity,
} from "@/lib/format";
import { Button, cx, Empty, IconButton, Input, Segmented, Select, Spinner, Tag } from "@/ui";

import type { LocalInvoice, PrinterTarget } from "../../../shared/ipc";
import {
  AddressesDialog, CancelOrderDialog, DeliveryEditDialog, EmitDialog, PaymentChangeDialog, PrinterPickDialog,
} from "./OrderActions";
import { orderedItems } from "./OrderPanel";

type Filter = "all" | "draft" | "open" | "deliveries" | "completed" | "cancelled";
const OPTIONS: { value: Filter; label: string }[] = [
  { value: "all", label: "Todos" }, { value: "draft", label: "Guardados" }, { value: "open", label: "Em aberto" },
  { value: "deliveries", label: "Entregas" }, { value: "completed", label: "Concluídos hoje" }, { value: "cancelled", label: "Cancelados hoje" },
];
const PARAMS: Record<Filter, Record<string, string>> = {
  all: {}, draft: { status: "draft" }, open: { status: "open" },
  deliveries: { status: "completed", fulfillment_status__in: "pending,ready,shipped" },
  completed: { overall_status: "completed" }, cancelled: { status: "cancelled" },
};
const today = () => new Date().toLocaleDateString("sv-SE");
const ORDERING: Record<Filter, string> = {
  all: "-created_at", draft: "-created_at", open: "-created_at", deliveries: "completed_at",
  completed: "-completed_at", cancelled: "-created_at",
};
const PAGE_SIZES = [{ value: 10, label: "10" }, { value: 20, label: "20" }, { value: 50, label: "50" }];
const OVERALL_OPTIONS = Object.entries(OVERALL_STATUS).map(([value, label]) => ({ value, label }));
const PAYMENT_OPTIONS = Object.entries(PAYMENT_STATUS).map(([value, label]) => ({ value, label }));
const FULFILLMENT_OPTIONS = Object.entries(FULFILLMENT_STATUS).map(([value, label]) => ({ value, label }));
const DOCUMENT_OPTIONS = [
  { value: "open", label: "Aberta" }, { value: "draft", label: "Pedido guardado" },
  { value: "completed", label: "Concluída" }, { value: "cancelled", label: "Cancelada" },
];
const CHANNEL_OPTIONS = [
  { value: "pos", label: "PDV" }, { value: "mobile", label: "PDV móvel" },
  { value: "backoffice", label: "Retaguarda" }, { value: "ecommerce", label: "Loja virtual" },
];
type ListFilters = {
  overall_status: string; payment_status: string; fulfillment_status: string; status: string; channel: string;
  completed_at__gte: string; completed_at__lte: string;
};
const EMPTY_FILTERS: ListFilters = {
  overall_status: "", payment_status: "", fulfillment_status: "", status: "", channel: "",
  completed_at__gte: "", completed_at__lte: "",
};

type Props = {
  seller: boolean; busy: boolean; boot: PdvBootstrap | null; operator: string;
  onResume: (id: string) => void; onPrint: (id: string) => void; onBack: () => void;
};

export default function OrdersPanel(props: Props) {
  const { seller, onBack } = props;
  const status = useStore(net);
  const [opened, setOpened] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [ordering, setOrdering] = useState(ORDERING.all);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<ListFilters>(EMPTY_FILTERS);
  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(search.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    setPage(1);
    setOrdering(ORDERING[filter]);
  }, [filter]);

  const activeFilters = Object.values(filters).filter(Boolean).length;
  const setListFilter = (key: keyof ListFilters, value: string | null) => {
    setFilters((current) => ({ ...current, [key]: value ?? "" }));
    setPage(1);
  };
  const sortBy = (field: string) => {
    const current = ordering.replace(/^-/, "");
    setOrdering(current !== field ? field : ordering.startsWith("-") ? ORDERING[filter] : `-${field}`);
    setPage(1);
  };

  const list = useQuery({
    queryKey: ["pdv-orders", filter, term, filters, ordering, page, pageSize],
    queryFn: () => salesApi.list({
      ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)),
      ...PARAMS[filter],
      ...(filter === "completed" || filter === "cancelled" ? { created_at__gte: `${today()}T00:00:00` } : {}),
      ordering, search: term || undefined, page, page_size: pageSize,
    }),
    placeholderData: (p) => p,
    refetchInterval: 30_000,
    enabled: status.online,
  });
  // Guardados NESTE PC (servidor fora na hora de guardar) e as vendas concluídas aqui.
  const parkedHere = useQuery({
    queryKey: ["pdv-local-parked", props.busy], queryFn: async () => (await window.starrp.local.parked()) as unknown as Sale[],
  });
  const historyHere = useQuery({
    queryKey: ["pdv-local-history", status.pending, status.lastSync],
    queryFn: async () => (await window.starrp.local.history()) as unknown as (Sale & { server_number?: number })[],
    enabled: !status.online,
  });
  const queue = useQuery({
    queryKey: ["pdv-outbox", status.pending, status.failed, status.lastSync], queryFn: () => window.starrp.offline.outbox(),
  });

  const hint = {
    all: "Todos os pedidos da filial, os mais recentes primeiro. Use os filtros para achar guardados, entregas...",
    draft: seller ? "Pedidos guardados da filial. Abra um para ver e continuar editando." : "Abra um pedido para conferir, retomar e cobrar.",
    open: "Vendas em andamento agora nos caixas da filial.",
    deliveries: "Pagas e ainda não entregues (as mais antigas primeiro). Abra para separar, despachar e dar baixa.",
    completed: "Abra uma venda para conferir, emitir ou reimprimir a nota.",
    cancelled: "Vendas canceladas hoje nesta filial.",
  }[filter];

  if (opened) return <OrderView id={opened} {...props} onBack={() => setOpened(null)} />;

  const rows = status.online ? list.data?.results ?? [] : [];
  const total = list.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total ? (page - 1) * pageSize + 1 : 0;
  const last = Math.min(page * pageSize, total);
  const waiting = queue.data ?? [];

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-3">
      <header className="flex shrink-0 items-center gap-2.5">
        <IconButton icon="pi pi-arrow-left" label="Voltar para a venda" onClick={onBack} />
        <div><h2 className="panel-title">Pedidos da filial</h2><p className="text-[13px] text-muted">{hint}</p></div>
      </header>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Segmented value={filter} onChange={setFilter} options={OPTIONS} />
      </div>

      {waiting.length > 0 && (
        <div className="shrink-0 rounded-[10px] border border-warning bg-warning-subtle px-3 py-2">
          <p className="mb-1 flex items-center gap-1.5 text-[12.5px] font-bold text-warning-text">
            <i className="pi pi-cloud-upload" /> Vendas deste PC esperando o servidor ({waiting.length})
          </p>
          <ul className="flex flex-col text-[13px]">
            {waiting.map((e) => (
              <li key={e.id} className="flex items-center gap-3 border-t border-line-subtle py-1.5 first:border-0">
                <span className="font-semibold text-strong">{e.label}</span>
                <span className="text-muted">{dateTime(e.createdAt)}</span>
                <span className="text-muted">{money((e.payload.payments as { amount: string }[] | undefined)?.reduce((s, p) => s + Number(p.amount), 0) ?? 0)}</span>
                <span className="ml-auto truncate text-[12px] text-danger-text">{e.status === "failed" ? e.lastError : ""}</span>
                <Tag tone={e.status === "failed" ? "danger" : "warning"}>{e.status === "failed" ? "Recusada" : "Na fila"}</Tag>
                {e.status === "failed" && <Button size="sm" variant="secondary" icon="pi pi-replay" onClick={() => void window.starrp.offline.retry(e.id)}>Tentar</Button>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(parkedHere.data ?? []).length > 0 && (
        <div className="shrink-0 rounded-[10px] border border-line bg-card px-3 py-2">
          <p className="mb-1 flex items-center gap-1.5 text-[12.5px] font-bold text-strong">
            <i className="pi pi-bookmark" /> Guardados neste PC ({parkedHere.data!.length})
          </p>
          <ul className="flex flex-col text-[13px]">
            {parkedHere.data!.map((s) => (
              <li key={s.id} className="flex items-center gap-3 border-t border-line-subtle py-1.5 first:border-0">
                <span className="font-semibold text-strong">OFF-{s.number}</span>
                <span className="text-muted">{s.parked_at ? dateTime(s.parked_at) : ""}</span>
                <span className="truncate text-muted">{s.customer_name || "Sem cliente"}</span>
                <span className="ml-auto font-semibold text-strong">{money(s.total)}</span>
                {!seller && <Button size="sm" icon="pi pi-play" loading={props.busy} onClick={() => props.onResume(s.id)}>Retomar</Button>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* A lista rola DENTRO do cartão: o cabeçalho e a paginação ficam no lugar. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[10px] border border-line bg-card">
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line-subtle p-2.5">
          <div className="relative min-w-[240px] max-w-[360px] flex-1">
            <i className="pi pi-search absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por número ou cliente…  ( / )"
              className="pl-9" disabled={!status.online} />
          </div>
          <Button size="sm" variant={activeFilters ? "primary" : "secondary"} icon="pi pi-sliders-h"
            disabled={!status.online} onClick={() => setFiltersOpen((open) => !open)}>
            Filtros{activeFilters ? ` (${activeFilters})` : ""}
          </Button>
          <span className="ml-auto text-[12.5px] text-muted">{total.toLocaleString("pt-BR")} {total === 1 ? "registro" : "registros"}</span>
          {activeFilters > 0 && (
            <Button size="sm" variant="ghost" icon="pi pi-filter-slash" onClick={() => { setFilters(EMPTY_FILTERS); setPage(1); }}>Limpar</Button>
          )}
          <IconButton icon={list.isFetching ? "pi pi-spin pi-spinner" : "pi pi-refresh"} label="Atualizar"
            disabled={!status.online || list.isFetching} onClick={() => void list.refetch()} />
        </div>
        {filtersOpen && status.online && (
          <div className="grid shrink-0 grid-cols-[repeat(5,minmax(150px,1fr))] gap-2 border-b border-line-subtle bg-sunken p-2.5">
            <Select value={filters.overall_status || null} options={OVERALL_OPTIONS} placeholder="Status geral"
              onChange={(value) => setListFilter("overall_status", value)} />
            <Select value={filters.payment_status || null} options={PAYMENT_OPTIONS} placeholder="Pagamento"
              onChange={(value) => setListFilter("payment_status", value)} />
            <Select value={filters.fulfillment_status || null} options={FULFILLMENT_OPTIONS} placeholder="Entrega"
              onChange={(value) => setListFilter("fulfillment_status", value)} />
            <Select value={filters.status || null} options={DOCUMENT_OPTIONS} placeholder="Documento no caixa"
              onChange={(value) => setListFilter("status", value)} />
            <Select value={filters.channel || null} options={CHANNEL_OPTIONS} placeholder="Canal"
              onChange={(value) => setListFilter("channel", value)} />
            <label className="flex items-center gap-2 text-[12px] text-muted">
              <span className="shrink-0">De</span><Input type="date" value={filters.completed_at__gte}
                onChange={(event) => setListFilter("completed_at__gte", event.target.value)} />
            </label>
            <label className="flex items-center gap-2 text-[12px] text-muted">
              <span className="shrink-0">Até</span><Input type="date" value={filters.completed_at__lte}
                onChange={(event) => setListFilter("completed_at__lte", event.target.value)} />
            </label>
          </div>
        )}
        {!status.online ? (
          (historyHere.data ?? []).length ? (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <p className="sticky top-0 z-[1] bg-card px-3 py-2 text-[12.5px] text-muted shadow-[0_1px_0_var(--border-subtle)]">
                <i className="pi pi-wifi mr-1.5 text-warning-text" />Servidor sem resposta: estas são as vendas concluídas NESTE PC (guardadas aqui).
              </p>
              <table className="w-full text-[13px]">
                <tbody>
                  {historyHere.data!.map((s) => (
                    <tr key={s.id} className="border-t border-line-subtle">
                      <td className="px-3 py-2 font-semibold text-strong">{s.server_number ? `Venda ${s.server_number}` : `OFF-${s.number}`}</td>
                      <td className="px-3 py-2 text-muted">{s.completed_at ? dateTime(s.completed_at) : ""}</td>
                      <td className="px-3 py-2 text-muted">{s.customer_name || "Sem cliente"}</td>
                      <td className="px-3 py-2 text-right font-semibold text-strong">{money(s.total)}</td>
                      <td className="px-3 py-2 text-right">
                        <Button size="sm" variant="secondary" icon="pi pi-print" onClick={() => props.onPrint(s.id)}>Recibo</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty icon="pi pi-wifi" title="Servidor sem resposta">Os pedidos da filial aparecem quando a conexão voltar.</Empty>
        ) : list.isPending ? <Spinner label="Carregando pedidos…" /> : !rows.length ? <Empty icon="pi pi-inbox" title="Nenhum pedido aqui" /> : (
          <div className="min-h-0 flex-1 overflow-auto">
            <table className="min-w-[1320px] w-full text-[13px]">
              <thead className="sticky top-0 z-[1] bg-card text-left text-[11.5px] tracking-wide text-muted uppercase shadow-[0_1px_0_var(--border-subtle)]">
                <tr>
                  <SortHeader field="number" label="Nº" ordering={ordering} onSort={sortBy} />
                  <SortHeader field="created_at" label={filter === "draft" ? "Guardado" : "Aberto em"} ordering={ordering} onSort={sortBy} />
                  <SortHeader field="customer_name" label="Cliente" ordering={ordering} onSort={sortBy} />
                  <SortHeader field="seller_name" label="Vendedor" ordering={ordering} onSort={sortBy} />
                  <th className="px-3 py-2">Itens</th>
                  <SortHeader field="total" label="Total" ordering={ordering} onSort={sortBy} right />
                  <SortHeader field="overall_status" label="Status geral" ordering={ordering} onSort={sortBy} />
                  <SortHeader field="payment_status" label="Pagamento" ordering={ordering} onSort={sortBy} />
                  <SortHeader field="fulfillment_status" label="Entrega" ordering={ordering} onSort={sortBy} />
                  <th className="w-20 px-3 py-2 text-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} tabIndex={0} onClick={() => setOpened(s.id)}
                    onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && setOpened(s.id)}
                    className="cursor-pointer border-b border-line-subtle last:border-0 hover:bg-hover focus:bg-hover focus:outline-0">
                    <td className="px-3 py-2.5 font-bold text-strong">{s.number}</td>
                    <td className="px-3 py-2.5">{dateTime(s.created_at)}</td>
                    <td className="px-3 py-2.5">{s.customer_name || "—"}</td>
                    <td className="px-3 py-2.5">{s.seller_name || "—"}</td>
                    <td className="px-3 py-2.5">{s.item_count ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right font-semibold text-strong">{money(s.total)}</td>
                    <td className="px-3 py-2.5"><Tag tone={OVERALL_TONE[s.overall_status]}>{OVERALL_STATUS[s.overall_status] ?? s.status}</Tag></td>
                    <td className="px-3 py-2.5"><Tag tone={PAYMENT_TONE[s.payment_status]}>{PAYMENT_STATUS[s.payment_status] ?? s.payment_status}</Tag></td>
                    <td className="px-3 py-2.5"><Tag tone={FULFILLMENT_TONE[s.fulfillment_status]}>{FULFILLMENT_STATUS[s.fulfillment_status] ?? s.fulfillment_status}</Tag></td>
                    <td className="px-2 py-1.5 text-right" onClick={(event) => event.stopPropagation()}>
                      <span className="inline-flex items-center">
                        <IconButton icon="pi pi-eye" label="Abrir pedido" className="size-8" onClick={() => setOpened(s.id)} />
                        <IconButton icon="pi pi-print" label="Imprimir recibo" className="size-8" onClick={() => props.onPrint(s.id)} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {status.online && total > 0 && (
          <div className="relative flex min-h-12 shrink-0 items-center justify-center gap-2 border-t border-line-subtle p-2 text-[12.5px] text-muted">
            <label className="absolute left-3 flex items-center gap-2">Linhas
              <Select value={pageSize} options={PAGE_SIZES} onChange={(value) => { if (value) { setPageSize(value); setPage(1); } }} className="h-8 w-18 py-0" />
            </label>
            <IconButton icon="pi pi-chevron-left" label="Anterior" disabled={page <= 1} onClick={() => setPage(page - 1)} />
            Página {page} de {pages}
            <IconButton icon="pi pi-chevron-right" label="Próxima" disabled={page >= pages} onClick={() => setPage(page + 1)} />
            <span className="absolute right-3">{first}–{last} de {total}</span>
          </div>
        )}
      </div>
    </section>
  );
}

function SortHeader({ field, label, ordering, onSort, right = false }: {
  field: string; label: string; ordering: string; onSort: (field: string) => void; right?: boolean;
}) {
  const active = ordering.replace(/^-/, "") === field;
  const icon = !active ? "pi pi-sort-alt" : ordering.startsWith("-") ? "pi pi-sort-amount-down" : "pi pi-sort-amount-up";
  return (
    <th className={cx("px-3 py-2", right && "text-right")} aria-sort={active ? (ordering.startsWith("-") ? "descending" : "ascending") : "none"}>
      <button type="button" onClick={() => onSort(field)}
        className={cx("inline-flex items-center gap-1 font-bold hover:text-brand-text", right && "ml-auto")}>
        {label}<i className={cx(icon, "text-[10px]", active ? "text-brand-text" : "text-subtle")} />
      </button>
    </th>
  );
}

/* ── o pedido aberto ───────────────────────────────────────────────────────── */

const NEXT = [
  { to: "ready", label: "Separado", icon: "pi pi-box" },
  { to: "shipped", label: "Saiu para entrega", icon: "pi pi-truck" },
  { to: "delivered", label: "Entregue", icon: "pi pi-home" },
];
const INVOICE_TONE: Record<string, string> = {
  authorized: "success", processing: "info", draft: "warning", error: "danger", rejected: "danger", cancelled: "neutral",
  contingency: "warning",
};
const LOCAL_STATUS: Record<string, string> = {
  authorized: "Autorizada", contingency: "Contingência (a transmitir)", rejected: "Rejeitada", error: "Erro", processing: "Em processamento",
};
type Modal = null | "addresses" | "delivery" | "payment" | "cancel" | "emit" | "print-other";

function OrderView({ id, busy, seller, boot, operator, onBack, onResume }: Props & { id: string }) {
  const { me, config } = useStore(session);
  const query = useQuery({ queryKey: ["pdv-order", id], queryFn: () => salesApi.get(id) });
  const locals = useQuery({ queryKey: ["pdv-order-local-invoices", id], queryFn: () => window.starrp.fiscal.invoices(id) });
  const sale = query.data;
  const [moving, setMoving] = useState(false);
  const [backing, setBacking] = useState(false);
  const [reason, setReason] = useState("");
  const [modal, setModal] = useState<Modal>(null);
  const [working, setWorking] = useState<string | null>(null);

  const reload = async () => {
    setModal(null);
    await Promise.all([query.refetch(), locals.refetch()]);
  };
  const step = FULFILLMENT_FLOW.indexOf(String(sale?.fulfillment_status));
  const canMove = can(me, "logistics.manage");
  const delivers = sale?.status === "completed" && Boolean(sale.shipping_address) && step >= 0;
  const { delivery } = deliveryOf(sale ?? null);
  const items = (sale?.items ?? []).filter((i) => i.status === "active");
  const cancelledItems = (sale?.items ?? []).filter((i) => i.status === "cancelled");
  const payments = sale?.payments ?? [];
  const approved = payments.filter((p) => !p.status || p.status === "approved");
  const serverInvoice = sale?.invoices?.[0] ?? null;
  const localInvoice: LocalInvoice | null = (locals.data ?? []).find((i) => i.status === "authorized" || i.status === "contingency") ?? null;
  const authorizedModels = new Set([...(sale?.invoices ?? []).filter((i) => i.status === "authorized").map((i) => i.document_model),
    ...(locals.data ?? []).filter((i) => i.status === "authorized" || i.status === "contingency").map((i) => i.document_model)]);
  const deliveryEditable = sale?.status === "completed" && !["delivered", "returned", "cancelled"].includes(String(sale?.fulfillment_status));
  const canEmit = Boolean(config?.fiscal.enabled) && !seller && can(me, "cash.manage") && sale?.status === "completed" && authorizedModels.size === 0;
  const hasInvoice = Boolean(localInvoice || (serverInvoice && serverInvoice.status !== "rejected" && serverInvoice.status !== "error"));

  async function move(to: string, note = "") {
    setMoving(true);
    try {
      await salesApi.fulfillment(id, to, note);
      await query.refetch();
      setBacking(false);
      setReason("");
      notify.success(`Entrega: ${FULFILLMENT_STATUS[to]}`, to === "delivered" ? "Pedido concluído." : undefined);
    } catch (error) {
      notify.error(error, "Entrega não atualizada");
    } finally {
      setMoving(false);
    }
  }

  async function task(name: string, action: () => Promise<unknown>) {
    setWorking(name);
    try {
      await action();
    } catch (error) {
      notify.error(error, "Não foi possível concluir");
    } finally {
      setWorking(null);
    }
  }

  const emit = (model: "65" | "55") => {
    setModal(null);
    void task("emit", async () => {
      await emitInvoice(sale!, model, { print: config?.printing.autoInvoice ?? true });
      await reload();
    });
  };
  /** A nota do pedido: a emitida por este PC (imprime sem servidor) ou a do servidor (DANFE de lá). */
  const printInvoice = (target?: PrinterTarget) => {
    setModal(null);
    void task("print", async () => {
      if (localInvoice) return printDanfe(localInvoice, target);
      if (serverInvoice) return printDanfe(fromServerDanfe(await salesApi.danfe(id, serverInvoice.id)), target);
    });
  };
  const receipt = () => void task("receipt", () => printReceipt(saleReceipt(sale!, boot, operator)));

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
      <header className="flex flex-wrap items-center gap-2.5">
        <IconButton icon="pi pi-arrow-left" label="Voltar para os pedidos" onClick={onBack} />
        <div className="min-w-0 flex-1">
          <h2 className="panel-title">Pedido {sale?.number ?? "…"}</h2>
          {sale && (
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Tag tone={OVERALL_TONE[sale.overall_status]}>{OVERALL_STATUS[sale.overall_status] ?? sale.status}</Tag>
              <Tag tone={sale.payment_status === "paid" ? "success" : sale.payment_status === "pending" ? "warning" : "neutral"}>{PAYMENT_STATUS[sale.payment_status] ?? sale.payment_status}</Tag>
              {sale.shipping_address && <Tag tone="info">{FULFILLMENT_STATUS[sale.fulfillment_status] ?? sale.fulfillment_status}</Tag>}
              {localInvoice ? <Tag tone={INVOICE_TONE[localInvoice.status]}>{localInvoice.document_model === "55" ? "NF-e" : "NFC-e"} {localInvoice.number} · {LOCAL_STATUS[localInvoice.status]}</Tag>
                : serverInvoice && <Tag tone={INVOICE_TONE[serverInvoice.status]}>{serverInvoice.label} · {serverInvoice.status_label}</Tag>}
              <span className="text-[12.5px] text-muted">aberto em {dateTime(sale.created_at)}{sale.parked_at && ` · guardado em ${dateTime(sale.parked_at)}`}</span>
            </div>
          )}
        </div>
      </header>

      {sale && (
        <div role="toolbar" aria-label="Ações do pedido" className="flex flex-wrap items-center gap-2">
          {sale.status === "draft" && (
            <Button icon="pi pi-play" loading={busy} onClick={() => onResume(id)}>{seller ? "Continuar editando" : "Retomar e cobrar"}</Button>
          )}
          {canEmit && <Button icon="pi pi-send" loading={working === "emit"} onClick={() => setModal("emit")}>Emitir nota</Button>}
          {hasInvoice && <>
            <Button variant="secondary" icon="pi pi-print" loading={working === "print"} onClick={() => printInvoice()}>Imprimir nota</Button>
            <Button variant="secondary" icon="pi pi-sliders-h" onClick={() => setModal("print-other")}>Nota em outra impressora</Button>
          </>}
          {sale.status !== "draft" && <Button variant="secondary" icon="pi pi-receipt" loading={working === "receipt"} onClick={receipt}>Recibo</Button>}
          {sale.status !== "cancelled" && <Button variant="ghost" icon="pi pi-map-marker" onClick={() => setModal("addresses")}>Endereços</Button>}
          {deliveryEditable && can(me, "sales.edit_delivery") && <Button variant="ghost" icon="pi pi-truck" onClick={() => setModal("delivery")}>Alterar entrega</Button>}
          {sale.status === "completed" && approved.length > 0 && can(me, "sales.edit_payment") && (
            <Button variant="ghost" icon="pi pi-credit-card" onClick={() => setModal("payment")}>Trocar pagamento</Button>
          )}
          {sale.status !== "cancelled" && sale.fulfillment_status !== "returned" && sale.status !== "open" && (
            <Button variant="ghost" icon="pi pi-times-circle" className="ml-auto text-danger-text" onClick={() => setModal("cancel")}>Cancelar pedido</Button>
          )}
        </div>
      )}

      {delivers && (
        <div role="group" aria-label="Entrega" className="flex flex-wrap items-center gap-2 rounded-[10px] border border-line bg-card px-3 py-2.5">
          <span className="mr-auto flex items-center gap-1.5 text-[13px] text-muted">
            <i className="pi pi-truck" /> Entrega: <b className="text-strong">{FULFILLMENT_STATUS[String(sale?.fulfillment_status)]}</b>
          </span>
          {canMove && NEXT.filter((n) => FULFILLMENT_FLOW.indexOf(n.to) > step).map((n) => (
            <Button key={n.to} size="sm" icon={n.icon} loading={moving} variant={n.to === "delivered" ? "success" : "secondary"}
              onClick={() => (n.to !== "delivered" || window.confirm("Confirmar que o pedido chegou no cliente? O status geral vira Concluído.")) && void move(n.to)}>{n.label}</Button>
          ))}
          {canMove && step > 0 && !backing && <Button size="sm" variant="ghost" icon="pi pi-undo" onClick={() => setBacking(true)}>Voltar etapa</Button>}
          {backing && (
            <form className="flex w-full items-center gap-1.5" onSubmit={(e) => {
              e.preventDefault();
              if (reason.trim()) void move(FULFILLMENT_FLOW[step - 1]!, reason);
            }}>
              <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Motivo (ex.: cliente não estava)" className="h-8 flex-1" />
              <Button type="submit" size="sm" disabled={!reason.trim()} loading={moving}>Voltar</Button>
              <Button size="sm" variant="ghost" onClick={() => setBacking(false)}>Cancelar</Button>
            </form>
          )}
        </div>
      )}

      {query.isPending ? <Spinner label="Carregando o pedido…" /> : query.isError || !sale ? (
        <p className="p-10 text-center text-muted">Não foi possível abrir o pedido.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
            <Stat icon="pi pi-wallet" label="Total" value={money(sale.total)} />
            <Stat icon="pi pi-check-circle" label="Pago" value={money(sale.paid_amount)} tone={Number(sale.balance_due) > 0 ? "danger" : undefined} />
            <Stat icon="pi pi-list" label="Itens" value={String(items.length)} />
            <Stat icon="pi pi-percentage" label="Descontos" value={money(Number(sale.discount) + Number(sale.coupon_discount))} />
          </div>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-3">
              <Card title="Itens">
                <ul>
                  {orderedItems(items).map((item) => (
                    <li key={item.id} className={cx("flex items-baseline gap-2.5 border-t border-line-subtle py-[7px] text-[13.5px] first:border-t-0", item.parent_item && "pl-[18px]")}>
                      <span className="min-w-[46px] font-bold text-strong">{quantity(item.quantity)}×</span>
                      <span className="min-w-0 flex-1 text-strong">{item.parent_item && "↳ "}{item.description}
                        <small className="block text-[12px] text-muted">{item.sku} · {money(item.unit_price)}{Number(item.discount) > 0 && ` · desconto ${money(item.discount)}`}</small></span>
                      <strong className="text-strong">{money(item.total)}</strong>
                    </li>
                  ))}
                  {cancelledItems.map((item) => (
                    <li key={item.id} className="flex items-baseline gap-2.5 border-t border-line-subtle py-[7px] text-[13px] text-muted line-through">
                      <span className="min-w-[46px]">{quantity(item.quantity)}×</span><span className="flex-1">{item.description}</span><span>{money(item.total)}</span>
                    </li>
                  ))}
                </ul>
              </Card>
              <Card title={`Pagamentos · ${PAYMENT_STATUS[sale.payment_status] ?? sale.payment_status}`}>
                {payments.length ? (
                  <table className="w-full text-[13px]">
                    <thead className="text-left text-[11px] text-muted uppercase"><tr><th className="py-1 pr-3">Forma</th><th className="px-3 py-1 text-right">Valor</th><th className="px-3 py-1 text-right">Troco</th><th className="px-3 py-1">NSU</th><th className="py-1 pl-3">Situação</th></tr></thead>
                    <tbody>
                      {payments.map((p) => (
                        <tr key={p.id} className="border-t border-line-subtle">
                          <td className="py-1.5 pr-3 text-strong">{p.method_name}{(p.installments ?? 1) > 1 && ` · ${p.installments}x`}</td>
                          <td className="px-3 py-1.5 text-right font-semibold text-strong">{money(p.amount)}</td>
                          <td className="px-3 py-1.5 text-right">{Number(p.change_amount) ? money(p.change_amount) : "—"}</td>
                          <td className="px-3 py-1.5">{p.nsu || "—"}</td>
                          <td className="py-1.5 pl-3"><Tag tone={p.status === "approved" || !p.status ? "success" : "neutral"}>{{ approved: "Aprovado", cancelled: "Cancelado", refunded: "Estornado", pending: "Aguardando" }[p.status ?? "approved"] ?? p.status}</Tag></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="text-muted">Nenhum pagamento.</p>}
              </Card>
              <InvoicesCard sale={sale} locals={locals.data ?? []} />
            </div>
            <div className="flex flex-col gap-3">
              <Card title="Cliente">
                <p className="text-strong">{sale.customer_name || "Consumidor"}</p>
                {sale.customer_document && <p className="text-muted">CPF/CNPJ {sale.customer_document}</p>}
                {sale.coupon_code && <p className="text-muted">Cupom {sale.coupon_code}</p>}
                <p className="mt-1 text-muted">Vendedor: {sale.seller_name || "—"}{sale.operator_name && ` · Operador: ${sale.operator_name}`}</p>
              </Card>
              {(delivery || sale.shipping_address_detail) && (
                <Card title="Entrega">
                  {delivery && <p className="text-strong">{delivery.table_name}{delivery.lead_days != null && ` · ${delivery.lead_days} dia(s) útil(eis)`}</p>}
                  <p className="text-muted">{delivery?.address_label}</p>
                  {sale.shipping_address_detail?.reference && <p className="text-muted">Ref.: {sale.shipping_address_detail.reference}</p>}
                  <p className="text-muted">Frete: {money(sale.freight)}</p>
                </Card>
              )}
              <Card title="Valores">
                <dl className="flex flex-col gap-1">
                  <Money label="Subtotal" value={sale.subtotal} />
                  {Number(sale.discount) > 0 && <Money label="Desconto" value={sale.discount} minus />}
                  {sale.coupon_code && <Money label={`Cupom ${sale.coupon_code}`} value={sale.coupon_discount} minus />}
                  {Number(sale.freight) > 0 && <Money label="Frete" value={sale.freight} />}
                  <div className="mt-1 flex justify-between border-t border-line-subtle pt-1.5 text-[15px] font-extrabold text-strong">
                    <dt>Total</dt><dd>{money(sale.total)}</dd>
                  </div>
                  <Money label="Pago" value={sale.paid_amount} />
                  {Number(sale.change_amount) > 0 && <Money label="Troco" value={sale.change_amount} />}
                  {Number(sale.balance_due) > 0 && <Money label="Falta pagar" value={sale.balance_due} minus />}
                  {Number(sale.refunded_amount) > 0 && <Money label="Estornado" value={sale.refunded_amount ?? "0"} minus />}
                </dl>
              </Card>
              <Card title="Histórico">
                <Line label="Aberto em" value={dateTime(sale.created_at)} />
                {sale.completed_at && <Line label="Concluído no caixa" value={dateTime(sale.completed_at)} />}
                {sale.ready_at && <Line label="Separado em" value={dateTime(sale.ready_at)} />}
                {sale.shipped_at && <Line label="Saiu para entrega" value={dateTime(sale.shipped_at)} />}
                {sale.delivered_at && <Line label="Entregue em" value={dateTime(sale.delivered_at)} />}
              </Card>
              {sale.cancel_reason && <Card title="Motivo do cancelamento"><p className="text-danger-text">{sale.cancel_reason}</p></Card>}
              {sale.notes && <Card title="Anotações"><p className="whitespace-pre-wrap">{sale.notes}</p></Card>}
            </div>
          </div>
        </>
      )}

      {sale && modal === "addresses" && <AddressesDialog sale={sale} onClose={() => setModal(null)} onDone={() => void reload()} />}
      {sale && modal === "delivery" && <DeliveryEditDialog sale={sale} onClose={() => setModal(null)} onDone={() => void reload()} />}
      {sale && modal === "payment" && <PaymentChangeDialog sale={sale} onClose={() => setModal(null)} onDone={() => void reload()} />}
      {sale && modal === "cancel" && <CancelOrderDialog sale={sale} onClose={() => setModal(null)} onDone={() => void reload()} />}
      {sale && modal === "emit" && <EmitDialog sale={sale} onClose={() => setModal(null)} onEmit={emit} />}
      {modal === "print-other" && <PrinterPickDialog title="Imprimir a nota em outra impressora" onClose={() => setModal(null)} onPrint={(t) => printInvoice(t)} />}
    </section>
  );
}

function InvoicesCard({ sale, locals }: { sale: Sale; locals: LocalInvoice[] }) {
  const server = sale.invoices ?? [];
  if (!server.length && !locals.length) return null;
  const known = new Set(server.map((i) => `${i.document_model}:${i.series}:${i.number}`));
  const onlyHere = locals.filter((i) => !known.has(`${i.document_model}:${i.series}:${i.number}`) || !i.synced);
  return (
    <Card title="Nota fiscal">
      <ul className="flex flex-col">
        {server.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-2 border-t border-line-subtle py-1.5 text-[13px] first:border-0">
            <span className="font-semibold text-strong">{i.label}</span>
            <Tag tone={INVOICE_TONE[i.status]}>{i.status_label}</Tag>
            <span className="text-muted">{money(i.total)}</span>
            {i.environment === "2" && <Tag tone="warning">Homologação</Tag>}
            {i.access_key && <span className="w-full font-mono text-[11.5px] text-muted">{i.access_key.replace(/(\d{4})(?=\d)/g, "$1 ")}</span>}
            {i.protocol && <span className="text-[12px] text-muted">Protocolo {i.protocol}{i.authorized_at && ` · ${dateTime(i.authorized_at)}`}</span>}
          </li>
        ))}
        {onlyHere.map((i) => (
          <li key={i.key} className="flex flex-wrap items-center gap-2 border-t border-line-subtle py-1.5 text-[13px] first:border-0">
            <span className="font-semibold text-strong">{i.document_model === "55" ? "NF-e" : "NFC-e"} {i.number} · série {i.series}</span>
            <Tag tone={INVOICE_TONE[i.status]}>{LOCAL_STATUS[i.status]}</Tag>
            {!i.synced && <Tag tone="warning">só neste PC</Tag>}
            {i.message && <span className="w-full text-[12px] text-muted">{i.message}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

const Card = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="flex flex-col gap-1 rounded-[10px] border border-line bg-card px-3.5 py-2.5 text-[13.5px]">
    <span className="eyebrow mb-0.5">{title}</span>{children}
  </div>
);
const Stat = ({ icon, label, value, tone }: { icon: string; label: string; value: string; tone?: string }) => (
  <div className="flex items-center gap-3 rounded-[10px] border border-line bg-card px-3.5 py-2.5">
    <span className="grid size-9 place-items-center rounded-lg bg-brand-subtle text-brand-text"><i className={icon} /></span>
    <div><p className="text-[11.5px] font-semibold tracking-wide text-muted uppercase">{label}</p>
      <p className={cx("text-[16px] font-extrabold", tone === "danger" ? "text-danger-text" : "text-strong")}>{value}</p></div>
  </div>
);
const Line = ({ label, value }: { label: string; value: string }) => (
  <div className="flex justify-between gap-3"><span className="text-muted">{label}</span><span className="text-strong">{value}</span></div>
);
const Money = ({ label, value, minus }: { label: string; value: string; minus?: boolean }) => (
  <div className="flex justify-between">
    <dt className="text-muted">{label}</dt>
    <dd className={minus ? "font-semibold text-danger-text" : "font-semibold text-strong"}>{minus ? "− " : ""}{money(value)}</dd>
  </div>
);
