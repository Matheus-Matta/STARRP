/**
 * Os documentos impressos da retaguarda (`frontend/src/print/docs/*.vue`) copiados para o app: mesmos dados (mesmas
 * rotas da API), mesmas colunas, textos, totais, assinaturas e papéis (`formats`). Cada um devolve o que o
 * `PrintShell` precisa e o corpo da folha; `print/index.ts` monta a folha e gera o PDF ou imprime.
 *
 *   turno · venda · danfe · estoque · separacao · conta · titulo · dre · lista · relatorio
 */
import { findResource } from "@front/resources";
import { findReport } from "@front/reports/catalog";
import { formatDocument } from "@front/utils/documents";
import { date, dateTime, money, percent, quantity } from "@front/utils/format";
import { applyMask, formatPhone, MASKS } from "@front/utils/masks";

import { api, type Page } from "@/api/client";
import type { FieldDef } from "@/shared/types";
import { cellText, compositeTable, fieldText, recordTitle, stripHtml, TABLE_TYPES } from "@/shared/values";

import { barsChart, CHART_CSS, fmt, type Format, heatmapChart, lineChart, waterfallChart } from "./charts";
import { esc, type PCol, type PrintFormat, printMeta, printTable, section, signatures } from "./shell";

type Any = Record<string, any>;
type Query = Record<string, string>;

export type DocContext = { storeName: string; query: Query };
export type LoadedDoc = {
  title: string; subtitle?: string; filename: string; formats: PrintFormat[]; format: PrintFormat; bare?: boolean;
  storeId?: string | null; css?: string; body: (thermal: boolean) => string;
};
type Loader = (id: string, ctx: DocContext) => Promise<LoadedDoc>;

const pick = (query: Query, formats: PrintFormat[], fallback: PrintFormat): PrintFormat => {
  const asked = query.formato as PrintFormat | undefined;
  return asked && formats.includes(asked) ? asked : fallback;
};
const slugify = (text: string) => text.toLowerCase().replace(/[^a-z0-9à-ú]+/gi, "-");
const sum = (rows: Any[], key: string, digits = 2) => rows.reduce((t, r) => t + Number(r[key] ?? 0), 0).toFixed(digits);

/* ── venda (SalePrint) ─────────────────────────────────────────────────── */
const SALE_STATUS: Record<string, string> = { open: "Aberta", draft: "Pedido guardado", completed: "Concluída", cancelled: "Cancelada" };
const venda: Loader = async (id, { query }) => {
  const sale = await api.get<Any>(`/sales/${id}/`);
  const active = (sale.items ?? []).filter((i: Any) => i.status === "active");
  const ids = new Set(active.map((i: Any) => i.id));
  const items = active.filter((i: Any) => !i.parent_item || !ids.has(i.parent_item)).flatMap((item: Any) => [
    item, ...active.filter((s: Any) => s.parent_item === item.id).map((s: Any) => ({ ...s, description: `↳ ${s.description} (serviço)` })),
  ]);
  const payments = (sale.payments ?? []).filter((p: Any) => p.status === "approved");
  const columns: PCol[] = [
    { key: "description", label: "Produto" }, { key: "sku", label: "Código" }, { key: "quantity", label: "Qtd.", type: "quantity" },
    { key: "unit_price", label: "Preço", type: "money" }, { key: "discount", label: "Desc.", type: "money" },
    { key: "total", label: "Total", type: "money" },
  ];
  const formats: PrintFormat[] = ["a4", "80mm"];
  return {
    title: `Venda ${sale.number ?? ""}`, formats, format: pick(query, formats, "a4"), storeId: sale.store,
    filename: `venda-${sale.number ?? id}`,
    subtitle: `${SALE_STATUS[sale.status] ?? sale.status} · ${dateTime(sale.completed_at ?? sale.created_at)}`,
    css: `.receipt { list-style: none; margin: 0; padding: 0; border-top: 1px dashed #111; }
      .receipt li { padding: 3px 0; border-bottom: 1px dotted #999; } .receipt__name { font-weight: 700; }
      .receipt__line { display: flex; justify-content: space-between; font-size: 8pt; }
      .pay { display: flex; justify-content: space-between; padding: 2px 0; font-size: 9pt; } .center { text-align: center; }
      .cancelled { margin: 0; padding: 6px; border: 2px solid #b91c1c; color: #b91c1c; font-weight: 700; text-align: center; }`,
    body: (thermal) => [
      printMeta([["Cliente", sale.customer_name || "Consumidor"], ["CPF/CNPJ", sale.customer_document], ["Vendedor", sale.seller_name]], 3),
      thermal
        ? `<ul class="receipt">${items.map((item: Any) => `<li><div class="receipt__name">${esc(item.description)}</div>
            <div class="receipt__line"><span>${esc(quantity(item.quantity))} ${esc(String(item.unit).toLowerCase())} × ${esc(money(item.unit_price))}</span>
            <b>${esc(money(item.total))}</b></div></li>`).join("")}</ul>`
        : printTable(columns, items),
      `<div class="doc-total-box"><div><span>Subtotal</span><span>${esc(money(sale.subtotal))}</span></div>${
        Number(sale.discount) ? `<div><span>Desconto</span><span>− ${esc(money(sale.discount))}</span></div>` : ""}${
        Number(sale.coupon_discount) ? `<div><span>Cupom ${esc(sale.coupon_code)}</span><span>− ${esc(money(sale.coupon_discount))}</span></div>` : ""}${
        Number(sale.freight) ? `<div><span>Frete</span><span>${esc(money(sale.freight))}</span></div>` : ""}
        <div><span>Total</span><span>${esc(money(sale.total))}</span></div></div>`,
      section("Pagamento", payments.map((p: Any) => `<div class="pay"><span>${esc(p.method_name)}${p.installments > 1 ? ` (${p.installments}x)` : ""}</span>
        <span>${esc(money(p.amount))}</span></div>`).join("")
        + (Number(sale.change_amount) ? `<div class="pay"><span>Troco</span><b>${esc(money(sale.change_amount))}</b></div>` : "")
        + (payments.length ? "" : `<p class="doc-note">Sem pagamento registrado.</p>`)),
      `<p class="doc-note center">Comprovante sem valor fiscal. Obrigado pela preferência!</p>`,
      sale.status === "cancelled" ? `<p class="cancelled">VENDA CANCELADA${sale.cancel_reason ? ` — ${esc(sale.cancel_reason)}` : ""}</p>` : "",
    ].join(""),
  };
};

/* ── estoque (StockDocumentPrint) ──────────────────────────────────────── */
const DOC_KIND: Record<string, string> = { entry: "Entrada", exit: "Saída", transfer: "Transferência", adjustment: "Ajuste",
  inventory: "Inventário", supplier_return: "Devolução ao fornecedor", relocation: "Mudança de endereço" };
