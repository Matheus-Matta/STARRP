/**
 * Estoque: documentos (entrada, saída, transferência, inventário...), saldos,
 * kardex, lotes, endereços (WMS), modelos de etiqueta e configurações.
 */
import { defineAsyncComponent } from "vue";

import { stockApi } from "@/api/operations";
import { resourceApi } from "@/api/resource";
import { quantity } from "@/utils/format";
import { openPrint } from "@/utils/print";

// Diálogos só baixam quando abertos.
const PickingDialog = defineAsyncComponent(() => import("@/components/stock/PickingDialog.vue"));
const ConferenceDialog = defineAsyncComponent(() => import("@/components/stock/ConferenceDialog.vue"));
const LabelsDialog = defineAsyncComponent(() => import("@/components/stock/LabelsDialog.vue"));

import { choices, type ColumnDef, defineResource, linkTo, rowsOf, sumOf, type Tone, yesNo } from "./types";

export const documentKind = choices({
  entry: "Entrada", exit: "Saída", transfer: "Transferência", adjustment: "Ajuste", inventory: "Inventário",
  supplier_return: "Devolução ao fornecedor", relocation: "Mudança de endereço",
});
export const documentStatus = choices({ draft: "Rascunho", posted: "Confirmado", cancelled: "Cancelado" });
export const exitReason = choices({ consumption: "Consumo interno", loss: "Perda / avaria", expiration: "Vencimento" });
export const movementKind = choices({
  initial: "Implantação", purchase: "Compra", sale: "Venda", sale_return: "Devolução de cliente",
  transfer_in: "Transferência (entrada)", transfer_out: "Transferência (saída)", adjustment: "Ajuste / inventário",
  consumption: "Consumo", loss: "Perda", expiration: "Vencimento", supplier_return: "Devolução ao fornecedor",
  asset_disposal: "Baixa patrimonial", relocation: "Mudança de endereço", reversal: "Estorno",
});
export const lotStatus = choices({
  available: "Disponível", depleted: "Esgotado", blocked: "Bloqueado", expired: "Vencido", discarded: "Descartado",
});
const binKind = choices({ storage: "Armazenagem", picking: "Separação", receiving: "Recebimento", shipping: "Expedição" });
const labelSubject = choices({ product: "Produto / gôndola", lot: "Lote", bin: "Endereço", volume: "Caixa (volume)" });

const STOCK = { permission: "stock", module: "stock", group: "Estoque" } as const;

/** Colunas usadas pelas consultas de outros cadastros (kardex do produto, saldos do depósito...). */
export const movementColumns: ColumnDef[] = [
  { key: "created_at", label: "Quando", type: "datetime" },
  { key: "variant_name", label: "Produto", title: true },
  { key: "kind", label: "Tipo", type: "tag", map: movementKind.map },
  { key: "quantity", label: "Qtd.", type: "quantity", total: true },
  { key: "balance_after", label: "Saldo após", type: "quantity" },
  { key: "unit_cost", label: "Custo unit.", type: "money" },
  { key: "warehouse_name", label: "Depósito" },
  { key: "operator_name", label: "Por" },
];
export const balanceColumns: ColumnDef[] = [
  { key: "variant_name", label: "Produto", title: true },
  { key: "sku", label: "SKU" },
  { key: "warehouse_name", label: "Depósito" },
  { key: "quantity", label: "Saldo", type: "quantity", total: true },
  { key: "updated_at", label: "Último movimento", type: "datetime" },
];
export const lotColumns: ColumnDef[] = [
  { key: "code", label: "Código" },
  { key: "variant_name", label: "Produto", title: true },
  { key: "lot_number", label: "Lote" },
  { key: "expires_at", label: "Validade", type: "date" },
  { key: "quantity", label: "Saldo", type: "quantity", total: true },
  { key: "status", label: "Situação", type: "tag", map: lotStatus.map },
];
export const documentColumns: ColumnDef[] = [
  { key: "number", label: "Nº", title: true },
  { key: "kind", label: "Tipo", type: "tag", map: documentKind.map },
  { key: "status", label: "Situação", type: "tag", map: documentStatus.map },
  { key: "effective_date", label: "Data", type: "date" },
  { key: "external_number", label: "Nota / doc." },
  { key: "item_count", label: "Itens", sortable: false },
];
const kardexLink = (row: Record<string, unknown>) => `/cadastros/movimentacoes-de-estoque?variant=${row.variant}`;
const documentLink = (row: Record<string, unknown>) => `/cadastros/documentos-de-estoque/${row.id}`;
export const stockLinks = { kardexLink, documentLink };
const warehouse = { endpoint: "/stock/warehouses/" };
const is = (...kinds: string[]) => (v: Record<string, unknown>) => kinds.includes(String(v.kind ?? ""));
const draft = (v: Record<string, unknown>) => v.status === "draft";
/** Entrada que veio de NF-e: conferência → aprovação. */
const fromNfe = (v: Record<string, unknown>) => Boolean(v.inbound_nfe);

