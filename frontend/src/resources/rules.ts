/**
 * Regras COMPARTILHADAS entre filiais (backend: models/rules.py). A conta nasce com uma
 * padrão de cada tipo; a filial escolhe a dela no cadastro (vazio = a padrão) e várias
 * filiais usam a mesma. A padrão, a última e a em uso não se excluem (o backend recusa).
 */
import { choices, defineResource } from "./types";
import type { ColumnDef, FieldDef, SectionDef } from "./types";

const ruleColumns: ColumnDef[] = [
  { key: "name", label: "Nome", title: true },
  { key: "is_default", label: "Padrão", type: "boolean" },
  { key: "store_count", label: "Filiais", sortable: false },
];

const RULE = "Regra";
const ruleSection: Record<string, SectionDef> = {
  [RULE]: { icon: "pi pi-sitemap", description: "Várias filiais podem usar a mesma regra: escolha no cadastro da filial. "
    + "Filial nova (ou sem escolha) fica com a padrão. Sempre há uma padrão: marcar esta desmarca a anterior." },
};
const ruleFields: FieldDef[] = [
  { name: "name", label: "Nome", type: "text", required: true, section: RULE, span: 4, placeholder: "Shopping, Quiosque…" },
  { name: "is_default", label: "Padrão", type: "boolean", default: false, section: RULE, span: 2,
    hint: "Filial nova fica com esta" },
  { name: "description", label: "Descrição", type: "textarea", section: RULE, full: true },
];

/** PDV, caixa e venda de cada filial. */
export const storeRules = defineResource({
  name: "regras-das-filiais",
  title: "Regras das filiais",
  singular: "regra da filial",
  feminine: true,
  endpoint: "/stores/rules/",
  permission: "settings",
  icon: "pi pi-sliders-h",
  group: "Configurações",
  columns: [...ruleColumns,
    { key: "require_open_cash_session", label: "Exige caixa", type: "boolean" },
    { key: "pdv_auto_lock", label: "Bloqueia parado", type: "boolean" }],
  sections: {
    ...ruleSection,
    Caixa: { icon: "pi pi-wallet", description: "Abertura, fechamento e bloqueio da tela do caixa." },
    Venda: { icon: "pi pi-shopping-cart", description: "O que o PDV pede e imprime na venda." },
  },
  fields: [
    ...ruleFields,
    { name: "require_open_cash_session", label: "Exige caixa aberto", type: "boolean", default: true, section: "Caixa", span: 3 },
    { name: "cash_closing_tolerance", label: "Tolerância no fechamento (R$)", type: "money", default: "0.50", section: "Caixa",
      span: 3, hint: "Diferença até este valor fecha direto; acima, vai para o gerente aprovar." },
    { name: "pdv_auto_lock", label: "Bloquear o caixa parado", type: "boolean", default: true, section: "Caixa", span: 3,
      hint: "Tela do PDV se bloqueia sozinha" },
    { name: "pdv_lock_minutes", label: "Bloquear depois de (min)", type: "number", default: 5, section: "Caixa", span: 3,
      hint: "De 1 a 120 min sem uso. Volta com a senha do operador (ou a de aprovação do caixa); o F12 bloqueia sempre.",
      visible: (v) => v.pdv_auto_lock !== false },
    { name: "require_seller", label: "Exige vendedor na venda", type: "boolean", default: false, section: "Venda", span: 3 },
    { name: "confirm_address_at_checkout", label: "Confirmar endereço antes do pagamento", type: "boolean", default: true,
      section: "Venda", span: 3, hint: "Confere entrega e cobrança no PDV" },
    { name: "auto_print_receipt", label: "Imprime recibo ao concluir", type: "boolean", default: true, section: "Venda", span: 3 },
    { name: "require_payment_reference", label: "Exige NSU/autorização no cartão e PIX", type: "boolean", default: false,
      section: "Venda", span: 3, hint: "Desligado, o campo aparece no pagamento mas é opcional" },
    { name: "print_cancellation_receipt", label: "Imprime comprovante de cancelamento", type: "boolean", default: false,
      section: "Venda", span: 3 },
    { name: "scale_barcode_mode", label: "Etiqueta de balança", type: "select", default: "", section: "Venda", span: 3,
      options: [{ label: "Não usa", value: "" }, { label: "Traz o preço", value: "price" }, { label: "Traz o peso", value: "weight" }] },
    { name: "scale_barcode_prefix", label: "Prefixo da etiqueta", type: "text", format: "digits2", default: "2", section: "Venda",
      span: 3, visible: (v) => Boolean(v.scale_barcode_mode) },
  ],
});