const DOC_STATUS: Record<string, string> = { draft: "Rascunho", posted: "Confirmado", cancelled: "Cancelado" };
const EXIT_REASON: Record<string, string> = { consumption: "Consumo interno", loss: "Perda / avaria", expiration: "Vencimento" };
const estoque: Loader = async (id) => {
  const doc = await api.get<Any>(`/stock/documents/${id}/`);
  const entry = doc.kind === "entry";
  const inventory = doc.kind === "inventory";
  const rows = (doc.items ?? []).map((i: Any) => ({
    ...i, total: (Number(i.quantity) * Number(i.unit_cost ?? 0)).toFixed(2),
    lot: [i.lot_number, i.expires_at ? `val. ${date(i.expires_at)}` : ""].filter(Boolean).join(" · "),
    difference: i.expected_quantity == null ? null : (Number(i.quantity) - Number(i.expected_quantity)).toFixed(3),
  }));
  const columns: PCol[] = [
    { key: "variant_name", label: "Produto" }, { key: "sku", label: "SKU" },
    ...(inventory ? [{ key: "expected_quantity", label: "Sistema", type: "quantity" }] : []),
    { key: "quantity", label: inventory ? "Contado" : "Qtd.", type: "quantity" },
    ...(inventory ? [{ key: "difference", label: "Diferença", type: "quantity" }] : []),
    ...(entry ? [{ key: "unit_cost", label: "Custo unit.", type: "money" }, { key: "total", label: "Total", type: "money" },
                 { key: "lot", label: "Lote / validade" }] : []),
  ];
  const totals = { variant_name: `${rows.length} itens`, quantity: sum(rows, "quantity", 3), ...(entry ? { total: sum(rows, "total") } : {}) };
  const kind = DOC_KIND[doc.kind] ?? "Documento";
  return {
    title: `${kind} nº ${doc.number ?? ""}`, formats: ["a4"], format: "a4", storeId: doc.store,
    filename: `estoque-${kind.toLowerCase()}-${doc.number ?? id}`, subtitle: `${DOC_STATUS[doc.status]} · ${date(doc.effective_date)}`,
    body: () => [
      printMeta([
        ["Depósito", doc.warehouse_name],
        doc.kind === "transfer" ? ["Destino", doc.destination_name] : ["Fornecedor", doc.supplier_name],
        ["Nota / documento", doc.external_number], ["Data", date(doc.effective_date)],
        ["Confirmado em", doc.posted_at ? dateTime(doc.posted_at) : "Rascunho"],
        doc.kind === "exit" ? ["Motivo da saída", EXIT_REASON[doc.exit_reason]] : ["Situação", DOC_STATUS[doc.status]],
      ], 3),
      doc.reason ? `<p class="doc-note"><b>Observação:</b> ${esc(doc.reason)}</p>` : "",
      section("Itens", printTable(columns, rows, { totals })),
      signatures([entry ? "Recebido por" : "Separado por", "Conferido por", "Responsável"]),
    ].join(""),
  };
};

/* ── titulo (TitlePrint) ───────────────────────────────────────────────── */
const TITLE_STATUS: Record<string, string> = { open: "Em aberto", partial: "Parcial", paid: "Pago", cancelled: "Cancelado" };
const TITLE_KIND: Record<string, string> = { receivable: "A receber", payable: "A pagar" };
const titulo: Loader = async (id) => {
  const t = await api.get<Any>(`/finance/titles/${id}/`);
  const rows = (t.installments ?? []).map((i: Any) => ({ ...i, balance: (Number(i.amount) - Number(i.paid_amount)).toFixed(2) }));
  const columns: PCol[] = [
    { key: "number", label: "Parcela" }, { key: "due_date", label: "Vencimento", type: "date" },
    { key: "amount", label: "Valor", type: "money" }, { key: "paid_amount", label: "Pago", type: "money" },
    { key: "paid_at", label: "Pago em", type: "date" }, { key: "balance", label: "Saldo", type: "money" },
    { key: "status", label: "Situação", type: "tag", map: TITLE_STATUS },
  ];
  return {
    title: `Conta ${TITLE_KIND[t.kind]?.toLowerCase() ?? ""}`, formats: ["a4"], format: "a4", storeId: t.store, subtitle: t.description,
    filename: `${t.kind === "receivable" ? "receber" : "pagar"}-${slugify(String(t.document_number || t.description || id))}`,
    body: () => [
      printMeta([
        [t.kind === "receivable" ? "Cliente" : "Fornecedor", t.customer_name ?? t.supplier_name],
        ["Documento", t.document_number], ["Categoria", t.category_name],
        ["Emissão", date(t.issue_date)], ["Valor total", money(t.total)], ["Situação", TITLE_STATUS[t.status]],
      ], 3),
      t.notes ? `<p class="doc-note"><b>Observações:</b> ${esc(t.notes)}</p>` : "",
      section("Parcelas", printTable(columns, rows, { totals: { number: "Total", amount: sum(rows, "amount"),
                                                               paid_amount: sum(rows, "paid_amount"), balance: sum(rows, "balance") } })),
      signatures(["Responsável", t.kind === "receivable" ? "Cliente" : "Fornecedor"]),
    ].join(""),
  };
};

/* ── separacao (PickingPrint) ──────────────────────────────────────────── */
const separacao: Loader = async (id, { query }) => {
  const p = await api.get<Any>(`/stock/documents/${id}/picking-list/`);
  const rows = (p.lines ?? []).map((l: Any) => ({ ...l, check: "☐", bin: l.bin || "—" }));
  const columns: PCol[] = [
    { key: "check", label: "✔" }, { key: "bin", label: "Endereço" }, { key: "description", label: "Produto" },
    { key: "sku", label: "SKU" }, { key: "lot", label: "Lote" }, { key: "quantity", label: "Qtd.", type: "quantity" },
  ];
  const boxColumns: PCol[] = [
    { key: "description", label: "Produto" }, { key: "label", label: "Caixa" }, { key: "contents", label: "Conteúdo" },
    { key: "barcode", label: "Código" }, { key: "quantity", label: "Qtd." },
  ];
  const formats: PrintFormat[] = ["a4", "80mm"];
  return {
    title: `Lista de separação nº ${p.document ?? ""}`, formats, format: pick(query, formats, "a4"),
    filename: `separacao-${p.document ?? id}`, subtitle: p.warehouse,
    css: ".short { margin: 0; padding-left: 16px; color: #b91c1c; font-size: 9pt; }",
    body: (thermal) => [
      section("Pegar (na ordem do caminho)", printTable(columns, rows, { thermal })),
      (p.shortages ?? []).length ? section("Faltas", `<ul class="short">${p.shortages.map((s: Any) =>
        `<li>${esc(s.description)}: faltam ${esc(quantity(s.missing_quantity))}</li>`).join("")}</ul>`) : "",
      section("Carga", `<p class="doc-note">${esc(p.load.box_count)} caixas · ${esc(quantity(p.load.gross_weight))} kg · ${
        esc(Number(p.load.cubic_meters).toLocaleString("pt-BR"))} m³</p>${
        (p.load.boxes ?? []).some((b: Any) => b.label) ? printTable(boxColumns, p.load.boxes, { thermal }) : ""}`),
      signatures(["Separado por", "Conferido por"]),
    ].join(""),
  };
};

/* ── conta (AccountStatementPrint) ─────────────────────────────────────── */
/** AAAA-MM-DD do dia local (sem `toLocaleDateString("sv-SE")`, que nem todo Android tem). */
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const conta: Loader = async (id, { query }) => {
  const from = query.de ?? isoDay(new Date(Date.now() - 29 * 86_400_000));
  const to = query.ate ?? isoDay(new Date());
  const s = await api.get<Any>(`/finance/accounts/${id}/statement/`, { date_from: from, date_to: to });
  const rows = (s.lines ?? []).map((l: Any) => ({ ...l, inflow: l.kind === "in" ? l.amount : null, outflow: l.kind === "out" ? l.amount : null }));
  const columns: PCol[] = [
    { key: "date", label: "Data", type: "date" }, { key: "description", label: "Descrição" }, { key: "category", label: "Categoria" },
    { key: "inflow", label: "Entrada", type: "money" }, { key: "outflow", label: "Saída", type: "money" },
    { key: "balance", label: "Saldo", type: "money" },
  ];
  const formats: PrintFormat[] = ["a4", "a4-landscape"];
  return {
    title: "Extrato da conta", formats, format: pick(query, formats, "a4"),
    filename: `extrato-${s.account ?? "conta"}-${from}-a-${to}`, subtitle: `${s.account} · ${date(from)} a ${date(to)}`,
    body: () => [
      printMeta([["Saldo anterior", money(s.opening_balance)], ["Entradas", money(sum(rows, "inflow"))],
                 ["Saídas", money(sum(rows, "outflow"))], ["Saldo final", money(s.closing_balance)]], 4),
      printTable(columns, rows, { empty: "Nenhum lançamento no período.",
                                  totals: { description: "Totais do período", inflow: sum(rows, "inflow"), outflow: sum(rows, "outflow"),
                                            balance: s.closing_balance } }),
    ].join(""),
  };
};