const statusTone: Record<string, Tone> = { draft: "warning", posted: "success", cancelled: "danger" };
/** Linhas do documento com a diferença contado − esperado (nota / sistema). */
const docItems = (v: Record<string, unknown>) => rowsOf(v, "items").map((row) => ({
  ...row, difference: row.expected_quantity == null ? null : Number(row.quantity) - Number(row.expected_quantity),
}));
const hasExpected = (v: Record<string, unknown>) => rowsOf(v, "items").some((row) => row.expected_quantity != null);

export const stockDocuments = defineResource({
  ...STOCK,
  name: "documentos-de-estoque",
  display: {
    badges: (v) => [
      { label: documentKind.map[String(v.kind)] ?? "Documento", icon: "pi pi-file" },
      { label: documentStatus.map[String(v.status)] ?? "", tone: statusTone[String(v.status)] },
      Boolean(v.checked_at) && { label: "Conferido", tone: "info", icon: "pi pi-list-check" },
      Boolean(v.inbound_nfe) && { label: `NF-e ${v.inbound_nfe_number ?? ""}`, tone: "neutral", icon: "pi pi-inbox" },
    ],
    stats: [
      { label: "Itens", icon: "pi pi-list", value: (v) => rowsOf(v, "items").length },
      { label: "Quantidade", icon: "pi pi-box", type: "quantity", value: (v) => sumOf(rowsOf(v, "items"), "quantity") },
      { label: "Custo total", icon: "pi pi-wallet", type: "money", value: (v) => sumOf(rowsOf(v, "items"), "total_cost"),
        visible: (v) => v.kind === "entry" },
      { label: "Diferença", icon: "pi pi-sort-alt", type: "quantity", visible: hasExpected,
        value: (v) => sumOf(docItems(v), "difference"),
        tone: (v) => (sumOf(docItems(v), "difference") === 0 ? "success" : "danger"),
        hint: (v) => (sumOf(docItems(v), "difference") === 0 ? "Contado igual ao esperado" : "Contado diferente do esperado") },
    ],
    sections: [
      { title: "Movimento", icon: "pi pi-arrow-right-arrow-left",
        description: (v) => ({ entry: "Para onde o estoque entrou.", exit: "De onde o estoque saiu e por quê.",
                               transfer: "De um depósito para o outro.", inventory: "Contagem que acertou o saldo do sistema.",
                               adjustment: "Acerto de saldo com a diferença em cada item." } as Record<string, string>)[String(v.kind)]
          ?? "O que este documento movimenta.",
        items: [
          { label: "Tipo", key: "kind", type: "tag", map: documentKind.map },
          { label: "Depósito", key: "warehouse_name", link: (v) => linkTo("depositos", v.warehouse) },
          { label: "Depósito de destino", key: "destination_name", link: (v) => linkTo("depositos", v.destination),
            visible: (v) => Boolean(v.destination) },
          { label: "Motivo da saída", key: "exit_reason", type: "tag", map: exitReason.map, visible: (v) => v.kind === "exit" },
          { label: "Data do movimento", key: "effective_date", type: "date" },
        ] },
      { title: "Origem", icon: "pi pi-truck", description: "De quem veio e o documento que acompanha a mercadoria.",
        visible: (v) => Boolean(v.supplier || v.external_number || v.inbound_nfe),
        items: [
          { label: "Fornecedor", key: "supplier_name", link: (v) => linkTo("fornecedores", v.supplier) },
          { label: "Nota / documento", key: "external_number" },
          { label: "NF-e de entrada", value: (v) => (v.inbound_nfe ? `NF-e ${v.inbound_nfe_number}` : null),
            link: (v) => linkTo("notas-de-entrada", v.inbound_nfe), visible: (v) => Boolean(v.inbound_nfe) },
        ] },
      { title: "Itens", icon: "pi pi-list",
        description: (v) => (hasExpected(v) ? "\"Na nota\" é o que veio no documento; \"Contado\" é o que a conferência achou."
          : "Produtos e quantidades do documento."),
        table: {
          rows: docItems, empty: "Documento sem itens.",
          columns: (v) => [
            { key: "variant_name", label: "Produto", title: true }, { key: "sku", label: "SKU" },
            ...(hasExpected(v) ? [{ key: "expected_quantity", label: v.kind === "inventory" ? "Sistema" : "Na nota",
                                    type: "quantity" as const, total: true }] : []),
            { key: "quantity", label: hasExpected(v) ? "Contado" : "Qtd.", type: "quantity", total: true },
            ...(hasExpected(v) ? [{ key: "difference", label: "Diferença", type: "quantity" as const, total: true }] : []),
            ...(v.kind === "entry" ? [{ key: "unit_cost", label: "Custo unit.", type: "money" as const },
                                      { key: "total_cost", label: "Total", type: "money" as const, total: true }] : []),
            { key: "lot_number", label: "Lote" }, { key: "expires_at", label: "Validade", type: "date" },
          ],
        } },
      { title: "Observação", icon: "pi pi-comment", visible: (v) => Boolean(v.reason),
        items: [{ label: "Anotação", key: "reason", type: "textarea", span: "full" }] },
    ],
    aside: [
      { title: "Resumo", icon: "pi pi-chart-bar", items: [
        { label: "Número", key: "number" },
        { label: "Situação", key: "status", type: "tag", map: documentStatus.map, tones: statusTone },
        { label: "Itens", value: (v) => rowsOf(v, "items").length },
        { label: "Quantidade", type: "quantity", value: (v) => sumOf(rowsOf(v, "items"), "quantity") },
        { label: "Custo total", type: "money", strong: true, value: (v) => sumOf(rowsOf(v, "items"), "total_cost"),
          visible: (v) => v.kind === "entry" },
      ] },
    ],
  },
  views: [
    { name: "movimentos", label: "Movimentos gerados", icon: "pi pi-arrow-right-arrow-left",
      description: "O que este documento moveu no estoque (e os estornos, se cancelado).",
      list: { endpoint: "/stock/movements/", params: (id) => ({ document_item__document: id }), columns: movementColumns,
              ordering: "created_at", searchable: false } },
  ],
  title: "Documentos de estoque",
  singular: "documento",
  endpoint: "/stock/documents/",
  icon: "pi pi-file-edit",
  ordering: "-number",
  lockedWhen: (v) => Boolean(v.id) && v.status !== "draft",
  /** Documento abre os itens: produto, SKU (na coluna do depósito) e a quantidade. */
  tree: {
    hasChildren: (row) => Number(row.item_count ?? 0) > 0,
    children: async (row) => rowsOf(await resourceApi.get("/stock/documents/", String(row.id)), "items")
      .map((i) => ({ id: i.id, number: i.variant_name, warehouse_name: i.sku, item_count: quantity(i.quantity),
                     external_number: i.lot_number || undefined })),
  },
  columns: [
    { key: "number", label: "Nº", title: true },
    { key: "kind", label: "Tipo", type: "tag", map: documentKind.map },
    { key: "status", label: "Situação", type: "tag", map: documentStatus.map },
    { key: "warehouse_name", label: "Depósito" },
    { key: "effective_date", label: "Data", type: "date" },
    { key: "item_count", label: "Itens", sortable: false },
    { key: "external_number", label: "Nota / doc." },
    { key: "checked_at", label: "Conferido em", type: "datetime" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: documentKind.options },
    { name: "status", label: "Situação", type: "select", options: documentStatus.options },
    { name: "warehouse", label: "Depósito", type: "relation", relation: warehouse },
    { name: "effective_date", label: "Período", type: "daterange" },
  ],
  sections: {
    Documento: { icon: "pi pi-file", description: "Rascunho pode tudo; confirmado move o estoque e só se desfaz cancelando (estorno)." },
    Itens: { icon: "pi pi-list", description: "Leia os códigos ou escolha os produtos. Entrada pede o custo, que atualiza o custo médio." },
  },
  fields: [
    { name: "kind", label: "Tipo", type: "segmented", options: documentKind.options, default: "entry", section: "Documento", full: true },
    { name: "warehouse", label: "Depósito", type: "relation", relation: warehouse, required: true, section: "Documento" },
    { name: "destination", label: "Depósito de destino", type: "relation", relation: warehouse, section: "Documento",
      visible: is("transfer") },
    { name: "exit_reason", label: "Motivo da saída", type: "select", options: exitReason.options, default: "consumption",
      section: "Documento", visible: is("exit") },
    { name: "supplier", label: "Fornecedor", type: "relation", relation: { endpoint: "/suppliers/" }, section: "Documento",
      visible: is("entry", "supplier_return") },
    { name: "external_number", label: "Nº da nota / documento", type: "text", maxLength: 60, section: "Documento" },
    { name: "effective_date", label: "Data", type: "date", required: true, default: new Date().toLocaleDateString("sv-SE"),
      section: "Documento" },
    { name: "reason", label: "Observação", type: "textarea", section: "Documento" },
    { name: "items", label: "Itens", type: "stock-items", default: [], section: "Itens" },
  ],
  rowActions: [
    { label: "Imprimir documento", icon: "pi pi-print", run: async (row) => openPrint("estoque", String(row.id)) },
    { label: "Imprimir separação", icon: "pi pi-map", run: async (row) => openPrint("separacao", String(row.id)),
      visible: (row) => row.status === "draft" && ["exit", "transfer", "supplier_return", "relocation"].includes(String(row.kind)) },
  ],
  formActions: [
    { label: "Imprimir", icon: "pi pi-print", run: async ({ id }) => openPrint("estoque", id) },
    { label: "Confirmar", icon: "pi pi-check", severity: "success", visible: (v) => draft(v) && !fromNfe(v),
      success: "Documento confirmado",
      confirm: "Confirmar o documento? O estoque é movimentado e o documento não poderá mais ser editado.",
      run: ({ id }) => stockApi.post(id) },
    { label: "Conferido (digitado)", icon: "pi pi-list-check", visible: (v) => draft(v) && fromNfe(v) && !v.checked_at,
      success: "Conferência concluída",
      confirm: "Concluir a conferência com as quantidades digitadas nos itens? Use a Conferência para ler os códigos.",
      run: ({ id }) => stockApi.check(id) },
    { label: "Aprovar entrada", icon: "pi pi-check", severity: "success", visible: (v) => draft(v) && fromNfe(v) && Boolean(v.checked_at),
      success: "Entrada aprovada: estoque e contas a pagar lançados",
      confirm: "Aprovar a entrada? O estoque entra com as quantidades conferidas e as duplicatas da nota viram contas a pagar.",
      run: ({ id }) => stockApi.post(id) },
    { label: "Ver nota", icon: "pi pi-inbox", visible: fromNfe,
      // Router importado na hora: no topo do arquivo fecharia um ciclo (router → páginas → recursos).
      run: async ({ values }) => (await import("@/router")).router.push(`/cadastros/notas-de-entrada/${values.inbound_nfe}`) },
    { label: "Separação", icon: "pi pi-map", dialog: PickingDialog,
      visible: (v) => draft(v) && is("exit", "transfer", "supplier_return", "relocation")(v) },
    { label: "Conferência", icon: "pi pi-qrcode", dialog: ConferenceDialog, visible: (v) => v.status !== "cancelled" },
    { label: "Etiquetas", icon: "pi pi-tags", dialog: LabelsDialog, visible: (v) => v.status === "posted" && is("entry")(v) },
    { label: "Cancelar", icon: "pi pi-times", severity: "danger", visible: (v) => v.status !== "cancelled",
      confirm: "Cancelar o documento? Se já foi confirmado, cada movimento ganha um estorno.",
      success: "Documento cancelado", run: ({ id }) => stockApi.cancel(id) },
  ],
});

