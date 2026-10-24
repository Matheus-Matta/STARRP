import { choices, defineResource, type FieldDef, yesNo } from "./types";

const storeScope: FieldDef = {
  name: "store", label: "Loja", type: "relation", relation: { endpoint: "/stores/" }, section: "Validade",
  hint: "Vazio = vale para todas as lojas (só quem acessa a rede inteira grava assim).",
};
const window: FieldDef[] = [
  { name: "is_enabled", label: "Ligado", type: "boolean", default: true, section: "Validade" },
  { name: "starts_at", label: "Começa em", type: "datetime", section: "Validade" },
  { name: "ends_at", label: "Termina em", type: "datetime", section: "Validade" },
];

export const couponKind = choices({ percent: "Percentual", amount: "Valor em reais", free_shipping: "Frete grátis" });

export const coupons = defineResource({
  name: "cupons",
  title: "Cupons",
  singular: "cupom",
  endpoint: "/promotions/coupons/",
  permission: "promotions",
  icon: "pi pi-ticket",
  group: "Promoções",
  searchable: true,
  columns: [
    { key: "code", label: "Código" },
    { key: "kind", label: "Tipo", type: "tag", map: couponKind.map },
    { key: "value", label: "Valor" },
    { key: "min_subtotal", label: "Mínimo", type: "money" },
    { key: "ends_at", label: "Termina", type: "datetime" },
    { key: "is_enabled", label: "Ligado", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: couponKind.options },
    { name: "is_enabled", label: "Ligado", type: "boolean", options: yesNo },
    { name: "store", label: "Loja", type: "relation", relation: { endpoint: "/stores/" } },
  ],
  fields: [
    { name: "code", label: "Código", type: "text", required: true, maxLength: 40, section: "Desconto",
      hint: "Guardado em MAIÚSCULAS: o cliente dita e o caixa digita." },
    { name: "name", label: "Nome interno", type: "text", section: "Desconto" },
    { name: "kind", label: "Tipo", type: "select", options: couponKind.options, default: "percent", section: "Desconto" },
    { name: "value", label: "Valor (% ou R$)", type: "money", required: true, section: "Desconto" },
    { name: "max_discount", label: "Teto do desconto (R$)", type: "money", section: "Desconto" },
    { name: "min_subtotal", label: "Compra mínima (sem frete)", type: "money", section: "Desconto" },
    { name: "usage_limit", label: "Usos no total (0 = ilimitado)", type: "number", default: 0, section: "Regras" },
    { name: "usage_limit_per_customer", label: "Usos por CPF (0 = ilimitado)", type: "number", default: 0, section: "Regras" },
    { name: "first_purchase_only", label: "Só primeira compra", type: "boolean", section: "Regras" },
    { name: "requires_document", label: "Exige CPF/CNPJ", type: "boolean", section: "Regras" },
    { name: "combines_with_promotions", label: "Acumula com promoção", type: "boolean", default: true, section: "Regras" },
    { name: "customer_groups", label: "Só para os grupos", type: "multirelation", relation: { endpoint: "/customers/groups/" }, section: "Regras" },
    ...window,
    storeScope,
  ],
});

export const discountTables = defineResource({
  name: "tabelas-de-desconto",
  title: "Tabelas de desconto",
  singular: "tabela",
  feminine: true,
  endpoint: "/promotions/tables/",
  permission: "promotions",
  icon: "pi pi-percentage",
  group: "Promoções",
  searchable: true,
  columns: [
    { key: "name", label: "Nome" },
    { key: "rule_count", label: "Regras", sortable: false },
    { key: "starts_at", label: "Começa", type: "datetime" },
    { key: "ends_at", label: "Termina", type: "datetime" },
    { key: "is_enabled", label: "Ligada", type: "boolean" },
  ],
  filters: [
    { name: "is_enabled", label: "Ligada", type: "boolean", options: yesNo },
    { name: "store", label: "Loja", type: "relation", relation: { endpoint: "/stores/" } },
  ],
  sections: {
    Validade: { icon: "pi pi-calendar", description: "Nome, quando a tabela vale e em qual loja." },
    Regras: { icon: "pi pi-sliders-h", description: "O que tem desconto e quanto. A ordem é a prioridade: "
      + "a 1ª regra que pega o produto vale." },
  },
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, section: "Validade" },
    { name: "description", label: "Descrição", type: "text", section: "Validade" },
    ...window,
    storeScope,
    { name: "rules", label: "Regras", type: "promotion-rules", default: [], section: "Regras" },
  ],
});

