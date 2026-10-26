/**
 * Financeiro: contas a receber/pagar (com parcelas e baixa), vencimentos,
 * lançamentos (com estorno), categorias e turnos de caixa (fechamento).
 */
import { defineAsyncComponent } from "vue";

import { financeApi } from "@/api/operations";
import { resourceApi } from "@/api/resource";
import { openPrint } from "@/utils/print";

import { saleColumns } from "./sales";
import { choices, type ColumnDef, defineResource, type FieldDef, linkTo, type ResourceDef, rowsOf, type Tone, yesNo } from "./types";

const CashReportDialog = defineAsyncComponent(() => import("@/components/finance/CashReportDialog.vue"));
const CashStatementView = defineAsyncComponent(() => import("@/components/finance/CashStatementView.vue"));

export const titleStatus = choices({ open: "Em aberto", partial: "Parcial", paid: "Pago", cancelled: "Cancelado" });
export const titleKind = choices({ receivable: "A receber", payable: "A pagar" });
const txKind = choices({ in: "Entrada", out: "Saída" });
const categoryKind = choices({ income: "Receita", expense: "Despesa" });
const sessionStatus = choices({
  open: "Aberto", pending_approval: "Aguardando gerente", closed: "Fechado", cancelled: "Cancelado",
});

const FINANCE = { permission: "finance", module: "finance", group: "Financeiro" } as const;
/** Contado e diferença só existem depois do fechamento (aberto ainda não contou a gaveta). */
const counted = (v: Record<string, unknown>) => ["closed", "pending_approval"].includes(String(v.status));
const titleTone: Record<string, Tone> = { open: "info", partial: "warning", paid: "success", cancelled: "neutral" };

export const installmentColumns: ColumnDef[] = [
  { key: "due_date", label: "Vencimento", type: "date" },
  { key: "title_description", label: "Título", title: true },
  { key: "number", label: "Parcela" },
  { key: "amount", label: "Valor", type: "money", total: true },
  { key: "paid_amount", label: "Pago", type: "money", total: true },
  { key: "status", label: "Situação", type: "tag", map: titleStatus.map },
];
const accounts = { endpoint: "/finance/accounts/", params: { is_active: "true" } };