export const stockBalances = defineResource({
  ...STOCK,
  name: "saldos",
  title: "Saldos de estoque",
  singular: "saldo",
  endpoint: "/stock/balances/",
  icon: "pi pi-chart-bar",
  readOnly: true,
  creatable: false,
  ordering: "variant__product__name",
  rowLink: (row) => `/cadastros/movimentacoes-de-estoque?variant=${row.variant}`,
  columns: [
    { key: "variant_name", label: "Produto", title: true },
    { key: "sku", label: "SKU" },
    { key: "warehouse_name", label: "Depósito" },
    { key: "quantity", label: "Saldo", type: "quantity", total: true },
    { key: "updated_at", label: "Último movimento", type: "datetime" },
  ],
  filters: [{ name: "warehouse", label: "Depósito", type: "relation", relation: warehouse }],
  fields: [],
});

export const stockMovements = defineResource({
  ...STOCK,
  name: "movimentacoes-de-estoque",
  display: {
    badges: (v) => [{ label: movementKind.map[String(v.kind)] ?? String(v.kind ?? ""), icon: "pi pi-arrow-right-arrow-left" }],
    stats: [
      { label: "Quantidade", icon: "pi pi-box", type: "quantity", value: (v) => v.quantity,
        tone: (v) => (Number(v.quantity) < 0 ? "danger" : "success"),
        hint: (v) => (Number(v.quantity) < 0 ? "Saiu do estoque" : "Entrou no estoque") },
      { label: "Saldo depois", icon: "pi pi-chart-bar", type: "quantity", value: (v) => v.balance_after },
      { label: "Custo total", icon: "pi pi-wallet", type: "money", value: (v) => v.total_cost },
    ],
    sections: [
      { title: "Produto", icon: "pi pi-box", description: "O que mexeu no estoque.", items: [
        { label: "Produto", key: "variant_name", span: "wide", link: (v) => (v.variant ? `/cadastros/movimentacoes-de-estoque?variant=${v.variant}` : null),
          hint: () => "Abre o kardex do produto" },
        { label: "SKU", key: "sku" },
        { label: "Tipo", key: "kind", type: "tag", map: movementKind.map },
        { label: "Depósito", key: "warehouse_name", link: (v) => linkTo("depositos", v.warehouse) },
      ] },
      { title: "Valores", icon: "pi pi-wallet", description: "Custo usado no movimento (entra no custo médio nas entradas).", items: [
        { label: "Quantidade", key: "quantity", type: "quantity" },
        { label: "Custo unitário", key: "unit_cost", type: "money" },
        { label: "Custo total", key: "total_cost", type: "money", strong: true },
        { label: "Saldo depois", key: "balance_after", type: "quantity" },
      ] },
      { title: "Motivo", icon: "pi pi-comment", visible: (v) => Boolean(v.reason),
        items: [{ label: "Anotação", key: "reason", type: "textarea", span: "full" }] },
    ],
  },
  title: "Movimentações (kardex)",
  singular: "movimentação",
  feminine: true,
  endpoint: "/stock/movements/",
  icon: "pi pi-arrow-right-arrow-left",
  readOnly: true,
  creatable: false,
  ordering: "-created_at",
  columns: [
    { key: "created_at", label: "Quando", type: "datetime" },
    { key: "variant_name", label: "Produto", title: true },
    { key: "kind", label: "Tipo", type: "tag", map: movementKind.map },
    { key: "quantity", label: "Qtd.", type: "quantity", total: true },
    { key: "balance_after", label: "Saldo após", type: "quantity" },
    { key: "unit_cost", label: "Custo unit.", type: "money" },
    { key: "warehouse_name", label: "Depósito" },
    { key: "operator_name", label: "Por" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: movementKind.options },
    { name: "warehouse", label: "Depósito", type: "relation", relation: warehouse },
    { name: "created_at", label: "Período", type: "daterange" },
  ],
  fields: [
    { name: "variant_name", label: "Produto", type: "text", span: 4 },
    { name: "kind", label: "Tipo", type: "select", options: movementKind.options },
    { name: "quantity", label: "Quantidade", type: "quantity" },
    { name: "balance_after", label: "Saldo depois", type: "quantity" },
    { name: "unit_cost", label: "Custo unitário", type: "money" },
    { name: "total_cost", label: "Custo total", type: "money" },
    { name: "warehouse_name", label: "Depósito", type: "text" },
    { name: "operator_name", label: "Feito por", type: "text" },
    { name: "reason", label: "Motivo", type: "textarea" },
  ],
});

