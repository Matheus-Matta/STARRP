/** Cadastros de apoio de estoque, fiscal e financeiro. */
import { defineAsyncComponent } from "vue";

import { balanceColumns, movementColumns, stockLinks } from "./stock";
import { choices, defineResource, yesNo } from "./types";

const AccountStatementView = defineAsyncComponent(() => import("@/components/finance/AccountStatementView.vue"));

export const warehouseKind = choices({
  sales_floor: "Loja / área de venda", storage: "Depósito", damaged: "Avariados", maintenance: "Manutenção",
  disposal: "Descarte",
});

export const warehouses = defineResource({
  name: "depositos",
  tree: { parent: "parent" },
  views: [
    { name: "saldos", label: "Saldos", icon: "pi pi-chart-bar",
      list: { endpoint: "/stock/balances/", params: (id) => ({ warehouse: id }), columns: balanceColumns,
              ordering: "variant__product__name", rowLink: stockLinks.kardexLink } },
    { name: "movimentacoes", label: "Movimentações", icon: "pi pi-arrow-right-arrow-left",
      list: { endpoint: "/stock/movements/", params: (id) => ({ warehouse: id }), columns: movementColumns, ordering: "-created_at" } },
    { name: "enderecos", label: "Endereços", icon: "pi pi-th-large",
      list: { endpoint: "/stock/bins/", params: (id) => ({ warehouse: id }), ordering: "sequence",
              rowLink: (row) => `/cadastros/enderecos/${row.id}`,
              columns: [{ key: "code", label: "Endereço" }, { key: "kind", label: "Tipo" }, { key: "sequence", label: "Ordem" },
                        { key: "is_active", label: "Ativo", type: "boolean" }] } },
  ],
  title: "Depósitos",
  singular: "depósito",
  endpoint: "/stock/warehouses/",
  permission: "stock",
  icon: "pi pi-warehouse",
  group: "Logística",
  columns: [
    { key: "name", label: "Nome" },
    { key: "kind", label: "Tipo", type: "tag", map: warehouseKind.map },
    { key: "is_default", label: "Padrão do PDV", type: "boolean" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: warehouseKind.options },
    { name: "uses_bins", label: "Endereçamento (WMS)", type: "boolean", options: yesNo },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true },
    { name: "kind", label: "Tipo", type: "select", options: warehouseKind.options, default: "storage" },
    { name: "is_default", label: "O PDV baixa a venda daqui", type: "boolean" },
    { name: "is_active", label: "Ativo", type: "boolean", default: true },
  ],
});

export const fiscalProfiles = defineResource({
  name: "perfis-fiscais",
  title: "Perfis fiscais",
  singular: "perfil fiscal",
  endpoint: "/fiscal/profiles/",
  permission: "fiscal",
  icon: "pi pi-file",
  group: "Fiscal",
  columns: [
    { key: "name", label: "Nome" },
    { key: "cfop", label: "CFOP" },
    { key: "csosn", label: "CSOSN" },
    { key: "icms_rate", label: "ICMS", type: "percent" },
    { key: "is_default", label: "Padrão", type: "boolean" },
    { key: "is_system", label: "Pré-pronto", type: "boolean" },
  ],
  filters: [
    { name: "is_system", label: "Pré-pronto do sistema", type: "boolean", options: yesNo },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, section: "Regra" },
    { name: "cfop", label: "CFOP", type: "text", default: "5102", maxLength: 4, section: "Regra" },
    { name: "cfop_interstate", label: "CFOP interestadual", type: "text", maxLength: 4, section: "Regra" },
    { name: "csosn", label: "CSOSN (Simples)", type: "text", maxLength: 3, section: "Regra" },
    { name: "cst_icms", label: "CST ICMS (regime normal)", type: "text", maxLength: 2, section: "Regra" },
    { name: "icms_rate", label: "ICMS (%)", type: "percent", section: "Alíquotas" },
    { name: "pis_cst", label: "CST PIS", type: "text", default: "49", section: "Alíquotas" },
    { name: "pis_rate", label: "PIS (%)", type: "percent", section: "Alíquotas" },
    { name: "cofins_cst", label: "CST COFINS", type: "text", default: "49", section: "Alíquotas" },
    { name: "cofins_rate", label: "COFINS (%)", type: "percent", section: "Alíquotas" },
    { name: "approx_tax_rate", label: "Tributos aproximados (%)", type: "percent", section: "Alíquotas" },
    { name: "is_default", label: "Sugerido no cadastro de produto", type: "boolean", section: "Alíquotas" },
  ],
});

export const financialAccounts = defineResource({
  name: "contas-financeiras",
  views: [
    { name: "extrato", label: "Extrato", icon: "pi pi-file", component: AccountStatementView,
      description: "Saldo anterior, cada lançamento com o saldo corrido e o saldo final do período." },
    { name: "lancamentos", label: "Lançamentos", icon: "pi pi-list",
      list: { endpoint: "/finance/transactions/", params: (id) => ({ financial_account: id }), ordering: "-date",
              rowLink: (row) => `/cadastros/lancamentos/${row.id}`,
              columns: [{ key: "date", label: "Data", type: "date" }, { key: "description", label: "Descrição", title: true },
                        { key: "category_name", label: "Categoria" },
                        { key: "kind", label: "Tipo", type: "tag", map: { in: "Entrada", out: "Saída" } },
                        { key: "amount", label: "Valor", type: "money", total: true }] } },
  ],
  title: "Contas financeiras",
  singular: "conta",
  feminine: true,
  endpoint: "/finance/accounts/",
  permission: "finance",
  module: "finance",
  icon: "pi pi-briefcase",
  group: "Financeiro",
  columns: [
    { key: "name", label: "Nome" },
    { key: "kind", label: "Tipo", type: "tag", map: { cash: "Caixa", bank: "Banco", acquirer: "Adquirente", wallet: "Carteira" } },
    { key: "opening_balance", label: "Saldo inicial", type: "money" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: [{ label: "Caixa / cofre", value: "cash" }, { label: "Banco", value: "bank" }, { label: "Adquirente", value: "acquirer" }, { label: "Carteira", value: "wallet" }] },
    { name: "store", label: "Filial", type: "relation", relation: { endpoint: "/stores/" } },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true },
    { name: "kind", label: "Tipo", type: "select", default: "bank", options: [
      { label: "Caixa / cofre", value: "cash" }, { label: "Banco", value: "bank" },
      { label: "Adquirente", value: "acquirer" }, { label: "Carteira digital", value: "wallet" }] },
    { name: "bank_code", label: "Banco", type: "text" },
    { name: "agency", label: "Agência", type: "text" },
    { name: "account_number", label: "Conta", type: "text" },
    { name: "opening_balance", label: "Saldo inicial", type: "money" },
    { name: "is_active", label: "Ativa", type: "boolean", default: true },
  ],
});
