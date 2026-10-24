/**
 * Fiscal: dados fiscais do emitente (CNPJ, certificado, CSC), notas emitidas e
 * as notas de ENTRADA que a SEFAZ entrega para os CNPJs (DF-e).
 *
 * Caminho da nota de entrada: Só resumo → (ciência) → Vincular itens →
 * Em conferência (a entrada de estoque já existe em rascunho) → Recebida.
 */
import { defineAsyncComponent } from "vue";

import { fiscalApi } from "@/api/fiscal";
import { resourceApi } from "@/api/resource";
import { money, quantity } from "@/utils/format";

import { choices, type ColumnDef, defineResource, linkTo, rowsOf, type Tone, UFS, yesNo } from "./types";

const CertificateDialog = defineAsyncComponent(() => import("@/components/fiscal/CertificateDialog.vue"));
const SefazSyncDialog = defineAsyncComponent(() => import("@/components/fiscal/SefazSyncDialog.vue"));
const NfeImportDialog = defineAsyncComponent(() => import("@/components/fiscal/NfeImportDialog.vue"));
const NfeDetail = defineAsyncComponent(() => import("@/components/fiscal/NfeDetail.vue"));

export const environment = choices({ "1": "Produção", "2": "Homologação" });
export const provider = choices({ manual: "Manual (sem transmissão)", focus_nfe: "Focus NFe", acbrlib: "ACBrLib" });
export const crt = choices({ "1": "Simples Nacional", "2": "Simples - excesso de sublimite", "3": "Regime normal" });

export const nfeStage = choices({
  summary: "Só resumo", pending_mapping: "Vincular itens", checking: "Em conferência",
  pending_receipt: "Pronta para entrada", received: "Recebida", cancelled: "Cancelada", ignored: "Ignorada",
});
export const stageTones: Record<string, Tone> = {
  summary: "neutral", pending_mapping: "warning", checking: "info", pending_receipt: "brand", received: "success",
  cancelled: "danger", ignored: "neutral",
};
export const manifestation = choices({
  none: "Sem manifestação", science: "Ciência", confirmed: "Confirmada", unknown: "Desconhecida",
  not_performed: "Não realizada", error: "Erro",
});
export const xmlStatus = choices({
  summary_only: "Só resumo", pending: "XML pendente", available: "XML completo", error: "Erro no XML",
});
export const receiving = choices({
  not_started: "Não recebida", partial: "Parcial", received: "Recebida", divergent: "Com divergência",
});
export const fiscalStatus = choices({ unknown: "—", authorized: "Autorizada", cancelled: "Cancelada", denied: "Denegada" });
export const invoiceStatus = choices({
  draft: "Rascunho", processing: "Em processamento", authorized: "Autorizada", rejected: "Rejeitada",
  cancelled: "Cancelada", error: "Erro de comunicação",
});
export const documentModel = choices({ "65": "NFC-e", "55": "NF-e" });
const invoiceTones: Record<string, Tone> = {
  authorized: "success", rejected: "danger", error: "danger", cancelled: "neutral", processing: "info", draft: "warning",
};

const FISCAL = { permission: "fiscal", module: "fiscal", group: "Fiscal" } as const;
const configRelation = { endpoint: "/fiscal/configs/" };

export const inboundColumns: ColumnDef[] = [
  { key: "number", label: "Nº", title: true },
  { key: "supplier_name", label: "Fornecedor" },
  { key: "issued_at", label: "Emissão", type: "datetime" },
  { key: "total", label: "Valor", type: "money", total: true },
  { key: "stage", label: "Etapa", type: "tag", map: nfeStage.map, tones: stageTones, sortable: false },
  { key: "manifestation", label: "Manifestação", type: "tag", map: manifestation.map,
    tones: { none: "neutral", error: "danger", science: "info", confirmed: "success" } },
  { key: "pending_count", label: "A vincular", sortable: false },
  { key: "store_name", label: "Loja" },
];