export const stockLots = defineResource({
  ...STOCK,
  name: "lotes",
  title: "Lotes e validades",
  singular: "lote",
  endpoint: "/stock/lots/",
  icon: "pi pi-calendar-clock",
  creatable: false,
  deletable: false,
  ordering: "expires_at",
  columns: [
    { key: "code", label: "Código" },
    { key: "variant_name", label: "Produto", title: true },
    { key: "lot_number", label: "Lote do fabricante" },
    { key: "expires_at", label: "Validade", type: "date" },
    { key: "quantity", label: "Saldo", type: "quantity", total: true },
    { key: "status", label: "Situação", type: "tag", map: lotStatus.map },
    { key: "warehouse_name", label: "Depósito" },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: lotStatus.options },
    { name: "warehouse", label: "Depósito", type: "relation", relation: warehouse },
    { name: "expires_at", label: "Vence entre", type: "daterange" },
  ],
  fields: [
    { name: "variant_name", label: "Produto", type: "text", span: 4 },
    { name: "code", label: "Código interno", type: "text" },
    { name: "lot_number", label: "Lote do fabricante", type: "text" },
    { name: "manufactured_at", label: "Fabricação", type: "date" },
    { name: "expires_at", label: "Validade", type: "date" },
    { name: "status", label: "Situação", type: "select", options: lotStatus.options,
      hint: "Bloqueado não sai na venda nem na separação." },
  ],
});