/** Contas a receber e a pagar: o mesmo cadastro, mudando cliente/fornecedor e o tipo de categoria. */
function titles(kind: "receivable" | "payable"): ResourceDef {
  const receivable = kind === "receivable";
  const party: FieldDef = receivable
    ? { name: "customer", label: "Cliente", type: "relation", relation: { endpoint: "/customers/" }, section: "Título" }
    : { name: "supplier", label: "Fornecedor", type: "relation", relation: { endpoint: "/suppliers/" }, section: "Título" };
  return defineResource({
    ...FINANCE,
    name: receivable ? "contas-a-receber" : "contas-a-pagar",
    title: receivable ? "Contas a receber" : "Contas a pagar",
    singular: receivable ? "conta a receber" : "conta a pagar",
    feminine: true,
    endpoint: "/finance/titles/",
    params: { kind },
    icon: receivable ? "pi pi-arrow-down-left" : "pi pi-arrow-up-right",
    formActions: [{ label: "Imprimir", icon: "pi pi-print", run: async ({ id }) => openPrint("titulo", id) }],
    rowActions: [{ label: "Imprimir", icon: "pi pi-print", run: async (row) => openPrint("titulo", String(row.id)) }],
    deletable: false,
    ordering: "-issue_date",
    /** Título abre as parcelas: "Parcela 1/3" na descrição, vencimento, valor e situação. */
    tree: {
      hasChildren: () => true,
      children: async (row) => {
        const found = (await resourceApi.list("/finance/installments/", { title: String(row.id), ordering: "number", page_size: 200 })).results;
        return found.map((i) => ({ id: i.id, description: `Parcela ${i.number}/${found.length}`, next_due: i.due_date,
                                   total: i.amount, open_amount: (Number(i.amount) - Number(i.paid_amount)).toFixed(2), status: i.status }));
      },
    },
    display: {
      badges: (v) => [{ label: titleStatus.map[String(v.status)] ?? "", tone: titleTone[String(v.status)] }],
      stats: [
        { label: "Valor total", icon: "pi pi-wallet", type: "money", value: (v) => v.total },
        { label: receivable ? "Recebido" : "Pago", icon: "pi pi-check-circle", type: "money",
          value: (v) => Number(v.total) - Number(v.open_amount ?? 0), tone: () => "success" },
        { label: "Em aberto", icon: "pi pi-clock", type: "money", value: (v) => v.open_amount,
          tone: (v) => (Number(v.open_amount) > 0 ? "warning" : "success") },
        { label: "Próximo vencimento", icon: "pi pi-calendar", type: "date", value: (v) => v.next_due,
          visible: (v) => Boolean(v.next_due) },
      ],
      sections: [
        { title: "Título", icon: "pi pi-file", description: receivable ? "Quem deve e de onde veio a conta." : "Para quem e de onde veio a conta.",
          items: [
            { label: "Descrição", key: "description", span: "wide" },
            { label: "Nº documento", key: "document_number" },
            receivable
              ? { label: "Cliente", key: "customer_name", link: (v) => linkTo("clientes", v.customer) }
              : { label: "Fornecedor", key: "supplier_name", link: (v) => linkTo("fornecedores", v.supplier) },
            { label: "Categoria", key: "category_name", link: (v) => linkTo("categorias-financeiras", v.category) },
            { label: "Emissão", key: "issue_date", type: "date" },
            { label: "Venda de origem", value: (v) => (v.sale ? "Ver venda" : null), link: (v) => linkTo("vendas", v.sale) },
            { label: "NF-e de origem", value: (v) => (v.inbound_nfe ? "Ver nota" : null), link: (v) => linkTo("notas-de-entrada", v.inbound_nfe) },
          ] },
        { title: "Parcelas", icon: "pi pi-calendar", description: receivable ? "O que vence e o que já foi recebido." : "O que vence e o que já foi pago.",
          table: { rows: (v) => rowsOf(v, "installments"), empty: "Sem parcelas.", columns: [
            { key: "number", label: "Parcela", title: true }, { key: "due_date", label: "Vencimento", type: "date" },
            { key: "amount", label: "Valor", type: "money", total: true }, { key: "paid_amount", label: "Pago", type: "money", total: true },
            { key: "paid_at", label: "Pago em", type: "date" },
            { key: "status", label: "Situação", type: "tag", map: titleStatus.map, tones: titleTone },
          ] } },
        { title: "Observações", icon: "pi pi-comment", visible: (v) => Boolean(v.notes),
          items: [{ label: "Anotações", key: "notes", type: "textarea", span: "full" }] },
      ],
      aside: [
        { title: "Resumo", icon: "pi pi-calculator", items: [
          { label: "Situação", key: "status", type: "tag", map: titleStatus.map, tones: titleTone },
          { label: "Parcelas", value: (v) => rowsOf(v, "installments").length },
          { label: "Valor total", key: "total", type: "money" },
          { label: "Em aberto", key: "open_amount", type: "money", strong: true },
        ] },
      ],
    },
    columns: [
      { key: "description", label: "Descrição", title: true },
      { key: receivable ? "customer_name" : "supplier_name", label: receivable ? "Cliente" : "Fornecedor" },
      { key: "category_name", label: "Categoria" },
      { key: "issue_date", label: "Emissão", type: "date" },
      { key: "next_due", label: "Próx. vencimento", type: "date", sortable: false },
      { key: "total", label: "Total", type: "money", total: true },
      { key: "open_amount", label: "Em aberto", type: "money", sortable: false, total: true },
      { key: "status", label: "Situação", type: "tag", map: titleStatus.map },
    ],
    filters: [
      { name: "status", label: "Situação", type: "select", options: titleStatus.options },
      receivable
        ? { name: "customer", label: "Cliente", type: "relation", relation: { endpoint: "/customers/" } }
        : { name: "supplier", label: "Fornecedor", type: "relation", relation: { endpoint: "/suppliers/" } },
      { name: "issue_date", label: "Emissão", type: "daterange" },
    ],
    sections: {
      Título: { icon: "pi pi-file", description: receivable ? "Quem deve, quanto e em quantas vezes. As parcelas nascem ao salvar."
        : "Para quem, quanto e em quantas vezes. As parcelas nascem ao salvar." },
      Parcelas: { icon: "pi pi-calendar", description: receivable ? "Dê baixa ao receber: o dinheiro entra na conta escolhida."
        : "Dê baixa ao pagar: o dinheiro sai da conta escolhida." },
    },
    fields: [
      { name: "description", label: "Descrição", type: "text", required: true, maxLength: 255, span: 4, section: "Título" },
      { name: "document_number", label: "Nº documento", type: "text", maxLength: 60, section: "Título" },
      party,
      { name: "category", label: "Categoria", type: "relation", section: "Título",
        relation: { endpoint: "/finance/categories/", params: { kind: receivable ? "income" : "expense" } } },
      { name: "store", label: "Filial", type: "relation", relation: { endpoint: "/stores/" }, section: "Título" },
      { name: "total", label: "Valor total", type: "money", required: true, section: "Título" },
      { name: "installment_count", label: "Parcelas", type: "number", default: 1, createOnly: true, section: "Título",
        hint: "Mensais, a partir do 1º vencimento." },
      { name: "first_due", label: "1º vencimento", type: "date", createOnly: true, section: "Título" },
      { name: "notes", label: "Observações", type: "textarea", section: "Título" },
      { name: "installments", label: "Parcelas", type: "installments", section: "Parcelas", visible: (v) => Boolean(v.id) },
    ],
  });
}