export const invoiceColumns: ColumnDef[] = [
  { key: "number", label: "Nº", title: true },
  { key: "document_model", label: "Modelo", type: "tag", map: documentModel.map },
  { key: "series", label: "Série" },
  { key: "status", label: "Situação", type: "tag", map: invoiceStatus.map,
    tones: { authorized: "success", rejected: "danger", error: "danger", cancelled: "neutral", processing: "info" } },
  { key: "recipient_name", label: "Destinatário" },
  { key: "total", label: "Valor", type: "money", total: true },
  { key: "created_at", label: "Emitida em", type: "datetime" },
];

export const fiscalConfigs = defineResource({
  ...FISCAL,
  name: "dados-fiscais",
  title: "Dados fiscais",
  singular: "dados fiscais",
  endpoint: "/fiscal/configs/",
  icon: "pi pi-id-card",
  ordering: "name",
  columns: [
    { key: "name", label: "Nome", title: true },
    { key: "cnpj", label: "CNPJ" },
    { key: "legal_name", label: "Razão social" },
    { key: "store_names", label: "Lojas", sortable: false },
    { key: "environment", label: "Ambiente", type: "tag", map: environment.map, tones: { "1": "success", "2": "warning" } },
    { key: "has_certificate", label: "Certificado", type: "boolean", sortable: false },
    { key: "certificate_valid_until", label: "Validade do A1", type: "date" },
    { key: "dfe_enabled", label: "Busca notas", type: "boolean" },
  ],
  filters: [
    { name: "environment", label: "Ambiente", type: "select", options: environment.options },
    { name: "dfe_enabled", label: "Busca notas", type: "boolean", options: yesNo },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  listActions: [
    { label: "Criar a partir das lojas", icon: "pi pi-building", success: "Dados fiscais criados a partir das lojas",
      confirm: "Criar os dados fiscais de cada loja com CNPJ que ainda não tem, copiando razão social, IE e endereço?",
      run: () => fiscalApi.fromStores() },
  ],
  sections: {
    Emitente: { icon: "pi pi-id-card", description: "Como a SEFAZ conhece a empresa. Lojas com o mesmo CNPJ usam o mesmo cadastro." },
    Endereço: { icon: "pi pi-map-marker", description: "Endereço do emitente na nota. A UF define o webservice da SEFAZ." },
    Lojas: { icon: "pi pi-building", description: "As lojas que emitem com este CNPJ e recebem as notas de entrada dele." },
    Emissão: { icon: "pi pi-send", description: "Ambiente, provedor e código de segurança (CSC) para NFC-e/NF-e." },
    "Notas de entrada": { icon: "pi pi-inbox",
      description: "Busca na SEFAZ tudo que foi emitido contra o CNPJ; com o certificado, baixa o XML e gera a entrada." },
  },
  fields: [
    { name: "name", label: "Nome (apelido)", type: "text", required: true, placeholder: "Ex.: Matriz", section: "Emitente" },
    { name: "cnpj", label: "CNPJ", type: "document", required: true, section: "Emitente" },
    { name: "legal_name", label: "Razão social", type: "text", required: true, span: 4, section: "Emitente" },
    { name: "trade_name", label: "Nome fantasia", type: "text", section: "Emitente" },
    { name: "state_registration", label: "Inscrição estadual", type: "text", section: "Emitente" },
    { name: "municipal_registration", label: "Inscrição municipal", type: "text", section: "Emitente" },
    { name: "crt", label: "Regime tributário", type: "select", options: crt.options, default: "1", section: "Emitente" },
    { name: "phone", label: "Telefone", type: "phone", section: "Emitente" },
    { name: "email", label: "E-mail", type: "email", section: "Emitente" },
    { name: "zip_code", label: "CEP", type: "cep", section: "Endereço" },
    { name: "street", label: "Logradouro", type: "text", span: 3, section: "Endereço" },
    { name: "number", label: "Número", type: "text", section: "Endereço" },
    { name: "complement", label: "Complemento", type: "text", section: "Endereço" },
    { name: "district", label: "Bairro", type: "text", section: "Endereço" },
    { name: "city", label: "Cidade", type: "text", section: "Endereço" },
    { name: "state", label: "UF", type: "select", options: UFS, required: true, section: "Endereço" },
    { name: "city_ibge", label: "Código IBGE", type: "text", mask: "9999999", section: "Endereço" },
    { name: "stores", label: "Lojas vinculadas", type: "multirelation", relation: { endpoint: "/stores/" }, full: true,
      default: [], section: "Lojas" },
    { name: "environment", label: "Ambiente", type: "segmented", options: environment.options, default: "2", section: "Emissão" },
    { name: "provider", label: "Provedor", type: "select", options: provider.options, default: "manual", section: "Emissão" },
    { name: "default_profile", label: "Perfil fiscal padrão", type: "relation", relation: { endpoint: "/fiscal/profiles/" },
      section: "Emissão" },
    { name: "csc_id", label: "ID do CSC", type: "text", maxLength: 6, section: "Emissão" },
    { name: "csc_token", label: "CSC (token)", type: "password", hint: "Fica guardado e não aparece de novo.", section: "Emissão" },
    { name: "dfe_enabled", label: "Buscar notas na SEFAZ", type: "boolean", default: true,
      hint: "A cada hora, as notas emitidas para este CNPJ", section: "Notas de entrada" },
    { name: "dfe_auto_science", label: "Ciência automática", type: "boolean", default: true,
      hint: "Libera o XML com os itens", section: "Notas de entrada" },
    { name: "dfe_auto_entry", label: "Entrada automática", type: "boolean", default: true,
      hint: "Itens vinculados viram entrada", section: "Notas de entrada" },
    { name: "is_active", label: "Ativo", type: "boolean", default: true, section: "Notas de entrada" },
  ],
  views: [
    { name: "entradas", label: "Notas de entrada", icon: "pi pi-inbox", module: "inbound_nfe", permission: "inbound_nfe.view",
      description: "Notas emitidas contra este CNPJ.",
      list: { endpoint: "/inbound-nfe/", params: (id) => ({ fiscal_config: id }), columns: inboundColumns,
              ordering: "-issued_at", rowLink: (row) => `/cadastros/notas-de-entrada/${row.id}` } },
    { name: "emitidas", label: "Notas emitidas", icon: "pi pi-send", description: "NFC-e e NF-e emitidas por este CNPJ.",
      list: { endpoint: "/fiscal/invoices/", params: (id) => ({ fiscal_config: id }), columns: invoiceColumns,
              ordering: "-created_at", rowLink: (row) => `/cadastros/notas-emitidas/${row.id}` } },
  ],
  formActions: [
    { label: "Certificado A1", icon: "pi pi-shield", dialog: CertificateDialog },
    { label: "Buscar notas agora", icon: "pi pi-cloud-download", dialog: SefazSyncDialog,
      visible: (v) => Boolean(v.dfe_enabled) },
  ],
});

export const invoices = defineResource({
  ...FISCAL,
  name: "notas-emitidas",
  title: "Notas emitidas",
  singular: "nota",
  feminine: true,
  endpoint: "/fiscal/invoices/",
  icon: "pi pi-send",
  readOnly: true,
  creatable: false,
  ordering: "-created_at",
  columns: invoiceColumns,
  tree: {
    hasChildren: () => true,
    children: async (row) => rowsOf(await resourceApi.get("/fiscal/invoices/", String(row.id)), "items")
      .map((i) => ({ id: i.id, number: i.description, series: i.ncm, recipient_name: `${quantity(i.quantity)} × ${money(i.unit_price)}`,
                     total: i.total })),
  },
  display: {
    badges: (v) => [
      { label: documentModel.map[String(v.document_model)] ?? "", icon: "pi pi-file" },
      { label: invoiceStatus.map[String(v.status)] ?? "", tone: invoiceTones[String(v.status)] },
      v.environment === "2" && { label: "Homologação", tone: "warning" },
    ],
    stats: [
      { label: "Total", icon: "pi pi-wallet", type: "money", value: (v) => v.total },
      { label: "Produtos", icon: "pi pi-box", type: "money", value: (v) => v.products_total },
      { label: "Itens", icon: "pi pi-list", value: (v) => rowsOf(v, "items").length },
      { label: "Tributos aprox.", icon: "pi pi-building-columns", type: "money", value: (v) => v.approx_tax_total },
    ],
    sections: [
      { title: "Emitente e destinatário", icon: "pi pi-id-card", description: "Quem emitiu (dados fiscais) e para quem.", items: [
        { label: "Emitente", key: "fiscal_config_name", link: (v) => linkTo("dados-fiscais", v.fiscal_config) },
        { label: "Loja", key: "store_name" },
        { label: "Destinatário", value: (v) => v.recipient_name || "Consumidor" },
        { label: "CPF/CNPJ", key: "recipient_document", type: "document" },
        { label: "Venda", value: (v) => (v.sale ? `Venda ${v.sale_number}` : null), link: (v) => linkTo("vendas", v.sale) },
      ] },
      { title: "Autorização na SEFAZ", icon: "pi pi-verified", description: "O que a SEFAZ respondeu: chave, protocolo e data.", items: [
        { label: "Modelo / série / número", value: (v) => `${documentModel.map[String(v.document_model)] ?? ""} ${v.series ?? "—"} / ${v.number ?? "—"}` },
        { label: "Ambiente", key: "environment", type: "tag", map: environment.map, tones: { "1": "success", "2": "warning" } },
        { label: "Protocolo", key: "protocol" },
        { label: "Chave de acesso", key: "access_key", span: "full" },
        { label: "Autorizada em", key: "authorized_at", type: "datetime" },
      ] },
      { title: "Retorno da SEFAZ", icon: "pi pi-exclamation-triangle", description: "Motivo da rejeição ou erro de comunicação.",
        visible: (v) => Boolean(v.error_message), items: [{ label: "Mensagem", key: "error_message", type: "textarea", span: "full",
                                                            tone: () => "danger" }] },
      { title: "Itens da nota", icon: "pi pi-list", description: "Produtos e a tributação de cada linha.",
        table: { rows: (v) => rowsOf(v, "items"), empty: "Nota sem itens.", columns: [
          { key: "line_number", label: "#" }, { key: "description", label: "Produto", title: true },
          { key: "ncm", label: "NCM" }, { key: "cfop", label: "CFOP" },
          { key: "quantity", label: "Qtd.", type: "quantity", total: true }, { key: "unit_price", label: "Preço", type: "money" },
          { key: "discount", label: "Desconto", type: "money", total: true }, { key: "total", label: "Total", type: "money", total: true },
        ] } },
    ],
    aside: [
      { title: "Valores", icon: "pi pi-calculator", items: [
        { label: "Produtos", key: "products_total", type: "money" },
        { label: "Desconto", value: (v) => -Number(v.discount_total ?? 0), type: "money", visible: (v) => Number(v.discount_total) > 0 },
        { label: "Frete", key: "freight_total", type: "money", visible: (v) => Number(v.freight_total) > 0 },
        { label: "Tributos aprox.", key: "approx_tax_total", type: "money" },
        { label: "Total da nota", key: "total", type: "money", strong: true },
      ] },
    ],
  },
  filters: [
    { name: "status", label: "Situação", type: "select", options: invoiceStatus.options },
    { name: "document_model", label: "Modelo", type: "select", options: documentModel.options },
    { name: "fiscal_config", label: "Emitente", type: "relation", relation: configRelation },
    { name: "created_at", label: "Período", type: "daterange" },
  ],
  sections: {
    Nota: { icon: "pi pi-file", description: "Retrato do que foi enviado à SEFAZ e do que ela respondeu." },
    Valores: { icon: "pi pi-dollar" },
  },
  fields: [
    { name: "document_model", label: "Modelo", type: "select", options: documentModel.options, section: "Nota" },
    { name: "series", label: "Série", type: "number", section: "Nota" },
    { name: "number", label: "Número", type: "number", section: "Nota" },
    { name: "status", label: "Situação", type: "select", options: invoiceStatus.options, section: "Nota" },
    { name: "environment", label: "Ambiente", type: "select", options: environment.options, section: "Nota" },
    { name: "fiscal_config_name", label: "Emitente", type: "text", section: "Nota" },
    { name: "access_key", label: "Chave de acesso", type: "text", span: 4, section: "Nota" },
    { name: "protocol", label: "Protocolo", type: "text", section: "Nota" },
    { name: "authorized_at", label: "Autorizada em", type: "datetime", section: "Nota" },
    { name: "recipient_name", label: "Destinatário", type: "text", section: "Nota" },
    { name: "recipient_document", label: "CPF/CNPJ do destinatário", type: "text", section: "Nota" },
    { name: "error_message", label: "Retorno / erro", type: "textarea", section: "Nota" },
    { name: "products_total", label: "Produtos", type: "money", section: "Valores" },
    { name: "discount_total", label: "Desconto", type: "money", section: "Valores" },
    { name: "freight_total", label: "Frete", type: "money", section: "Valores" },
    { name: "approx_tax_total", label: "Tributos aprox.", type: "money", section: "Valores" },
    { name: "total", label: "Total", type: "money", section: "Valores" },
  ],
});

export const inboundNfes = defineResource({
  name: "notas-de-entrada",
  title: "Notas de entrada",
  singular: "nota",
  feminine: true,
  endpoint: "/inbound-nfe/",
  permission: "inbound_nfe",
  module: "inbound_nfe",
  group: "Compras",
  icon: "pi pi-inbox",
  creatable: false,
  editable: false,
  deletable: false,
  ordering: "-issued_at",
  columns: inboundColumns,
  /** Nota abre os itens: descrição, produto vinculado (ou "a vincular") e o valor. */
  tree: {
    hasChildren: (row) => Number(row.item_count ?? 0) > 0,
    children: async (row) => rowsOf(await resourceApi.get("/inbound-nfe/", String(row.id)), "items")
      .map((i) => ({ id: i.id, number: i.description, supplier_name: i.variant_name ?? (i.ignored ? "Fora do estoque" : "A vincular"),
                     issued_at: undefined, total: i.total, pending_count: `${quantity(i.quantity)} ${i.unit}` })),
  },
  filters: [
    { name: "stage", label: "Etapa", type: "select", options: nfeStage.options },
    { name: "fiscal_config", label: "CNPJ", type: "relation", relation: configRelation },
    { name: "manifestation", label: "Manifestação", type: "select", options: manifestation.options },
    { name: "issued_at", label: "Emissão", type: "daterange" },
  ],
  listActions: [
    { label: "Importar XML", icon: "pi pi-upload", dialog: NfeImportDialog },
    { label: "Buscar na SEFAZ", icon: "pi pi-cloud-download", severity: "contrast", dialog: SefazSyncDialog },
  ],
  summary: NfeDetail,
  fields: [],
  views: [
    { name: "eventos", label: "Eventos", icon: "pi pi-history", description: "Manifestações enviadas e eventos da SEFAZ.",
      list: { endpoint: "/inbound-nfe/events/", params: (id) => ({ nfe: id }), ordering: "-created_at", searchable: false,
              columns: [
                { key: "created_at", label: "Quando", type: "datetime" },
                { key: "event_code", label: "Código" },
                { key: "description", label: "Evento", title: true },
                { key: "direction", label: "Direção", type: "tag", map: { sent: "Enviado", received: "Recebido" } },
                { key: "status", label: "Situação", type: "tag",
                  map: { accepted: "Aceito", rejected: "Rejeitado", pending: "Pendente", error: "Erro", sent: "Enviado",
                         ignored: "Ignorado" },
                  tones: { accepted: "success", rejected: "danger", error: "danger" } },
                { key: "protocol", label: "Protocolo" },
                { key: "reason", label: "Retorno" },
              ] } },
  ],
  rowActions: [
    { label: "Abrir entrada de estoque", icon: "pi pi-file-edit", visible: (row) => Boolean(row.entry),
      to: (row) => `/cadastros/documentos-de-estoque/${(row.entry as { id: string }).id}` },
  ],
});