export const storageBins = defineResource({
  ...STOCK,
  group: "Logística",
  name: "enderecos",
  title: "Endereços (WMS)",
  singular: "endereço",
  endpoint: "/stock/bins/",
  icon: "pi pi-th-large",
  ordering: "sequence",
  columns: [
    { key: "code", label: "Endereço", title: true },
    { key: "kind", label: "Tipo", type: "tag", map: binKind.map },
    { key: "aisle", label: "Rua" },
    { key: "rack", label: "Prateleira" },
    { key: "level", label: "Nível" },
    { key: "sequence", label: "Ordem na rota" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "warehouse", label: "Depósito", type: "relation", relation: warehouse },
    { name: "kind", label: "Tipo", type: "select", options: binKind.options },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "warehouse", label: "Depósito", type: "relation", relation: warehouse, required: true },
    { name: "code", label: "Endereço", type: "text", required: true, placeholder: "A-01-1" },
    { name: "kind", label: "Tipo", type: "select", options: binKind.options, default: "storage" },
    { name: "aisle", label: "Rua", type: "text", span: 1 },
    { name: "rack", label: "Prateleira", type: "text", span: 1 },
    { name: "level", label: "Nível", type: "text", span: 1 },
    { name: "position", label: "Posição", type: "text", span: 1 },
    { name: "sequence", label: "Ordem na rota", type: "number", default: 0, hint: "A separação segue esta ordem." },
    { name: "is_active", label: "Ativo", type: "boolean", default: true },
  ],
});