export const receivables = titles("receivable");
export const payables = titles("payable");

export const installments = defineResource({
  ...FINANCE,
  name: "vencimentos",
  title: "Vencimentos",
  singular: "parcela",
  feminine: true,
  endpoint: "/finance/installments/",
  icon: "pi pi-calendar",
  readOnly: true,
  creatable: false,
  ordering: "due_date",
  searchable: false,
  rowLink: (row) => `/cadastros/${row.kind === "receivable" ? "contas-a-receber" : "contas-a-pagar"}/${row.title}`,
  columns: [
    { key: "due_date", label: "Vencimento", type: "date" },
    { key: "title_description", label: "Título", title: true },
    { key: "party_name", label: "Cliente / fornecedor", sortable: false },
    { key: "kind", label: "Tipo", type: "tag", map: titleKind.map },
    { key: "number", label: "Parcela" },
    { key: "amount", label: "Valor", type: "money", total: true },
    { key: "paid_amount", label: "Pago", type: "money", total: true },
    { key: "status", label: "Situação", type: "tag", map: titleStatus.map },
  ],
  filters: [
    { name: "title__kind", label: "Tipo", type: "select", options: titleKind.options },
    { name: "status", label: "Situação", type: "select", options: titleStatus.options },
    { name: "due_date", label: "Vence entre", type: "daterange" },
  ],
  fields: [],
});