/* ── turno (CashShiftPrint) ────────────────────────────────────────────── */
const SHIFT_STATUS: Record<string, string> = { open: "Aberto", pending_opening: "Abertura aguardando gerente",
  pending_approval: "Aguardando gerente", closed: "Fechado", cancelled: "Cancelado" };
const DRAWER: [string, string][] = [
  ["opening", "Troco inicial"], ["sale", "Vendas em dinheiro"], ["supply", "Suprimentos"], ["withdrawal", "Sangrias"],
  ["refund", "Devoluções"], ["expected", "Esperado"], ["counted", "Contado"], ["difference", "Diferença"],
];
const turno: Loader = async (id, { query }) => {
  const s = await api.get<Any>(`/cash/sessions/${id}/statement/`);
  const drawerRows = DRAWER.filter(([key]) => key in (s.drawer ?? {})).map(([key, label]) => ({ label, value: s.drawer[key] ?? null }));
  const payColumns: PCol[] = [{ key: "method__name", label: "Forma" }, { key: "count", label: "Qtd." }, { key: "total", label: "Total", type: "money" }];
  const saleColumns: PCol[] = [
    { key: "number", label: "Nº" }, { key: "completed_at", label: "Hora", type: "datetime" }, { key: "customer", label: "Cliente" },
    { key: "seller", label: "Vendedor" }, { key: "payments", label: "Pagamentos" }, { key: "discount", label: "Desc.", type: "money" },
    { key: "total", label: "Total", type: "money" }, { key: "status_label", label: "Situação" },
  ];
  const movementColumns: PCol[] = [
    { key: "created_at", label: "Quando", type: "datetime" }, { key: "kind_label", label: "Tipo" },
    { key: "amount", label: "Valor", type: "money" }, { key: "status_label", label: "Situação" },
    { key: "reason", label: "Motivo" }, { key: "operator", label: "Operador" },
  ];
  const costs = s.sales?.cost != null;
  const itemColumns: PCol[] = [
    { key: "description", label: "Produto" }, { key: "sku", label: "SKU" }, { key: "quantity", label: "Qtd.", type: "quantity" },
    // Custo e margem só vêm para quem tem `catalog.view_costs` (o operador fecha o turno sem eles).
    ...(costs ? [{ key: "cost", label: "Custo", type: "money" as const }, { key: "margin", label: "Margem", type: "money" as const }] : []),
  ];
  const formats: PrintFormat[] = ["a4", "80mm"];
  return {
    title: "Fechamento de caixa", formats, format: pick(query, formats, "a4"),
    filename: `fechamento-${s.session.register ?? "caixa"}-${String(s.session.opened_at ?? "").slice(0, 10)}`,
    subtitle: `${s.session.register} · ${dateTime(s.session.opened_at)}`,
    css: `.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; } .cols--one { grid-template-columns: 1fr; }
      .drawer tr.strong td { font-weight: 700; background: #f3f4f6; } .issues { margin: 0; padding-left: 16px; font-size: 8.5pt; }`,
    body: (thermal) => [
      printMeta([
        ["Caixa / terminal", `${s.session.register} · ${s.session.terminal || "—"}`],
        ["Situação", SHIFT_STATUS[s.session.status] ?? s.session.status], ["Aprovado por", s.session.approved_by],
        ["Abertura", `${dateTime(s.session.opened_at)} · ${s.session.opened_by}`],
        ["Fechamento", s.session.closed_at ? `${dateTime(s.session.closed_at)} · ${s.session.closed_by}` : "Em aberto"],
        ["Vendas", `${s.sales.count} · ticket ${money(s.sales.average_ticket)}`],
      ], 3),
      `<div class="doc-kpis"><div><small>Vendido</small><b>${esc(money(s.sales.total))}</b></div>
        ${costs ? `<div><small>Custo</small><b>${esc(money(s.sales.cost))}</b></div>
        <div><small>Margem bruta</small><b>${esc(money(s.sales.gross_margin))}</b></div>` : ""}
        <div><small>Cancelado</small><b>${esc(s.sales.cancelled_count)} · ${esc(money(s.sales.cancelled_total))}</b></div></div>`,
      `<div class="cols${thermal ? " cols--one" : ""}">${
        section("Formas de pagamento", printTable(payColumns, s.by_payment_method ?? [], { thermal, empty: "Nenhum pagamento.",
          totals: { method__name: "Total", total: sum(s.by_payment_method ?? [], "total") } }))}${
        section("Gaveta (dinheiro)", `<table class="pt drawer"><tbody>${drawerRows.map((row) => `<tr class="${
          ["Esperado", "Diferença"].includes(row.label) ? "strong" : ""}"><td>${esc(row.label)}</td><td class="r${
          row.label === "Diferença" && Number(row.value) < 0 ? " neg" : ""}">${row.value == null ? "—" : esc(money(row.value))}</td></tr>`).join("")}</tbody></table>`)}</div>`,
      (s.occurrences ?? []).length ? section("Ocorrências", `<ul class="issues">${s.occurrences.map((o: Any) =>
        `<li><b>${esc(o.kind)}:</b> ${esc(o.text)}</li>`).join("")}</ul>`) : "",
      thermal ? "" : [
        section(`Vendas do turno (${(s.sales_list ?? []).length})`, printTable(saleColumns, s.sales_list ?? [])),
        section("Movimentos da gaveta", printTable(movementColumns, s.movements ?? [], { empty: "Nenhum movimento." })),
        section("Itens vendidos", printTable(itemColumns, s.items ?? [], { totals: { description: "Total", total: sum(s.items ?? [], "total"),
          ...(costs ? { cost: sum(s.items ?? [], "cost"), margin: sum(s.items ?? [], "margin") } : {}) } })),
      ].join(""),
      signatures(["Operador do caixa", "Gerente / conferente"]),
    ].join(""),
  };
};

