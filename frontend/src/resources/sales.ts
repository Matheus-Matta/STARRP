/**
 * Vendas (consulta): a lista de todas as vendas, o detalhe de cada uma e os itens.
 * As colunas daqui também servem às consultas de outros cadastros
 * ("compras do cliente", "vendas do produto", "vendas do turno").
 */
import { defineAsyncComponent } from "vue";

import { openPrint } from "@/utils/print";

import { http } from "@/api/http";
import { resourceApi } from "@/api/resource";
import { money, quantity } from "@/utils/format";

import { choices, type ColumnDef, defineResource, linkTo, rowsOf, type Tone } from "./types";

const ReviewLinkDialog = defineAsyncComponent(() => import("@/components/reviews/ReviewLinkDialog.vue"));

export const saleStatus = choices({ open: "Aberta", draft: "Pedido guardado", completed: "Concluída", cancelled: "Cancelada" });
/**
 * Os três status do pedido (padrão do StarHub) — o `status` acima é só o documento no caixa:
 * - geral: o reflexo de tudo, até o produto chegar no cliente (só "Concluído" quando entregue/retirado);
 * - pagamento; - entrega. Derivados no backend (`Sale.save`).
 */
export const overallStatus = choices({
  draft: "Pedido guardado", open: "Em atendimento", awaiting_payment: "Pagamento em andamento",
  awaiting_picking: "Aguardando separação", ready: "Pronto para entrega", in_transit: "Em rota de entrega",
  completed: "Concluído", returned: "Devolvido", cancelled: "Cancelado",
});
export const overallTones: Record<string, Tone> = {
  draft: "info", open: "warning", awaiting_payment: "warning", awaiting_picking: "brand", ready: "brand",
  in_transit: "info", completed: "success", returned: "neutral", cancelled: "danger",
};
export const paymentStatus = choices({
  pending: "A pagar", partial: "Pago em parte", paid: "Pago", partially_refunded: "Estorno parcial",
  refunded: "Estornado", cancelled: "Cancelado",
});
export const paymentTones: Record<string, Tone> = {
  pending: "warning", partial: "warning", paid: "success", partially_refunded: "info", refunded: "neutral", cancelled: "danger",
};
export const fulfillmentStatus = choices({
  pending: "Pendente", ready: "Separado", shipped: "Saiu para entrega", delivered: "Entregue",
  picked_up: "Retirado na loja", returned: "Devolvido", cancelled: "Cancelado",
});
export const fulfillmentTones: Record<string, Tone> = {
  pending: "warning", ready: "brand", shipped: "info", delivered: "success", picked_up: "success", returned: "neutral",
  cancelled: "danger",
};
/** Próxima etapa da entrega (pendente → separado → saiu → entregue). */
export const FULFILLMENT_FLOW = ["pending", "ready", "shipped", "delivered"];

const channel = choices({ pos: "PDV", mobile: "PDV móvel", backoffice: "Retaguarda", ecommerce: "Loja virtual" });

export const saleColumns: ColumnDef[] = [
  { key: "number", label: "Nº", title: true, width: "120px" },
  { key: "customer_name", label: "Cliente" },
  { key: "seller_name", label: "Vendedor", width: "130px" },
  { key: "item_count", label: "Itens", sortable: false, width: "70px" },
  { key: "total", label: "Total", type: "money", total: true },
  { key: "overall_status", label: "Status geral", type: "tag", map: overallStatus.map, tones: overallTones },
  { key: "payment_status", label: "Pagamento", type: "tag", map: paymentStatus.map, tones: paymentTones },
  { key: "fulfillment_status", label: "Entrega", type: "tag", map: fulfillmentStatus.map, tones: fulfillmentTones },
];

export const saleItemColumns: ColumnDef[] = [
  { key: "completed_at", label: "Data", type: "datetime" },
  { key: "sale_number", label: "Venda" },
  { key: "description", label: "Produto", title: true },
  { key: "customer_name", label: "Cliente" },
  { key: "seller_name", label: "Vendedor" },
  { key: "quantity", label: "Qtd.", type: "quantity", total: true },
  { key: "unit_price", label: "Preço", type: "money" },
  { key: "total", label: "Total", type: "money", total: true },
  { key: "margin", label: "Margem", type: "money", sortable: false, total: true },
];

/** Anda a entrega (a ação do backend preenche as etapas puladas e registra quem fez). */
const advance = (status: string, note = "") => async ({ id }: { id: string }) =>
  (await http.post(`/sales/${id}/fulfillment/`, { status, note })).data;
