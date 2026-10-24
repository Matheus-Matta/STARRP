import { choices, defineResource, type FieldDef, type SectionDef, yesNo } from "./types";
import { installmentColumns } from "./finance";
import { saleColumns, saleItemColumns, saleLink } from "./sales";
import { documentColumns, stockLinks } from "./stock";

export const personType = choices({ F: "Pessoa física", J: "Pessoa jurídica" });
const isCompany = (v: Record<string, unknown>) => v.person_type === "J";

const party: FieldDef[] = [
  { name: "person_type", label: "Tipo", type: "segmented", options: personType.options, default: "F", section: "Identificação",
    span: 3 },
  { name: "document", label: "CPF / CNPJ", type: "document", section: "Identificação", span: 3 },
  { name: "name", label: "Nome / nome fantasia", type: "text", required: true, section: "Identificação", span: 6 },
  { name: "legal_name", label: "Razão social", type: "text", section: "Identificação", visible: isCompany, span: 4 },
  { name: "state_registration", label: "Inscrição estadual", type: "text", section: "Identificação", visible: isCompany },
  { name: "phone", label: "Telefone", type: "phone", section: "Contato", span: 3 },
  { name: "email", label: "E-mail", type: "email", section: "Contato", span: 3 },
  { name: "notes", label: "Observações", type: "textarea", full: true, section: "Contato" },
  { name: "is_active", label: "Ativo", type: "boolean", default: true, section: "Contato" },
];

const address: FieldDef[] = [
  { name: "zip_code", label: "CEP", type: "cep", section: "Endereço" },
  { name: "street", label: "Logradouro", type: "text", section: "Endereço", span: 4 },
  { name: "number", label: "Número", type: "text", section: "Endereço", span: 1 },
  { name: "complement", label: "Complemento", type: "text", section: "Endereço" },
  { name: "district", label: "Bairro", type: "text", section: "Endereço", span: 3 },
  { name: "city", label: "Cidade", type: "text", section: "Endereço", span: 3 },
  { name: "state", label: "UF", type: "text", maxLength: 2, section: "Endereço", span: 1 },
  { name: "city_ibge", label: "Código IBGE", type: "text", mask: "9999999", section: "Endereço" },
];

const sections: Record<string, SectionDef> = {
  Identificação: { icon: "pi pi-id-card", description: "CPF ou CNPJ é conferido na hora. Pessoa jurídica pede razão social e IE." },
  Contato: { icon: "pi pi-phone", description: "Como falar com a pessoa. As observações aparecem no PDV." },
  Crédito: { icon: "pi pi-wallet", description: "Grupos (criados aqui mesmo), tags e o limite para vender a prazo." },
  Endereço: { icon: "pi pi-map-marker", description: "Usado na nota fiscal e na entrega." },
  Endereços: { icon: "pi pi-map-marker",
               description: "Onde entregar. O CEP preenche o resto; o padrão (★) vem primeiro no PDV e na nota." },
  Metacampos: { icon: "pi pi-tags", description: "Campos personalizados do cliente e chave/valor livres (integrações)." },
};