/* ── dre (DrePrint) ────────────────────────────────────────────────────── */
const dre: Loader = async (_id, { query }) => {
  const from = query.de ?? isoDay(new Date(Date.now() - 29 * 86_400_000));
  const to = query.ate ?? isoDay(new Date());
  const x = await api.get<Any>("/reports/dre/", { date_from: from, date_to: to });
  const net = Number(x.net_revenue ?? 0);
  const pct = (v: unknown) => (net ? percent(((Number(v) / net) * 100).toFixed(2)) : "—");
  const lines: { label: string; value: string; sign?: string; total?: boolean; indent?: boolean }[] = [
    { label: "Receita bruta de vendas", value: x.gross_revenue },
    { label: "Frete cobrado", value: x.freight, sign: "+" },
    { label: "Descontos concedidos", value: x.discounts, sign: "−" },
    { label: "Devoluções", value: x.returns, sign: "−" },
    ...(x.other_revenue ?? []).map((e: Any) => ({ label: `Serviços: ${e.category}`, value: e.amount, sign: "+", indent: true })),
    { label: "Receita líquida", value: x.net_revenue, total: true },
    { label: "Custo das mercadorias vendidas (CMV)", value: x.cmv, sign: "−" },
    { label: "Lucro bruto", value: x.gross_profit, total: true },
    { label: "Taxas de cartão", value: x.card_fees, sign: "−" },
    { label: "Comissões", value: x.commissions, sign: "−" },
    { label: "Diferenças de caixa", value: x.cash_differences, sign: "±" },
    ...(x.expenses ?? []).map((e: Any) => ({ label: e.category, value: e.amount, sign: "−", indent: true })),
    { label: "Resultado operacional", value: x.operating_result, total: true },
  ];
  return {
    title: "DRE — Demonstração do resultado", formats: ["a4"], format: "a4", filename: `dre-${from}-a-${to}`,
    subtitle: `Período de ${date(from)} a ${date(to)}`,
    css: `.dre { font-size: 10pt; } .dre td { padding: 6px 8px; }
      .dre tr.total td { font-weight: 700; background: #f3f4f6; border-top: 1.5px solid #111; }
      .dre tr.indent td:first-child { padding-left: 24px; color: #444; } .dre tr:last-child td { font-size: 11.5pt; }`,
    body: () => `<table class="pt dre"><thead><tr><th>Conta</th><th class="r">Valor</th><th class="r">% receita líquida</th></tr></thead>
      <tbody>${lines.map((l) => `<tr class="${[l.total && "total", l.indent && "indent"].filter(Boolean).join(" ")}">
        <td>${l.sign ? `(${l.sign}) ` : ""}${esc(l.label)}</td>
        <td class="r${l.total && Number(l.value) < 0 ? " neg" : ""}">${esc(money(l.value))}</td><td class="r">${esc(pct(l.value))}</td></tr>`).join("")}
      </tbody></table>
      <p class="doc-note">Regime de competência: vendas pela data de conclusão; despesas pela data de emissão do título.</p>`,
  };
};

/* ── lista (ListPrint) ─────────────────────────────────────────────────── */
const RESERVED = new Set(["auto", "view", "registro", "titulo", "formato"]);
const NAMES: Record<string, string> = { search: "busca", ordering: "ordem" };
const lista: Loader = async (name, { query }) => {
  const resource = findResource(name);
  const view = resource?.views?.find((v) => v.name === query.view);
  const filters = Object.fromEntries(Object.entries(query).filter(([k, v]) => !RESERVED.has(k) && v !== ""));
  const endpoint = view?.list?.endpoint ?? resource?.endpoint ?? "";
  const columns = (view?.list?.columns ?? resource?.columns ?? []) as unknown as (PCol & { total?: boolean })[];
  const fixed = view?.list ? view.list.params(String(query.registro), {}) : { ...resource?.params };
  const rows: Any[] = [];
  for (let page = 1; endpoint && rows.length < 2000; page++) {
    const chunk = await api.get<Page<Any>>(endpoint, { ...fixed, ...filters, page, page_size: 200 } as never);
    rows.push(...chunk.results);
    if (!chunk.next) break;
  }
  const title = query.titulo ?? (view ? `${resource?.title} · ${view.label}` : resource?.title ?? "Lista");
  const used = Object.entries(filters).filter(([k]) => k !== "ordering");
  const text = used.map(([k, v]) => `${NAMES[k] ?? k.replace(/__/g, " ").replace(/_/g, " ")}: ${v}`).join(" · ");
  const sums = columns.filter((c) => c.total);
  const totals = sums.length && rows.length ? Object.fromEntries([[columns[0]!.key, "Total"], ...sums.map((c) => [c.key,
    rows.reduce((t, r) => t + Number(r[c.key] ?? 0), 0).toFixed(c.type === "money" ? 2 : 3)])]) : undefined;
  const formats: PrintFormat[] = ["a4", "a4-landscape"];
  return {
    title, formats, format: pick(query, formats, columns.length > 5 ? "a4-landscape" : "a4"), filename: slugify(title),
    subtitle: `${rows.length} registro(s)${text ? ` · ${text}` : ""}${rows.length >= 2000 ? " · limitado a 2.000" : ""}`,
    body: () => (resource ? printTable(columns, rows, { totals }) : `<p class="doc-note">Lista desconhecida.</p>`),
  };
};