const isDelivery = (v: Record<string, unknown>) => v.status === "completed" && Boolean(v.shipping_address);
const step = (v: Record<string, unknown>) => FULFILLMENT_FLOW.indexOf(String(v.fulfillment_status));
export const saleLink = (row: Record<string, unknown>) => `/cadastros/vendas/${row.sale ?? row.id}`;

/** Nota fiscal do pedido (o backend manda a principal primeiro: a autorizada, se houver). */
type InvoiceSummary = {
  id: string; label: string; model_label: string; number: number | null; series: number | null; status: string;
  status_label: string; access_key: string; protocol: string; authorized_at: string | null; total: string; environment: string;
};
const invoicesOf = (v: Record<string, unknown>) => (v.invoices ?? []) as InvoiceSummary[];
const mainInvoice = (v: Record<string, unknown>) => invoicesOf(v)[0];
const INVOICE_TONES: Record<string, Tone> = {
  authorized: "success", processing: "info", draft: "warning", error: "danger", rejected: "danger", cancelled: "neutral",
};
const accessKey = (key: string) => key.replace(/(\d{4})(?=\d)/g, "$1 ");

/** Entrega lançada no pedido (metacampo do sistema `_entrega`). */
type Delivery = { table_name: string; lead_days: number | null; detail: string };
const delivery = (v: Record<string, unknown>) => ((v.metafields ?? {}) as Record<string, unknown>)._entrega as Delivery | undefined;

/** Itens na ordem do pedido, cada serviço (montagem, garantia) logo abaixo do item dele. */
function itemsWithServices(v: Record<string, unknown>) {
  const rows = rowsOf(v, "items");
  const ids = new Set(rows.map((i) => i.id));
  return rows.filter((i) => !i.parent_item || !ids.has(i.parent_item)).flatMap((item) => [
    item,
    ...rows.filter((s) => s.parent_item === item.id).map((s) => ({ ...s, description: `↳ ${s.description} (serviço)` })),
  ]);
}