export const labelTemplates = defineResource({
  ...STOCK,
  name: "modelos-de-etiqueta",
  title: "Modelos de etiqueta",
  singular: "modelo",
  endpoint: "/stock/label-templates/",
  icon: "pi pi-tags",
  columns: [
    { key: "name", label: "Nome" },
    { key: "subject", label: "Para", type: "tag", map: labelSubject.map },
    { key: "width_mm", label: "Largura (mm)" },
    { key: "height_mm", label: "Altura (mm)" },
    { key: "is_default", label: "Padrão", type: "boolean" },
    { key: "is_system", label: "Pré-pronto", type: "boolean" },
  ],
  filters: [
    { name: "subject", label: "Para", type: "select", options: labelSubject.options },
    { name: "is_system", label: "Pré-pronto do sistema", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, span: 3 },
    { name: "subject", label: "Para", type: "segmented", options: labelSubject.options, default: "product", span: 3 },
    { name: "width_mm", label: "Largura (mm)", type: "measure", default: "60.0", span: 1 },
    { name: "height_mm", label: "Altura (mm)", type: "measure", default: "40.0", span: 1 },
    { name: "margin_mm", label: "Margem (mm)", type: "measure", default: "2.0", span: 1 },
    { name: "columns", label: "Colunas", type: "number", default: 1, span: 1 },
    { name: "font_size_pt", label: "Fonte (pt)", type: "measure", default: "8.0", span: 1 },
    { name: "code_type", label: "Código", type: "select", options: [
      { label: "EAN-13", value: "ean13" }, { label: "Code 128", value: "code128" }, { label: "QR Code", value: "qr" }],
      default: "ean13", span: 1 },
    { name: "fields", label: "O que aparece", type: "multiselect", full: true, options: [
      { label: "Nome", value: "name" }, { label: "Preço", value: "price" }, { label: "Código de barras", value: "barcode" },
      { label: "SKU", value: "sku" }, { label: "Lote", value: "lot_number" }, { label: "Validade", value: "expires_at" },
      { label: "Fabricação", value: "manufactured_at" }, { label: "Quantidade", value: "quantity" },
      { label: "Endereço", value: "bin" }, { label: "Depósito", value: "warehouse" }, { label: "Volume (Vol 1/3)", value: "volume" },
      { label: "Conteúdo da caixa", value: "contents" }, { label: "Texto livre", value: "custom" }],
      hint: "Vazio = o padrão do tipo de etiqueta." },
    { name: "custom_text", label: "Texto livre", type: "text", full: true },
    { name: "is_default", label: "Modelo padrão", type: "boolean" },
    { name: "is_active", label: "Ativo", type: "boolean", default: true },
  ],
});