export const transactions = defineResource({
  ...FINANCE,
  name: "lancamentos",
  display: {
    badges: (v) => [
      { label: txKind.map[String(v.kind)] ?? "", tone: v.kind === "in" ? "success" : "danger",
        icon: v.kind === "in" ? "pi pi-arrow-down-left" : "pi pi-arrow-up-right" },
      Boolean(v.is_reversal) && { label: "Estorno", tone: "warning", icon: "pi pi-undo" },
      Boolean(v.reconciled) && { label: "Conciliado", tone: "info", icon: "pi pi-check-square" },
    ],
    stats: [
      { label: "Valor", icon: "pi pi-wallet", type: "money", value: (v) => (v.kind === "out" ? -Number(v.amount) : v.amount),
        tone: (v) => (v.kind === "in" ? "success" : "danger"), hint: (v) => (v.kind === "in" ? "Entrou na conta" : "Saiu da conta") },
      { label: "Data", icon: "pi pi-calendar", type: "date", value: (v) => v.date },
      { label: "Conta", icon: "pi pi-building-columns", value: (v) => v.account_name },
    ],
    sections: [
      { title: "Lançamento", icon: "pi pi-wallet", description: "Lançamento não se edita: se estiver errado, estorne.", items: [
        { label: "Descrição", key: "description", span: "full" },
        { label: "Conta", key: "account_name", link: (v) => linkTo("contas-financeiras", v.financial_account) },
        { label: "Categoria", key: "category_name", link: (v) => linkTo("categorias-financeiras", v.category) },
        { label: "Tipo", key: "kind", type: "tag", map: txKind.map, tones: { in: "success", out: "danger" } },
      ] },
      { title: "Origem", icon: "pi pi-link", description: "O que gerou este lançamento.",
        visible: (v) => Boolean(v.sale || v.cash_session || v.installment || v.reversal_of || v.transfer_pair), items: [
          { label: "Venda", value: (v) => (v.sale ? "Ver venda" : null), link: (v) => linkTo("vendas", v.sale), visible: (v) => Boolean(v.sale) },
          { label: "Turno de caixa", value: (v) => (v.cash_session ? "Ver turno" : null), link: (v) => linkTo("turnos-de-caixa", v.cash_session),
            visible: (v) => Boolean(v.cash_session) },
          { label: "Estorno de", value: (v) => (v.reversal_of ? "Lançamento original" : null),
            link: (v) => linkTo("lancamentos", v.reversal_of), visible: (v) => Boolean(v.reversal_of) },
          { label: "Transferência", value: (v) => (v.transfer_pair ? "Lançamento da outra conta" : null),
            link: (v) => linkTo("lancamentos", v.transfer_pair), visible: (v) => Boolean(v.transfer_pair) },
          { label: "Baixa de parcela", value: (v) => (v.installment ? "Sim" : null), visible: (v) => Boolean(v.installment) },
        ] },
    ],
  },
  title: "Lançamentos",
  singular: "lançamento",
  endpoint: "/finance/transactions/",
  icon: "pi pi-list",
  editable: false,
  deletable: false,
  ordering: "-date",
  columns: [
    { key: "date", label: "Data", type: "date" },
    { key: "description", label: "Descrição", title: true },
    { key: "account_name", label: "Conta" },
    { key: "category_name", label: "Categoria" },
    { key: "kind", label: "Tipo", type: "tag", map: txKind.map },
    { key: "amount", label: "Valor", type: "money", total: true },
    { key: "is_reversal", label: "Estorno", type: "boolean", sortable: false },
  ],
  filters: [
    { name: "financial_account", label: "Conta", type: "relation", relation: accounts },
    { name: "kind", label: "Tipo", type: "select", options: txKind.options },
    { name: "category", label: "Categoria", type: "relation", relation: { endpoint: "/finance/categories/" } },
    { name: "date", label: "Período", type: "daterange" },
  ],
  sections: {
    Lançamento: { icon: "pi pi-wallet", description: "Despesa ou receita avulsa (sem título). Lançamento não se edita: errado, estorne." },
  },
  fields: [
    { name: "kind", label: "Tipo", type: "segmented", options: txKind.options, default: "out", section: "Lançamento" },
    { name: "financial_account", label: "Conta", type: "relation", relation: accounts, required: true, section: "Lançamento" },
    { name: "date", label: "Data", type: "date", required: true, default: new Date().toLocaleDateString("sv-SE"),
      section: "Lançamento" },
    { name: "description", label: "Descrição", type: "text", required: true, maxLength: 255, span: 4, section: "Lançamento" },
    { name: "amount", label: "Valor", type: "money", required: true, section: "Lançamento" },
    { name: "category", label: "Categoria", type: "relation", relation: { endpoint: "/finance/categories/" }, creatable: false,
      section: "Lançamento" },
  ],
  formActions: [
    { label: "Estornar", icon: "pi pi-undo", severity: "danger", visible: (v) => !v.is_reversal && !v.installment,
      confirm: "Estornar este lançamento? Um lançamento inverso é criado e os dois ficam no extrato.",
      success: "Lançamento estornado", run: ({ id }) => financeApi.reverse(id) },
  ],
});