export const sales = defineResource({
  name: "vendas",
  title: "Vendas",
  singular: "venda",
  feminine: true,
  endpoint: "/sales/",
  permission: "sales",
  icon: "pi pi-shopping-cart",
  group: "Vendas",
  readOnly: true,
  creatable: false,
  deletable: false,
  ordering: "-created_at",
  columns: saleColumns,
  /** Venda abre os itens: produto na coluna do número, quantidade em "Itens", desconto e total da linha. */
  tree: {
    hasChildren: (row) => Number(row.item_count ?? 0) > 0,
    children: async (row) => (await resourceApi.list("/sales/items/", { sale: String(row.id), page_size: 200, ordering: "position" }))
      .results.map((i) => ({ id: i.id, number: i.description, customer_name: i.sku, item_count: quantity(i.quantity),
                             discount: i.discount, total: i.total,
                             status: i.status === "cancelled" ? "cancelled" : undefined })),
  },
  display: {
    badges: (v) => [
      { label: overallStatus.map[String(v.overall_status)] ?? "", tone: overallTones[String(v.overall_status)] },
      { label: paymentStatus.map[String(v.payment_status)] ?? "", tone: paymentTones[String(v.payment_status)],
        icon: "pi pi-wallet" },
      { label: fulfillmentStatus.map[String(v.fulfillment_status)] ?? "", tone: fulfillmentTones[String(v.fulfillment_status)],
        icon: "pi pi-truck" },
      ...(mainInvoice(v) ? [{ label: `${mainInvoice(v)!.label} · ${mainInvoice(v)!.status_label}`,
                               tone: INVOICE_TONES[mainInvoice(v)!.status] ?? "neutral", icon: "pi pi-file" }] : []),
      { label: channel.map[String(v.channel)] ?? "", tone: "neutral", icon: "pi pi-desktop" },
    ],
    stats: [
      { label: "Total", icon: "pi pi-wallet", type: "money", value: (v) => v.total },
      { label: "Pago", icon: "pi pi-check-circle", type: "money", value: (v) => v.paid_amount,
        hint: (v) => (Number(v.change_amount) ? `troco ${money(v.change_amount)}` : undefined) },
      { label: "Itens", icon: "pi pi-list", value: (v) => rowsOf(v, "items").filter((i) => i.status !== "cancelled").length },
      { label: "Descontos", icon: "pi pi-percentage", type: "money", value: (v) => Number(v.discount ?? 0) + Number(v.coupon_discount ?? 0),
        visible: (v) => Number(v.discount ?? 0) + Number(v.coupon_discount ?? 0) > 0 },
    ],
    sections: [
      { title: "Andamento", icon: "pi pi-directions",
        description: "O status geral só fica Concluído quando o produto chega no cliente (entregue ou retirado).", items: [
          { label: "Status geral", key: "overall_status", type: "tag", map: overallStatus.map, tones: overallTones },
          { label: "Pagamento", key: "payment_status", type: "tag", map: paymentStatus.map, tones: paymentTones },
          { label: "Entrega", key: "fulfillment_status", type: "tag", map: fulfillmentStatus.map, tones: fulfillmentTones },
          { label: "Documento no caixa", key: "status", type: "tag", map: saleStatus.map },
          { label: "Concluída no caixa", key: "completed_at", type: "datetime", visible: (v) => Boolean(v.completed_at) },
          { label: "Separado em", key: "ready_at", type: "datetime", visible: (v) => Boolean(v.ready_at) },
          { label: "Saiu para entrega", key: "shipped_at", type: "datetime", visible: (v) => Boolean(v.shipped_at) },
          { label: "Entregue em", key: "delivered_at", type: "datetime", visible: (v) => Boolean(v.delivered_at) },
          { label: "Estornado", key: "refunded_amount", type: "money", visible: (v) => Number(v.refunded_amount) > 0 },
        ] },
      { title: "Nota fiscal", icon: "pi pi-file",
        description: (v) => (invoicesOf(v).length > 1 ? "A nota que vale; as outras tentativas estão logo abaixo." : "Documento fiscal emitido para o pedido."),
        visible: (v) => invoicesOf(v).length > 0, items: [
          { label: "Documento", value: (v) => mainInvoice(v)?.label ?? null, link: (v) => linkTo("notas-emitidas", mainInvoice(v)?.id) },
          { label: "Situação", value: (v) => mainInvoice(v)?.status_label ?? null },
          { label: "Valor", value: (v) => mainInvoice(v)?.total ?? null, type: "money" },
          { label: "Chave de acesso", span: "full", value: (v) => (mainInvoice(v)?.access_key ? accessKey(mainInvoice(v)!.access_key) : null) },
          { label: "Protocolo", value: (v) => mainInvoice(v)?.protocol || null },
          { label: "Autorizada em", value: (v) => mainInvoice(v)?.authorized_at ?? null, type: "datetime" },
          { label: "Ambiente", value: (v) => (mainInvoice(v) ? (mainInvoice(v)!.environment === "1" ? "Produção" : "Homologação (teste)") : null) },
        ] },
      { title: "Outras notas do pedido", icon: "pi pi-history", visible: (v) => invoicesOf(v).length > 1,
        table: { rows: (v) => invoicesOf(v).slice(1).map((i) => ({ ...i })), empty: "—", columns: [
          { key: "label", label: "Documento", title: true },
          { key: "status", label: "Situação", type: "tag", map: { authorized: "Autorizada", processing: "Em processamento",
            draft: "Rascunho", error: "Erro de comunicação", rejected: "Rejeitada", cancelled: "Cancelada" }, tones: INVOICE_TONES },
          { key: "total", label: "Valor", type: "money" }, { key: "authorized_at", label: "Autorizada em", type: "datetime" },
        ] } },
      { title: "Cliente", icon: "pi pi-user", description: "Para quem foi a venda (vazio = consumidor não identificado).", items: [
        { label: "Cliente", value: (v) => v.customer_name || "Consumidor", link: (v) => linkTo("clientes", v.customer) },
        { label: "CPF/CNPJ", key: "customer_document", type: "document" },
        { label: "Cupom", key: "coupon_code", visible: (v) => Boolean(v.coupon_code) },
      ] },
      { title: "Atendimento", icon: "pi pi-id-card", description: "Quem vendeu e em qual caixa.", items: [
        { label: "Vendedor", key: "seller_name" },
        { label: "Operador", key: "operator_name" },
        { label: "Canal", key: "channel", type: "tag", map: channel.map },
        { label: "Turno de caixa", value: (v) => (v.cash_session ? "Ver turno" : null),
          link: (v) => linkTo("turnos-de-caixa", v.cash_session) },
      ] },
      { title: "Itens", icon: "pi pi-list", description: "Item cancelado fica na lista, sem somar no total.",
        table: { rows: itemsWithServices, empty: "Venda sem itens.", columns: [
          { key: "description", label: "Produto", title: true }, { key: "sku", label: "SKU" },
          { key: "quantity", label: "Qtd.", type: "quantity", total: true }, { key: "unit_price", label: "Preço", type: "money" },
          { key: "discount", label: "Desconto", type: "money", total: true }, { key: "total", label: "Total", type: "money", total: true },
          { key: "status", label: "Situação", type: "tag", map: { active: "Ativo", cancelled: "Cancelado" },
            tones: { active: "success", cancelled: "danger" } },
        ] } },
      { title: "Pagamentos", icon: "pi pi-credit-card", description: "Como o cliente pagou.",
        table: { rows: (v) => rowsOf(v, "payments"), empty: "Sem pagamentos.", columns: [
          { key: "method_name", label: "Forma", title: true }, { key: "amount", label: "Valor", type: "money", total: true },
          { key: "tendered_amount", label: "Entregue", type: "money" }, { key: "change_amount", label: "Troco", type: "money" },
          { key: "installments", label: "Parcelas" }, { key: "nsu", label: "NSU" },
          { key: "authorization_code", label: "Autorização" },
          { key: "status", label: "Situação", type: "tag", map: { approved: "Aprovado", cancelled: "Cancelado", refunded: "Estornado" },
            tones: { approved: "success", cancelled: "danger", refunded: "warning" } },
        ] } },
      { title: "Entrega", icon: "pi pi-truck", description: "Endereço do cliente e o frete cobrado (vazio = retirada na loja).",
        visible: (v) => Boolean(v.shipping_address), items: [
          { label: "Endereço", span: "full", value: (v) => (v.shipping_address_detail as Record<string, string> | null)?.text ?? null },
          { label: "Referência", span: "full", value: (v) => (v.shipping_address_detail as Record<string, string> | null)?.reference || null,
            visible: (v) => Boolean((v.shipping_address_detail as Record<string, string> | null)?.reference) },
          { label: "Tabela de frete", value: (v) => delivery(v)?.table_name ?? null },
          { label: "Prazo", value: (v) => (delivery(v)?.lead_days === undefined ? null : `${delivery(v)!.lead_days} dia(s) útil(eis)`) },
          { label: "Frete", key: "freight", type: "money" },
          { label: "Cálculo", value: (v) => delivery(v)?.detail || null },
        ] },
      { title: "Metacampos", icon: "pi pi-tags", description: "Informações extras do pedido (integrações, anotações).",
        visible: (v) => Object.keys((v.metafields ?? {}) as object).some((k) => !k.startsWith("_")),
        table: { rows: (v) => Object.entries((v.metafields ?? {}) as Record<string, unknown>).filter(([k]) => !k.startsWith("_"))
          .map(([key, value]) => ({ id: key, key, value: typeof value === "object" ? JSON.stringify(value) : String(value) })),
                 columns: [{ key: "key", label: "Chave", title: true }, { key: "value", label: "Valor" }] } },
      { title: "Observações", icon: "pi pi-comment", visible: (v) => Boolean(v.notes || v.cancel_reason), items: [
        { label: "Motivo do cancelamento", key: "cancel_reason", span: "full", tone: () => "danger",
          visible: (v) => Boolean(v.cancel_reason) },
        { label: "Anotações", key: "notes", type: "textarea", span: "full", visible: (v) => Boolean(v.notes) },
      ] },
    ],
    aside: [
      { title: "Valores", icon: "pi pi-calculator", items: [
        { label: "Subtotal", key: "subtotal", type: "money" },
        { label: "Desconto", value: (v) => -Number(v.discount ?? 0), type: "money", visible: (v) => Number(v.discount) > 0 },
        { label: "Cupom", value: (v) => -Number(v.coupon_discount ?? 0), type: "money", visible: (v) => Number(v.coupon_discount) > 0 },
        { label: "Frete", key: "freight", type: "money", visible: (v) => Number(v.freight) > 0 },
        { label: "Total", key: "total", type: "money", strong: true },
        { label: "Pago", key: "paid_amount", type: "money" },
        { label: "Troco", key: "change_amount", type: "money", visible: (v) => Number(v.change_amount) > 0 },
        { label: "Falta pagar", key: "balance_due", type: "money", tone: () => "danger", visible: (v) => Number(v.balance_due) > 0 },
      ] },
    ],
  },
  filters: [
    { name: "overall_status", label: "Status geral", type: "select", options: overallStatus.options },
    { name: "payment_status", label: "Pagamento", type: "select", options: paymentStatus.options },
    { name: "fulfillment_status", label: "Entrega", type: "select", options: fulfillmentStatus.options },
    { name: "status", label: "Documento no caixa", type: "select", options: saleStatus.options },
    { name: "channel", label: "Canal", type: "select", options: channel.options },
    { name: "customer", label: "Cliente", type: "relation", relation: { endpoint: "/customers/" } },
    { name: "completed_at", label: "Período", type: "daterange" },
  ],
  sections: {
    Venda: { icon: "pi pi-shopping-cart", description: "Venda concluída não se edita: devolução e cancelamento ficam registrados." },
    Valores: { icon: "pi pi-wallet", description: "Como o total foi formado." },
  },
  fields: [
    { name: "number", label: "Número", type: "number", section: "Venda" },
    { name: "status", label: "Situação", type: "select", options: saleStatus.options, section: "Venda" },
    { name: "channel", label: "Canal", type: "select", options: channel.options, section: "Venda" },
    { name: "customer_name", label: "Cliente", type: "text", section: "Venda" },
    { name: "customer_document", label: "CPF/CNPJ", type: "text", section: "Venda" },
    { name: "seller_name", label: "Vendedor", type: "text", section: "Venda" },
    { name: "created_at", label: "Aberta em", type: "datetime", section: "Venda" },
    { name: "completed_at", label: "Concluída em", type: "datetime", section: "Venda" },
    { name: "cancel_reason", label: "Motivo do cancelamento", type: "text", section: "Venda", visible: (v) => Boolean(v.cancel_reason) },
    { name: "subtotal", label: "Subtotal", type: "money", section: "Valores" },
    { name: "discount", label: "Desconto", type: "money", section: "Valores" },
    { name: "coupon_discount", label: "Cupom", type: "money", section: "Valores" },
    { name: "freight", label: "Frete", type: "money", section: "Valores" },
    { name: "total", label: "Total", type: "money", section: "Valores" },
    { name: "paid_amount", label: "Pago", type: "money", section: "Valores" },
    { name: "change_amount", label: "Troco", type: "money", section: "Valores" },
  ],
  formActions: [
    { label: "Marcar separado", icon: "pi pi-box", run: advance("ready"), success: "Pedido separado.", permission: "logistics.manage",
      visible: (v) => isDelivery(v) && step(v) === 0 },
    { label: "Saiu para entrega", icon: "pi pi-truck", run: advance("shipped"), success: "Pedido saiu para entrega.",
      permission: "logistics.manage",
      visible: (v) => isDelivery(v) && step(v) >= 0 && step(v) < 2 },
    { label: "Entregue", icon: "pi pi-home", severity: "success", run: advance("delivered"), success: "Pedido entregue: concluído.",
      permission: "logistics.manage",
      confirm: "Confirmar que o pedido chegou no cliente? O status geral vira Concluído.",
      visible: (v) => isDelivery(v) && step(v) >= 0 && step(v) < 3 },
    // O cliente avalia os produtos e a entrega pelo celular (sem login): link + mensagem pronta para o WhatsApp.
    { label: "Link de avaliação", icon: "pi pi-star", visible: (v) => v.status === "completed", dialog: ReviewLinkDialog },
    { label: "Recibo (bobina)", icon: "pi pi-receipt", run: async ({ id }) => openPrint("venda", id, { formato: "80mm" }) },
    { label: "Imprimir A4", icon: "pi pi-print", run: async ({ id }) => openPrint("venda", id, { formato: "a4" }) },
  ],
  rowActions: [
    { label: "Imprimir", icon: "pi pi-print", run: async (row) => openPrint("venda", String(row.id)) },
  ],
  views: [
    { name: "itens", label: "Itens", icon: "pi pi-list",
      list: { endpoint: "/sales/items/", params: (id) => ({ sale: id }), ordering: "position", searchable: false,
              columns: [
                { key: "description", label: "Produto", title: true }, { key: "sku", label: "SKU" },
                { key: "quantity", label: "Qtd.", type: "quantity", total: true }, { key: "unit_price", label: "Preço", type: "money" },
                { key: "discount", label: "Desconto", type: "money", total: true }, { key: "total", label: "Total", type: "money", total: true },
                { key: "margin", label: "Margem", type: "money", sortable: false, total: true },
                { key: "status", label: "Situação", type: "tag", map: { active: "Ativo", cancelled: "Cancelado" } },
              ] } },
  ],
});