export const customers = defineResource({
  name: "clientes",
  views: [
    { name: "compras", label: "Compras", icon: "pi pi-shopping-cart", permission: "sales.view",
      list: { endpoint: "/sales/", params: (id) => ({ customer: id }), columns: saleColumns, ordering: "-created_at",
              rowLink: (row) => `/cadastros/vendas/${row.id}` } },
    { name: "itens-comprados", label: "Itens comprados", icon: "pi pi-list", permission: "sales.view",
      list: { endpoint: "/sales/items/", params: (id) => ({ sale__customer: id, sale__status: "completed" }),
              columns: saleItemColumns, ordering: "-completed_at", rowLink: saleLink } },
    { name: "vale-troca", label: "Vale-troca", icon: "pi pi-wallet",
      description: "Créditos gerados nas devoluções e o que já foi usado (valor negativo).",
      list: { endpoint: "/customer-credits/", params: (id) => ({ customer: id }), ordering: "-created_at", searchable: false,
              columns: [{ key: "created_at", label: "Quando", type: "datetime" },
                        { key: "kind", label: "Tipo", type: "tag", map: { return: "Devolução", usage: "Uso em venda", adjustment: "Ajuste", expiration: "Expirou" } },
                        { key: "amount", label: "Valor", type: "money" }, { key: "expires_at", label: "Vale até", type: "date" },
                        { key: "notes", label: "Observação" }] } },
    { name: "a-receber", label: "A receber", icon: "pi pi-calendar", permission: "finance.view", module: "finance",
      list: { endpoint: "/finance/installments/", params: (id) => ({ title__customer: id }), columns: installmentColumns,
              ordering: "due_date", searchable: false, rowLink: (row) => `/cadastros/contas-a-receber/${row.title}` } },
  ],
  title: "Clientes",
  singular: "cliente",
  endpoint: "/customers/",
  permission: "partners",
  icon: "pi pi-users",
  group: "Vendas",
  searchable: true,
  ordering: "name",
  columns: [
    { key: "name", label: "Nome", sortable: true },
    { key: "document", label: "CPF / CNPJ" },
    { key: "phone", label: "Telefone" },
    { key: "credit_limit", label: "Limite crediário", type: "money" },
    { key: "credit_balance", label: "Vale-troca", type: "money" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "person_type", label: "Tipo", type: "select", options: personType.options },
    { name: "groups", label: "Grupo", type: "relation", relation: { endpoint: "/customers/groups/" } },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  sections,
  fields: [
    ...party,
    { name: "birth_date", label: "Nascimento", type: "date", section: "Identificação" },
    { name: "groups", label: "Grupos", type: "multirelation", relation: { endpoint: "/customers/groups/" }, creatable: true,
      section: "Crédito", span: 4 },
    { name: "credit_limit", label: "Limite do crediário", type: "money", section: "Crédito",
      hint: "0 = não vende a prazo." },
    { name: "tags", label: "Tags", type: "tags", section: "Crédito", full: true,
      tagSource: { endpoint: "/tags/", params: { scope: "customer" } }, placeholder: "vip, atacado… (Enter para adicionar)" },
    { name: "addresses", label: "Endereços", type: "addresses", default: [], section: "Endereços" },
    { name: "metafields", label: "Metacampos", type: "metafields", owner: "customer", default: {}, section: "Metacampos" },
  ],
});

export const customerGroups = defineResource({
  name: "grupos-de-clientes",
  title: "Grupos de clientes",
  singular: "grupo",
  endpoint: "/customers/groups/",
  permission: "partners",
  icon: "pi pi-bookmark",
  group: "Vendas",
  searchable: true,
  columns: [
    { key: "name", label: "Nome" },
    { key: "description", label: "Descrição" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true },
    { name: "description", label: "Descrição", type: "text" },
    { name: "color", label: "Cor do selo", type: "color", default: "#64748b" },
    { name: "is_active", label: "Ativo", type: "boolean", default: true },
  ],
});

export const suppliers = defineResource({
  name: "fornecedores",
  views: [
    { name: "entradas", label: "Entradas de estoque", icon: "pi pi-download", permission: "stock.view", module: "stock",
      list: { endpoint: "/stock/documents/", params: (id) => ({ supplier: id }), columns: documentColumns, ordering: "-number",
              rowLink: stockLinks.documentLink } },
    { name: "a-pagar", label: "A pagar", icon: "pi pi-calendar", permission: "finance.view", module: "finance",
      list: { endpoint: "/finance/installments/", params: (id) => ({ title__supplier: id }), columns: installmentColumns,
              ordering: "due_date", searchable: false, rowLink: (row) => `/cadastros/contas-a-pagar/${row.title}` } },
  ],
  title: "Fornecedores",
  singular: "fornecedor",
  endpoint: "/suppliers/",
  permission: "partners",
  icon: "pi pi-truck",
  group: "Compras",
  searchable: true,
  columns: [
    { key: "name", label: "Nome" },
    { key: "document", label: "CPF / CNPJ" },
    { key: "contact_name", label: "Contato" },
    { key: "phone", label: "Telefone" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  sections,
  filters: [
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    ...party.map((f) => (f.name === "person_type" ? { ...f, default: "J" } : f)),
    { name: "contact_name", label: "Pessoa de contato", type: "text", section: "Contato" },
    ...address,
  ],
});