export const financialCategories = defineResource({
  ...FINANCE,
  name: "categorias-financeiras",
  tree: { parent: "parent" },
  title: "Categorias financeiras",
  singular: "categoria",
  feminine: true,
  endpoint: "/finance/categories/",
  icon: "pi pi-sitemap",
  ordering: "name",
  columns: [
    { key: "code", label: "Código" },
    { key: "name", label: "Nome" },
    { key: "kind", label: "Tipo", type: "tag", map: categoryKind.map },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: categoryKind.options },
    { name: "is_active", label: "Ativa", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, span: 4 },
    { name: "code", label: "Código", type: "text", maxLength: 20 },
    { name: "kind", label: "Tipo", type: "segmented", options: categoryKind.options, default: "expense" },
    { name: "parent", label: "Categoria pai", type: "relation", relation: { endpoint: "/finance/categories/" } },
    { name: "is_active", label: "Ativa", type: "boolean", default: true },
  ],
});

export const cashSessions = defineResource({
  name: "turnos-de-caixa",
  display: {
    badges: (v) => [{ label: sessionStatus.map[String(v.status)] ?? "",
                      tone: ({ open: "warning", pending_approval: "info", closed: "success", cancelled: "danger" } as Record<string, Tone>)[String(v.status)] }],
    stats: [
      { label: "Troco inicial", icon: "pi pi-wallet", type: "money", value: (v) => v.opening_amount },
      { label: "Esperado na gaveta", icon: "pi pi-calculator", type: "money", value: (v) => (counted(v) ? v.expected_amount : v.expected_now ?? v.expected_amount),
        hint: (v) => (counted(v) ? undefined : "Até agora") },
      { label: "Contado", icon: "pi pi-inbox", type: "money", value: (v) => v.counted_amount, visible: counted },
      { label: "Diferença", icon: "pi pi-sort-alt", type: "money", value: (v) => v.difference, visible: counted,
        tone: (v) => (Number(v.difference) === 0 ? "success" : "danger"),
        hint: (v) => (Number(v.difference) === 0 ? "Gaveta fechou certinho" : Number(v.difference) > 0 ? "Sobrou dinheiro" : "Faltou dinheiro") },
    ],
    sections: [
      { title: "Turno", icon: "pi pi-inbox", description: "Qual caixa, quem operou e quando.", items: [
        { label: "Caixa", key: "register_name", link: (v) => linkTo("caixas", v.register) },
        { label: "Terminal", key: "terminal_label" },
        { label: "Operador", key: "opened_by_name" },
        { label: "Abertura", key: "opened_at", type: "datetime" },
        { label: "Fechamento", key: "closed_at", type: "datetime" },
      ] },
      { title: "Fechamento", icon: "pi pi-calculator", description: "Conferência da gaveta: o que o sistema esperava e o que foi contado.",
        visible: counted, items: [
          { label: "Esperado", key: "expected_amount", type: "money" },
          { label: "Contado", key: "counted_amount", type: "money" },
          { label: "Diferença", key: "difference", type: "money", strong: true,
            tone: (v) => (Number(v.difference) === 0 ? "success" : "danger") },
          { label: "Justificativa", key: "approval_reason", span: "full", visible: (v) => Boolean(v.approval_reason) },
        ] },
      { title: "Observações", icon: "pi pi-comment", visible: (v) => Boolean(v.notes),
        items: [{ label: "Anotações", key: "notes", type: "textarea", span: "full" }] },
    ],
  },
  views: [
    { name: "extrato", label: "Extrato do turno", icon: "pi pi-file",
      description: "Tudo o que aconteceu no turno: vendas, pagamentos, gaveta, itens e ocorrências.", component: CashStatementView },
    { name: "vendas", label: "Vendas", icon: "pi pi-shopping-cart", permission: "sales.view",
      list: { endpoint: "/sales/", params: (id) => ({ cash_session: id }), columns: saleColumns, ordering: "-created_at",
              rowLink: (row) => `/cadastros/vendas/${row.id}` } },
    { name: "gaveta", label: "Movimentos da gaveta", icon: "pi pi-inbox",
      list: { endpoint: "/cash/movements/", params: (id) => ({ session: id }), ordering: "created_at", searchable: false,
              columns: [{ key: "created_at", label: "Quando", type: "datetime" },
                        { key: "kind", label: "Tipo", type: "tag", map: { sale: "Venda em dinheiro", withdrawal: "Sangria",
                          supply: "Suprimento", refund: "Devolução", adjustment: "Ajuste" } },
                        { key: "amount", label: "Valor", type: "money", total: true },
                        { key: "status", label: "Situação", type: "tag", map: { pending: "Pendente", approved: "Aprovado", cancelled: "Cancelado" } },
                        { key: "reason", label: "Motivo" }, { key: "operator_name", label: "Operador", sortable: false }] } },
  ],
  title: "Turnos de caixa",
  singular: "turno",
  endpoint: "/cash/sessions/",
  permission: "cash",
  group: "Financeiro",
  icon: "pi pi-inbox",
  creatable: false,
  editable: false,
  deletable: false,
  searchable: false,
  ordering: "-opened_at",
  columns: [
    { key: "opened_at", label: "Abertura", type: "datetime" },
    { key: "register_name", label: "Caixa", title: true },
    { key: "opened_by_name", label: "Operador" },
    { key: "status", label: "Situação", type: "tag", map: sessionStatus.map },
    { key: "opening_amount", label: "Troco inicial", type: "money" },
    { key: "expected_amount", label: "Esperado", type: "money" },
    { key: "counted_amount", label: "Contado", type: "money" },
    { key: "difference", label: "Diferença", type: "money" },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: sessionStatus.options },
    { name: "register", label: "Caixa", type: "relation", relation: { endpoint: "/cash/registers/" } },
    { name: "opened_at", label: "Período", type: "daterange" },
  ],
  fields: [
    { name: "register_name", label: "Caixa", type: "text" },
    { name: "opened_by_name", label: "Operador", type: "text" },
    { name: "status", label: "Situação", type: "select", options: sessionStatus.options },
    { name: "opened_at", label: "Abertura", type: "datetime" },
    { name: "closed_at", label: "Fechamento", type: "datetime" },
    { name: "opening_amount", label: "Troco inicial", type: "money" },
    { name: "expected_amount", label: "Esperado", type: "money" },
    { name: "counted_amount", label: "Contado", type: "money" },
    { name: "difference", label: "Diferença", type: "money" },
    { name: "notes", label: "Observações", type: "textarea" },
  ],
  formActions: [
    { label: "Fechamento", icon: "pi pi-file", dialog: CashReportDialog },
    { label: "Imprimir", icon: "pi pi-print", run: async ({ id }) => openPrint("turno", id, { formato: "a4" }) },
    { label: "Z (bobina)", icon: "pi pi-receipt", run: async ({ id }) => openPrint("turno", id, { formato: "80mm" }) },
  ],
  rowActions: [
    { label: "Imprimir fechamento", icon: "pi pi-print", run: async (row) => openPrint("turno", String(row.id), { formato: "a4" }) },
  ],
});