const labelPrint = choices({ auto: "Imprime sozinho", ask: "Pergunta o modelo", off: "Não imprime" });
const labelTemplates = (subjects: string) => ({ endpoint: "/stock/label-templates/",
                                                params: { subject__in: subjects, is_active: "true" } });

/** Recebimento e conferência de mercadoria. */
export const logisticsRules = defineResource({
  name: "regras-de-logistica",
  title: "Regras de logística",
  singular: "regra de logística",
  feminine: true,
  endpoint: "/logistics/rules/",
  permission: "logistics",
  icon: "pi pi-sliders-h",
  group: "Logística",
  columns: [...ruleColumns, { key: "allow_manual_conference", label: "Conferência manual", type: "boolean" },
    { key: "entry_labels", label: "Etiqueta na entrada", type: "tag", map: labelPrint.map }],
  sections: {
    ...ruleSection,
    Recebimento: { icon: "pi pi-inbox", description: "Como a mercadoria que chega (entrada da NF-e) é conferida." },
    Etiquetas: { icon: "pi pi-tags", description: "Qual etiqueta sai em cada etapa. Já vem com os modelos padrão do "
      + "sistema; \"Imprime sozinho\" manda direto para a impressora, sem perguntar." },
  },
  fields: [
    ...ruleFields,
    { name: "allow_manual_conference", label: "Permitir conferência manual no recebimento", type: "boolean",
      section: "Recebimento", full: true,
      hint: "Marca item a item se a quantidade está correta, sem ler os códigos" },
    { name: "conference_labels", label: "Ao concluir a conferência", type: "segmented", options: labelPrint.options,
      default: "auto", section: "Etiquetas", span: 3 },
    { name: "conference_label", label: "Modelo da conferência", type: "relation", section: "Etiquetas", span: 3,
      relation: labelTemplates("volume,product"), visible: (v) => v.conference_labels !== "off",
      hint: "Caixa (Vol 1/3) ou produto. Só imprime se houver o que etiquetar." },
    { name: "entry_labels", label: "Ao confirmar / aprovar a entrada", type: "segmented", options: labelPrint.options,
      default: "auto", section: "Etiquetas", full: true },
    { name: "entry_lot_label", label: "Entrada com lote", type: "relation", section: "Etiquetas", span: 3,
      relation: labelTemplates("lot"), visible: (v) => v.entry_labels !== "off",
      hint: "Validade e data de entrada (FIFO/FEFO)" },
    { name: "entry_product_label", label: "Entrada sem lote", type: "relation", section: "Etiquetas", span: 3,
      relation: labelTemplates("product"), visible: (v) => v.entry_labels !== "off", hint: "Uma por unidade" },
  ],
});

const picking = choices({ fefo: "FEFO - primeiro a vencer", fifo: "FIFO - primeiro a entrar" });

/** Política de estoque: lotes, vencidos e saldo negativo. */
export const stockRules = defineResource({
  name: "regras-de-estoque",
  title: "Regras de estoque",
  singular: "regra de estoque",
  feminine: true,
  endpoint: "/stock/rules/",
  permission: "stock",
  icon: "pi pi-sliders-h",
  group: "Estoque",
  columns: [...ruleColumns, { key: "picking_strategy", label: "Saída", type: "tag", map: picking.map },
    { key: "allow_negative_stock", label: "Negativo", type: "boolean" }],
  sections: {
    ...ruleSection,
    Estoque: { icon: "pi pi-box", description: "Ordem de saída dos lotes, vencidos e venda sem saldo." },
  },
  fields: [
    ...ruleFields,
    { name: "picking_strategy", label: "Ordem de saída", type: "select", options: picking.options, default: "fefo",
      section: "Estoque", span: 3 },
    { name: "expiry_warning_days", label: "Avisar vencimento com (dias)", type: "number", default: 7, section: "Estoque", span: 3 },
    { name: "block_expired", label: "Bloquear venda de lote vencido", type: "boolean", default: true, section: "Estoque", span: 3 },
    { name: "allow_negative_stock", label: "Permitir vender sem saldo", type: "boolean", default: false, section: "Estoque",
      span: 3, hint: "Estoque negativo" },
    { name: "fifo_by_entry", label: "Sem validade: sai o mais antigo", type: "boolean", default: true, section: "Estoque",
      span: 3, hint: "Guarda a data de entrada (FIFO)" },
  ],
});