/* ── relatorio (ReportBookPrint) ───────────────────────────────────────── */
const deltaText = (d: unknown, good?: string) => {
  if (d === null || d === undefined) return "";
  const n = Number(d);
  const better = (n > 0 && good !== "down") || (n < 0 && good === "down");
  return `${n > 0 ? "▲" : n < 0 ? "▼" : "="} ${Math.abs(n).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% ${n === 0 ? "" : better ? "(melhor)" : "(pior)"} vs. anterior`;
};
const relatorio: Loader = async (slug, { query, storeName }) => {
  const def = findReport(slug);
  const params = Object.fromEntries(Object.entries(query).filter(([k, v]) => v && !["formato", "auto", "sobre"].includes(k)));
  const report = await api.get<Any>(`/reports/book/${slug}/`, params);
  const f = (v: unknown) => (v ?? "number") as Format;
  const filters = (report.filters ?? []).filter((flt: Any) => params[flt.name]).map((flt: Any) =>
    `${flt.label}: ${flt.options.find((o: Any) => String(o.value) === params[flt.name])?.label ?? params[flt.name]}`);
  const scope = slug === "filiais" ? "Todas as filiais que você acessa" : storeName;
  const isChart = (b: Any) => ["line", "bars", "heatmap", "waterfall"].includes(b.type);
  const numeric = (c: { format?: string }) => ["money", "number", "decimal", "quantity", "percent"].includes(c.format ?? "");
  const asRows = (b: Any) => {
    const rows = (b.rows ?? []) as Any[];
    const total = rows.reduce((t, r) => t + Number(r.value || 0), 0);
    const max = Math.max(1, ...rows.map((r) => Math.abs(Number(r.value || 0))));
    return rows.map((r, i): Any => ({ ...r, pos: i + 1, pct: total ? (Number(r.value) / total) * 100 : 0,
                                 bar: (Math.abs(Number(r.value || 0)) / max) * 100 }));
  };
  const blockBody = (b: Any) => {
    if (b.type === "line") return lineChart(b.x ?? [], b.series ?? [], f(b.format), b.zero !== false, b.grain);
    if (b.type === "bars") return barsChart(b.x ?? [], b.series ?? [], f(b.format), Boolean(b.stacked), b.grain);
    if (b.type === "heatmap") return heatmapChart(b.rows ?? [], b.cols ?? [], b.values ?? [], f(b.format));
    if (b.type === "waterfall") return waterfallChart(b.steps ?? [], f(b.format));
    if (b.type === "compare") {
      const metrics = (b.metrics ?? []) as Any[];
      return `<table class="pt rp-table"><thead><tr><th></th>${metrics.map((m) => `<th class="r">${esc(m.label)}${
        m.good ? `<small>${m.good === "up" ? "maior é melhor" : "menor é melhor"}</small>` : ""}</th>`).join("")}</tr></thead>
        <tbody>${(b.rows ?? []).map((r: Any) => `<tr><td><b>${esc(r.label)}</b></td>${metrics.map((m) =>
          `<td class="r">${esc(r[m.key] === null || r[m.key] === undefined || r[m.key] === "" ? "—" : fmt(r[m.key], m.format ?? "number"))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    }
    if (b.type === "insights") {
      const items = (b.items ?? []) as Any[];
      return items.length ? `<ul class="ins">${items.map((i) => `<li class="ins--${esc(i.tone)}">${
        i.tone === "good" ? "✔" : i.tone === "bad" ? "⚠" : "ℹ"} ${esc(i.text)}</li>`).join("")}</ul>`
        : `<p class="rp-empty">Sem conclusões no período (faltam dados nos dois lados do cruzamento).</p>`;
    }
    if ((b.type === "ranking" || b.type === "table") && !(b.rows ?? []).length) return `<p class="rp-empty">${esc(b.empty ?? "Sem dados no período.")}</p>`;
    if (b.type === "ranking" || b.type === "share") {
      return `<table class="pt rp-rank"><thead><tr>${b.type === "ranking" ? "<th>#</th>" : ""}<th>Item</th><th class="r">Valor</th>${
        b.type === "share" ? '<th class="r">%</th>' : ""}<th></th></tr></thead><tbody>${asRows(b).map((r) => `<tr>${
        b.type === "ranking" ? `<td class="n">${r.pos}</td>` : ""}<td>${esc(r.label)}${r.sub || r.group ? `<small> · ${
        esc([r.group, r.sub].filter(Boolean).join(" · "))}</small>` : ""}</td><td class="r">${esc(fmt(r.value, f(b.format)))}</td>${
        b.type === "share" ? `<td class="r">${esc(`${r.pct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`)}</td>` : ""}<td class="bar"><i style="width:${r.bar}%"></i></td></tr>`).join("")}</tbody></table>`;
    }
    if (b.type === "table") {
      const cols = (b.columns ?? []) as Any[];
      return `<table class="pt rp-table"><thead><tr>${cols.map((c) => `<th${numeric(c) ? ' class="r"' : ""}>${esc(c.label)}</th>`).join("")}</tr></thead>
        <tbody>${(b.rows ?? []).map((row: Any) => `<tr class="${row.strong ? "strong" : ""}">${cols.map((c) =>
          `<td${numeric(c) ? ' class="r"' : ""}>${esc(fmt(row[c.key], f(c.format ?? "text")))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    }
    return "";
  };
  const formats: PrintFormat[] = ["a4", "a4-landscape"];
  return {
    title: report.title ?? def?.title ?? "Relatório", formats, format: pick(query, formats, "a4"),
    filename: `${slug}-${report.period?.from ?? ""}-a-${report.period?.to ?? ""}`,
    subtitle: `${date(report.period?.from)} a ${date(report.period?.to)} · ${scope}`,
    css: `${CHART_CSS}
      .rp-filters { margin: 0; font-size: 9pt; color: #333; }
      .rp-about { margin: 0; padding: 6px 8px; border-left: 3px solid #2a78d6; background: #f3f6fb; font-size: 9pt; }
      .rp-kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(42mm, 1fr)); gap: 6px; }
      .rp-kpis > div { border: 1px solid #bbb; border-radius: 4px; padding: 6px 8px; break-inside: avoid; }
      .rp-kpis small { display: block; font-size: 7.5pt; color: #555; text-transform: uppercase; letter-spacing: 0.03em; }
      .rp-kpis b { display: block; font-size: 12.5pt; } .rp-kpis span { display: block; font-size: 7.5pt; color: #333; }
      .rp-kpis em { display: block; font-size: 7.5pt; color: #666; font-style: normal; }
      .rp-block { break-inside: avoid; } .rp-desc { margin: -2px 0 6px; font-size: 8.5pt; color: #555; }
      .rp-empty { margin: 0; font-size: 9pt; color: #555; } .rp-rank { font-size: 9pt; } .rp-rank .n { width: 18px; color: #777; }
      .rp-rank small { color: #666; } .rp-rank .bar { width: 28%; }
      .rp-rank .bar i { display: block; height: 6px; border-radius: 0 3px 3px 0; background: #2a78d6; }
      .rp-table { font-size: 8.5pt; } .rp-table tr.strong td { font-weight: 700; background: #f3f4f6; }
      .rp-table th small { display: block; font-size: 6.5pt; text-transform: none; color: #777; font-weight: 400; }
      .ins { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 9pt; }
      .ins li { padding: 5px 8px; border: 1px solid #ddd; border-radius: 4px; } .ins--good { border-color: #86efac; }
      .ins--bad { border-color: #fca5a5; }`,
    body: () => [
      `<p class="rp-filters"><b>Filtros:</b> ${esc(filters.length ? filters.join(" · ") : "nenhum (tudo do período)")}</p>`,
      query.sobre === "1" && def?.about ? `<p class="rp-about"><b>Para que serve.</b> ${esc(def.about.purpose)}</p>` : "",
      `<div class="rp-kpis">${(report.kpis ?? []).map((k: Any) => `<div><small>${esc(k.label)}</small><b>${esc(fmt(k.value, f(k.format)))}</b>${
        k.delta !== null && k.delta !== undefined ? `<span>${esc(deltaText(k.delta, k.good))}</span>` : ""}${k.hint ? `<em>${esc(k.hint)}</em>` : ""}</div>`).join("")}</div>`,
      ...(report.blocks ?? []).map((b: Any) => `<section class="doc-section rp-block"><h2>${esc(b.title)}</h2>${
        b.description ? `<p class="rp-desc">${esc(b.description)}</p>` : ""}${isChart(b) ? `<div class="rp-chart">${blockBody(b)}</div>` : blockBody(b)}</section>`),
    ].join(""),
  };
};

/* ── danfe (DanfePrint) ────────────────────────────────────────────────── */
const DANFE_STATUS: Record<string, string> = { draft: "em rascunho", processing: "em processamento", rejected: "rejeitada",
                                               error: "com erro de comunicação" };
const danfe: Loader = async (id, { query }) => {
  const url = query.venda ? `/sales/${query.venda}/invoices/${id}/danfe/` : `/fiscal/invoices/${id}/danfe/`;
  const n = await api.get<Any>(url);
  const nfce = Boolean(n.nfce);
  const formats: PrintFormat[] = nfce ? ["80mm", "a4"] : ["a4"];
  const issuer = (n.issuer ?? {}) as Any;
  const dest = n.recipient as Any | null;
  const taxes = (n.tax_totals ?? {}) as Any;
  const transport = (n.transport ?? {}) as Any;
  const doc = (v: unknown) => (v ? formatDocument(String(v)) : "");
  const cep = (v: unknown) => (v ? applyMask(v, MASKS.cep) : "");
  const phone = (v: unknown) => (v ? formatPhone(v) : "");
  const time = (v: unknown) => (v ? new Date(String(v)).toLocaleTimeString("pt-BR") : "");
  const val = (v: unknown) => money(v ?? 0).replace(/^R\$\s?/, "");
  const numberFmt = String(n.number ?? 0).padStart(9, "0").replace(/(\d{3})(\d{3})(\d{3})/, "$1.$2.$3");
  const seriesFmt = String(n.series ?? 0).padStart(3, "0");
  const key = String(n.access_key ?? "").replace(/(\d{4})(?=\d)/g, "$1 ");
  const status = String(n.status ?? "");
  const cancelled = status === "cancelled";
  const notAuthorized = !["authorized", "cancelled"].includes(status);
  const watermark = cancelled ? "CANCELADA" : n.homologation || notAuthorized ? "SEM VALOR FISCAL" : "";
  const banners: string[] = [];
  if (cancelled) banners.push(`NOTA CANCELADA${n.cancelled_at ? ` EM ${dateTime(n.cancelled_at)}` : ""}${n.cancel_protocol ? ` · PROTOCOLO ${n.cancel_protocol}` : ""}`);
  if (notAuthorized) banners.push(`NOTA ${(DANFE_STATUS[status] ?? status).toUpperCase()} — SEM VALOR FISCAL`);
  if (n.homologation) banners.push("EMITIDA EM AMBIENTE DE HOMOLOGAÇÃO — SEM VALOR FISCAL");
  if (n.contingency) banners.push(nfce ? "EMITIDA EM CONTINGÊNCIA — Pendente de autorização" : "DANFE EM CONTINGÊNCIA — impresso em decorrência de problemas técnicos");
  const cst = (item: Any) => `${item.origin ?? "0"}${item.csosn || item.cst_icms || ""}`;
  const additional: string[] = [];
  if (n.additional_info) additional.push(String(n.additional_info));
  if (issuer.crt === "1") additional.push("DOCUMENTO EMITIDO POR ME OU EPP OPTANTE PELO SIMPLES NACIONAL. NÃO GERA DIREITO A CRÉDITO FISCAL DE IPI.");
  if (Number(n.approx_tax_total)) additional.push(`Valor aproximado dos tributos: R$ ${val(n.approx_tax_total)} (Lei 12.741/2012).`);
  if (n.sale_number) additional.push(`Pedido ${n.sale_number}.`);
  if (n.homologation) additional.push("NF-e emitida em ambiente de homologação — sem valor fiscal.");
  const paymentsTotal = (n.payments ?? []).reduce((a: number, p: Any) => a + Number(p.amount), 0);
  const box = (cls: string, label: string, value: string) => `<div class="box ${cls}"><label>${esc(label)}</label><span>${value || "&nbsp;"}</span></div>`;
  const e = esc;

  const nfceBody = (thermal: boolean) => `<div class="nfce${thermal ? "" : " nfce--a4"}">
    ${watermark ? `<div class="wm wm--small">${e(watermark)}</div>` : ""}
    <header class="nfce__head"><strong>${e(issuer.legal_name || n.fiscal_config_name)}</strong>
      <span>CNPJ ${e(doc(issuer.cnpj))}${issuer.state_registration ? ` · IE ${e(issuer.state_registration)}` : ""}</span>
      <span>${e(issuer.address)}</span><p class="nfce__title">Documento Auxiliar da Nota Fiscal de Consumidor Eletrônica</p></header>
    ${banners.map((b) => `<p class="nfce__banner">${e(b)}</p>`).join("")}
    <table class="nfce__items"><thead><tr><th>Código</th><th>Descrição</th><th class="r">Qtde</th><th>UN</th><th class="r">Vl Unit</th><th class="r">Vl Total</th></tr></thead>
      <tbody>${(n.items ?? []).map((item: Any) => `<tr><td>${e(item.code)}</td><td>${e(item.description)}</td><td class="r">${e(quantity(item.quantity))}</td>
        <td>${e(item.unit)}</td><td class="r">${e(val(item.unit_price))}</td><td class="r">${e(val(item.total))}</td></tr>`).join("")}</tbody></table>
    <div class="nfce__totals"><div><span>Qtde. total de itens</span><span>${(n.items ?? []).length}</span></div>
      <div><span>Valor total R$</span><span>${e(val(n.products_total))}</span></div>
      ${Number(n.discount_total) ? `<div><span>Desconto R$</span><span>${e(val(n.discount_total))}</span></div>` : ""}
      ${Number(n.freight_total) ? `<div><span>Frete R$</span><span>${e(val(n.freight_total))}</span></div>` : ""}
      <div class="strong"><span>Valor a pagar R$</span><span>${e(val(n.total))}</span></div>
      <div class="head"><span>FORMA DE PAGAMENTO</span><span>VALOR PAGO R$</span></div>
      ${(n.payments ?? []).map((p: Any) => `<div><span>${e(p.method_name)}${p.installments > 1 ? ` (${p.installments}x)` : ""}</span><span>${e(val(p.amount))}</span></div>`).join("")}
      ${Number(n.change_amount) ? `<div><span>Troco R$</span><span>${e(val(n.change_amount))}</span></div>` : ""}</div>
    <section class="nfce__block"><b>Consulte pela Chave de Acesso em</b><span>${e(n.consult_url || issuer.portal_url || "o portal da SEFAZ do estado")}</span>
      <span class="key">${e(key || "—")}</span></section>
    <section class="nfce__block"><b>CONSUMIDOR</b>${dest?.document || dest?.name
      ? `<span>${dest.document ? `${String(dest.document).replace(/\D/g, "").length > 11 ? "CNPJ" : "CPF"} ${e(doc(dest.document))}` : ""} ${e(dest.name)}</span>${
        dest.address_line ? `<span>${e(dest.address_line)}, ${e(dest.district)}, ${e(dest.city)}/${e(dest.state)}</span>` : ""}`
      : "<span>CONSUMIDOR NÃO IDENTIFICADO</span>"}</section>
    <section class="nfce__block"><b>NFC-e nº ${e(String(n.number ?? 0).padStart(9, "0"))} Série ${e(seriesFmt)} ${e(dateTime(n.issued_at))}</b>
      ${n.protocol ? `<span>Protocolo de autorização: ${e(n.protocol)}</span>` : ""}${n.authorized_at ? `<span>Data de autorização: ${e(dateTime(n.authorized_at))}</span>` : ""}</section>
    ${n.qr_svg ? `<div class="nfce__qr">${n.qr_svg}</div>` : ""}
    ${Number(n.approx_tax_total) ? `<p class="nfce__note">Tributos totais incidentes (Lei Federal 12.741/2012): R$ ${e(val(n.approx_tax_total))}</p>` : ""}
    ${n.additional_info ? `<p class="nfce__note">${e(n.additional_info)}</p>` : ""}</div>`;

  const nfeBody = () => `<div class="danfe">${watermark ? `<div class="wm">${e(watermark)}</div>` : ""}
    <div class="row stub"><div class="box grow"><label>Recebemos de ${e(issuer.legal_name)} os produtos/serviços constantes da nota fiscal indicada ao lado.
      Emissão: ${e(date(n.issued_at))} · Destinatário: ${e(dest?.name || "—")} · Valor total: R$ ${e(val(n.total))}</label>
      <div class="row inner">${box("w30", "Data de recebimento", "")}${box("grow", "Identificação e assinatura do recebedor", "")}</div></div>
      <div class="box w20 center"><strong>NF-e</strong><span>Nº ${e(numberFmt)}</span><span>Série ${e(seriesFmt)}</span></div></div>
    <div class="cut"></div>
    ${banners.map((b) => `<p class="banner">${e(b)}</p>`).join("")}
    <div class="row head"><div class="box w40 issuer"><strong>${e(issuer.legal_name || n.fiscal_config_name)}</strong>
        ${issuer.trade_name && issuer.trade_name !== issuer.legal_name ? `<span>${e(issuer.trade_name)}</span>` : ""}
        <span>${e(issuer.address_line)}</span><span>${e(issuer.district)}${issuer.zip_code ? ` · CEP ${e(cep(issuer.zip_code))}` : ""}</span>
        <span>${e(issuer.city)}${issuer.state ? ` - ${e(issuer.state)}` : ""}${issuer.phone ? ` · Fone ${e(phone(issuer.phone))}` : ""}</span></div>
      <div class="box w20 center danfe-box"><strong class="big">DANFE</strong><small>Documento Auxiliar da Nota Fiscal Eletrônica</small>
        <div class="io"><small>0 - Entrada<br>1 - Saída</small><b class="io__box">${e(n.direction)}</b></div>
        <b>Nº ${e(numberFmt)}</b><b>Série ${e(seriesFmt)}</b><small>Folha 1/1</small></div>
      <div class="box grow">${n.barcode_svg ? `<div class="barcode">${n.barcode_svg}</div>` : ""}<label>Chave de acesso</label>
        <span class="key">${e(key || "—")}</span><small class="center">Consulta de autenticidade no portal nacional da NF-e www.nfe.fazenda.gov.br/portal ou no site da SEFAZ autorizadora</small></div></div>
    <div class="row">${box("w60", "Natureza da operação", e(n.operation_nature))}${box("grow", "Protocolo de autorização de uso",
      `${e(n.protocol || "—")}${n.authorized_at ? ` · ${e(dateTime(n.authorized_at))}` : ""}`)}</div>
    <div class="row">${box("w33", "Inscrição estadual", e(issuer.state_registration || "—"))}${box("w33", "Inscrição estadual do subst. trib.", "")}${
      box("grow", "CNPJ", e(doc(issuer.cnpj)))}</div>
    <h3>Destinatário / remetente</h3>
    <div class="row">${box("grow", "Nome / razão social", e(dest?.name || "CONSUMIDOR NÃO IDENTIFICADO"))}${box("w20", "CNPJ / CPF", e(doc(dest?.document) || "—"))}${
      box("w15", "Data da emissão", e(date(n.issued_at)))}</div>
    <div class="row">${box("grow", "Endereço", e(dest?.address_line || "—"))}${box("w20", "Bairro / distrito", e(dest?.district || "—"))}${
      box("w10", "CEP", e(cep(dest?.zip_code) || "—"))}${box("w15", "Data da saída", e(date(n.authorized_at || n.issued_at)))}</div>
    <div class="row">${box("grow", "Município", e(dest?.city || "—"))}${box("w15", "Fone / fax", e(phone(dest?.phone) || "—"))}${
      box("w5", "UF", e(dest?.state || "—"))}${box("w15", "Inscrição estadual", e(dest?.state_registration || "—"))}${
      box("w15", "Hora da saída", e(time(n.authorized_at || n.issued_at)))}</div>
    ${(n.duplicates ?? []).length ? `<h3>Fatura / duplicatas</h3><div class="row dups">${n.duplicates.map((d: Any) =>
      `<div class="box dup"><span>Nº ${e(d.number)}</span><span>Venc. ${e(date(d.due_date))}</span><b>R$ ${e(val(d.amount))}</b></div>`).join("")}</div>` : ""}
    <h3>Cálculo do imposto</h3>
    <div class="row">${box("grow r", "Base de cálc. do ICMS", e(val(taxes.icms_base)))}${box("grow r", "Valor do ICMS", e(val(taxes.icms_value)))}${
      box("grow r", "Base de cálc. ICMS S.T.", e(val(taxes.icms_st_base)))}${box("grow r", "Valor do ICMS subst.", e(val(taxes.icms_st_value)))}${
      box("grow r", "V. aprox. tributos", e(val(n.approx_tax_total)))}${box("grow r", "Valor total dos produtos", e(val(n.products_total)))}</div>
    <div class="row">${box("grow r", "Valor do frete", e(val(n.freight_total)))}${box("grow r", "Valor do seguro", e(val(taxes.insurance)))}${
      box("grow r", "Desconto", e(val(n.discount_total)))}${box("grow r", "Outras despesas", e(val(taxes.other_expenses)))}${
      box("grow r", "Valor total do IPI", e(val(taxes.ipi_value)))}${box("grow r total", "Valor total da nota", e(val(n.total)))}</div>
    <h3>Transportador / volumes transportados</h3>
    <div class="row">${box("grow", "Nome / razão social", e(transport.name))}${box("w25", "Frete", e(transport.mode))}${
      box("w10", "Código ANTT", e(transport.antt || ""))}${box("w10", "Placa do veículo", e(transport.plate || ""))}${
      box("w5", "UF", e(transport.plate_state || ""))}${box("w15", "CNPJ / CPF", e(doc(transport.document)))}</div>
    <div class="row">${box("grow", "Quantidade", e(transport.volumes || ""))}${box("grow", "Espécie", e(transport.species || ""))}${
      box("grow", "Marca", e(transport.brand || ""))}${box("grow", "Numeração", e(transport.numbering || ""))}${
      box("grow", "Peso bruto", e(transport.gross_weight || ""))}${box("grow", "Peso líquido", e(transport.net_weight || ""))}</div>
    <h3>Dados dos produtos / serviços</h3>
    <table class="items"><thead><tr><th>Código</th><th>Descrição do produto / serviço</th><th>NCM/SH</th><th>O/CST</th><th>CFOP</th><th>UN</th>
      <th class="r">Qtde</th><th class="r">V. unit.</th><th class="r">V. desc.</th><th class="r">V. total</th><th class="r">BC ICMS</th>
      <th class="r">V. ICMS</th><th class="r">V. IPI</th><th class="r">Alíq. ICMS</th><th class="r">Alíq. IPI</th></tr></thead>
      <tbody>${(n.items ?? []).map((item: Any) => `<tr><td>${e(item.code)}</td><td class="desc">${e(item.description)}</td><td>${e(item.ncm)}</td>
        <td>${e(cst(item))}</td><td>${e(item.cfop)}</td><td>${e(item.unit)}</td><td class="r">${e(quantity(item.quantity))}</td>
        <td class="r">${e(val(item.unit_price))}</td><td class="r">${e(val(item.discount))}</td><td class="r">${e(val(item.total))}</td>
        <td class="r">${e(val(item.icms_base))}</td><td class="r">${e(val(item.icms_value))}</td><td class="r">0,00</td>
        <td class="r">${e(Number(item.icms_rate ?? 0).toLocaleString("pt-BR", { minimumFractionDigits: 2 }))}</td><td class="r">0,00</td></tr>`).join("")}</tbody></table>
    <h3>Dados adicionais</h3>
    <div class="row extra"><div class="box w65"><label>Informações complementares</label>${additional.length
      ? additional.map((l) => `<p>${e(l)}</p>`).join("") : "<p>&nbsp;</p>"}</div>${box("grow", "Reservado ao fisco", "")}</div>
    ${paymentsTotal ? `<p class="pays">Pagamento: ${(n.payments ?? []).map((p: Any) => `${e(p.method_name)} ${p.installments > 1 ? `(${p.installments}x) ` : ""}R$ ${e(val(p.amount))}`).join(" · ")}</p>` : ""}
  </div>`;

  return {
    title: `DANFE ${nfce ? "NFC-e" : "NF-e"}`, formats, format: pick(query, formats, nfce ? "80mm" : "a4"), bare: true, storeId: n.store,
    filename: `danfe-${n.access_key || n.number || id}`,
    css: DANFE_CSS,
    body: (thermal) => (nfce ? nfceBody(thermal) : nfeBody()),
  };
};

const DANFE_CSS = `
.danfe, .nfce { position: relative; }
.wm { position: absolute; top: 30%; left: 0; right: 0; text-align: center; font: 900 54pt/1 Arial, sans-serif; color: rgba(185, 28, 28, 0.13);
      transform: rotate(-28deg); pointer-events: none; z-index: 0; white-space: nowrap; }
.wm--small { font-size: 26pt; top: 40%; }
.danfe { font: 7.5pt/1.25 Arial, Helvetica, sans-serif; color: #000; }
.danfe h3 { margin: 5px 0 1px; font: 700 7pt/1 Arial, sans-serif; text-transform: uppercase; }
.row { display: flex; }
.row + .row, .head + .row { margin-top: -1px; }
.box { border: 1px solid #000; padding: 1px 4px 2px; min-height: 22px; display: flex; flex-direction: column; min-width: 0; }
.box + .box { margin-left: -1px; }
.box label { font-size: 5.6pt; text-transform: uppercase; color: #222; line-height: 1.2; }
.box span, .box p { font-size: 8pt; margin: 0; overflow-wrap: anywhere; }
.box.r span { text-align: right; } .box.total span { font-weight: 700; }
.grow { flex: 1; }
.w5 { width: 5%; } .w10 { width: 10%; } .w15 { width: 15%; } .w20 { width: 20%; } .w25 { width: 25%; } .w30 { width: 30%; }
.w33 { width: 33.3%; } .w40 { width: 40%; } .w60 { width: 60%; } .w65 { width: 65%; }
.center { align-items: center; justify-content: center; text-align: center; }
.stub .inner { margin-top: 3px; } .stub .inner .box { border-width: 1px 1px 0 0; } .stub .inner .box:first-child { border-left: 0; }
.cut { border-top: 1px dashed #000; margin: 5px 0; }
.banner { margin: 0 0 4px; padding: 3px; border: 2px solid #b91c1c; color: #b91c1c; font: 700 8.5pt Arial, sans-serif; text-align: center; }
.issuer { justify-content: center; gap: 1px; } .issuer strong { font-size: 10pt; } .issuer span { font-size: 7.5pt; }
.danfe-box { gap: 1px; } .danfe-box .big { font-size: 13pt; } .danfe-box small { font-size: 6.5pt; }
.io { display: flex; align-items: center; gap: 6px; margin: 2px 0; } .io__box { border: 1px solid #000; padding: 1px 6px; font-size: 11pt; }
.barcode { margin: 2px auto; width: 100%; max-width: 95mm; } .barcode svg { width: 100%; height: 12mm; display: block; }
.key { font: 700 8.5pt/1.3 monospace; text-align: center; letter-spacing: 0.02em; }
.dups { flex-wrap: wrap; } .dup { width: 16.66%; font-size: 7pt; } .dup span { font-size: 7pt; }
.items { width: 100%; border-collapse: collapse; font-size: 6.6pt; }
.items th, .items td { border: 1px solid #000; padding: 1px 2px; vertical-align: top; }
.items th { font-size: 5.6pt; text-transform: uppercase; font-weight: 400; } .items .desc { width: 30%; }
.items .r, .r { text-align: right; }
.extra .box { min-height: 26mm; } .extra p { font-size: 7pt; } .pays { margin: 4px 0 0; font-size: 7pt; }
.nfce { font: 8pt/1.3 Arial, Helvetica, sans-serif; color: #000; }
.nfce--a4 { max-width: 110mm; margin: 0 auto; font-size: 9pt; }
.nfce__head { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 1px; padding-bottom: 4px; border-bottom: 1px dashed #000; }
.nfce__head strong { font-size: 9.5pt; } .nfce__title { margin: 4px 0 0; font-weight: 700; }
.nfce__banner { margin: 4px 0; padding: 2px; border: 1px solid #000; font-weight: 700; text-align: center; }
.nfce__items { width: 100%; border-collapse: collapse; margin-top: 4px; font-size: 7.2pt; }
.nfce__items th { text-align: left; border-bottom: 1px solid #000; font-weight: 700; }
.nfce__items td { padding: 1px 0; vertical-align: top; } .nfce__items .r { text-align: right; }
.nfce__totals { border-top: 1px dashed #000; margin-top: 4px; padding-top: 3px; }
.nfce__totals > div { display: flex; justify-content: space-between; } .nfce__totals .strong { font-weight: 700; }
.nfce__totals .head { margin-top: 3px; font-weight: 700; font-size: 7pt; }
.nfce__block { display: flex; flex-direction: column; align-items: center; text-align: center; border-top: 1px dashed #000;
               margin-top: 4px; padding-top: 3px; overflow-wrap: anywhere; }
.nfce__qr { width: 32mm; margin: 4px auto; } .nfce__qr svg { width: 100%; height: auto; display: block; }
.nfce__note { margin: 3px 0 0; text-align: center; font-size: 7pt; }
.danfe .row, .items tr { break-inside: avoid; }
`;

/* ── registro (ficha de qualquer cadastro sem documento próprio) ──────────
 * A retaguarda imprime a LISTA de qualquer cadastro; para um registro só, a ficha usa as mesmas peças da folha:
 * a grade "rótulo / valor" (PrintMeta) por seção e as tabelas (PrintTable) para itens, parcelas, variantes... */
const registro: Loader = async (id, { query }) => {
  const resource = findResource(query.cadastro ?? "");
  if (!resource) throw new Error("Cadastro desconhecido.");
  const values = await api.get<Any>(`${resource.endpoint}${id}/`);
  const display = resource.display ?? {};
  const byName = new Map(resource.fields.map((f) => [f.name, f]));
  const visible = (f?: FieldDef): f is FieldDef => !!f && f.type !== "images" && f.type !== "password"
    && f.type !== "seo-preview" && (!f.visible || f.visible(values));
  const text = (f: FieldDef) => (f.type === "richtext" ? stripHtml(String(values[f.name] ?? "")) || "—" : fieldText(f, values));
  const tableOf = (columns: PCol[], rows: Any[], empty = "Nenhum item.") => printTable(columns, rows, { empty });
  const composite = (f: FieldDef) => {
    const t = compositeTable(f, values);
    return t ? tableOf(t.columns as PCol[], t.rows) : "";
  };
  const parts: string[] = [];
  const stats = (display.stats ?? []).filter((st) => !st.visible || st.visible(values));
  if (stats.length) {
    parts.push(`<div class="doc-kpis">${stats.map((st) => `<div><small>${esc(st.label)}</small><b>${
      esc(cellText({ key: st.label, label: st.label, type: st.type }, st.value(values)))}</b></div>`).join("")}</div>`);
  }
  const sections: { title: string; plain: [string, unknown][]; tables: string[] }[] = [];
  if (display.sections) {
    for (const sec of [...display.sections, ...(display.aside ?? [])].filter((x) => !x.visible || x.visible(values))) {
      const fields = (sec.fields ?? []).map((n) => byName.get(n)).filter(visible);
      const items = (sec.items ?? []).filter((i) => !i.visible || i.visible(values)).map((i): [string, unknown] => {
        const value = i.value ? i.value(values) : values[i.key ?? ""];
        const options = i.map ? Object.entries(i.map).map(([v, label]) => ({ value: v, label })) : undefined;
        return [i.label, fieldText({ name: "__v", label: i.label, type: i.type ?? "text", options } as FieldDef, { ...values, __v: value })];
      });
      const grid = sec.table;
      const gridHtml = grid ? (() => {
        const columns = (typeof grid.columns === "function" ? grid.columns(values) : grid.columns) as PCol[];
        return tableOf(columns, grid.rows(values), grid.empty ?? "Nada por aqui.");
      })() : "";
      sections.push({
        title: sec.title,
        plain: [...fields.filter((f) => !TABLE_TYPES.includes(f.type)).map((f): [string, unknown] => [f.label, text(f)]), ...items],
        tables: [...fields.filter((f) => TABLE_TYPES.includes(f.type)).map(composite), gridHtml].filter(Boolean),
      });
    }
  } else {
    const groups = new Map<string, FieldDef[]>();
    for (const f of resource.fields) {
      if ((display.hide ?? []).includes(f.name) || !visible(f) || f.createOnly) continue;
      const name = f.section ?? "Dados";
      groups.set(name, [...(groups.get(name) ?? []), f]);
    }
    for (const [title, fields] of groups) {
      sections.push({ title, plain: fields.filter((f) => !TABLE_TYPES.includes(f.type)).map((f) => [f.label, text(f)]),
                      tables: fields.filter((f) => TABLE_TYPES.includes(f.type)).map(composite).filter(Boolean) });
    }
  }
  for (const sec of sections) {
    if (!sec.plain.length && !sec.tables.length) continue;
    parts.push(section(sec.title, (sec.plain.length ? printMeta(sec.plain, 3) : "") + sec.tables.join("")));
  }
  const title = recordTitle(values, resource);
  return {
    title, subtitle: `${resource.group} · ${resource.title}`, formats: ["a4"], format: "a4", storeId: values.store,
    filename: slugify(`${resource.singular}-${title}`), css: ".doc-section .pt { margin-top: 6px; }",
    body: () => parts.join(""),
  };
};

export const DOCS: Record<string, Loader> = { turno, venda, danfe, estoque, separacao, conta, titulo, dre, lista, relatorio, registro };
