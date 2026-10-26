import { choices, defineResource, UFS, yesNo } from "./types";

export const paymentKind = choices({
  cash: "Dinheiro", credit_card: "Crédito", debit_card: "Débito", pix: "PIX", voucher: "Vale-refeição",
  store_credit: "Vale-troca", installment_plan: "Crediário", bank_slip: "Boleto", other: "Outro",
});

const storeKind = choices({
  headquarters: "Matriz", regional: "Regional", branch: "Filial", distribution: "Centro de distribuição",
});

/** Filiais (no banco, "Store"). Em árvore: a matriz abre e mostra quem responde a ela. */
export const stores = defineResource({
  name: "filiais",
  title: "Filiais",
  singular: "filial",
  feminine: true,
  endpoint: "/stores/",
  permission: "settings",
  icon: "pi pi-building",
  group: "Configurações",
  tree: { parent: "parent" },
  columns: [
    { key: "name", label: "Nome", title: true },
    { key: "kind", label: "Tipo", type: "tag", map: storeKind.map,
      tones: { headquarters: "brand", regional: "info", branch: "neutral", distribution: "warning" } },
    { key: "parent_name", label: "Responde a" },
    { key: "cnpj", label: "CNPJ" },
    { key: "city", label: "Cidade" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: storeKind.options },
    { name: "state", label: "UF", type: "select", options: UFS },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome fantasia", type: "text", required: true, section: "Empresa" },
    { name: "kind", label: "Tipo de unidade", type: "segmented", options: storeKind.options, default: "branch",
      section: "Hierarquia", full: true },
    { name: "parent", label: "Responde a", type: "relation", relation: { endpoint: "/stores/" }, section: "Hierarquia",
      hint: "A unidade acima desta (ex.: a filial responde à regional, a regional à matriz). Vazio = topo da rede." },
    { name: "legal_name", label: "Razão social", type: "text", section: "Empresa" },
    { name: "cnpj", label: "CNPJ", type: "document", section: "Empresa" },
    { name: "state_registration", label: "Inscrição estadual", type: "text", section: "Empresa" },
    { name: "fiscal_config", label: "Dados fiscais", type: "relation", relation: { endpoint: "/fiscal/configs/" },
      hint: "Emitente usado na emissão e na busca de notas de entrada.", section: "Empresa" },
    { name: "phone", label: "Telefone", type: "phone", section: "Empresa" },
    { name: "email", label: "E-mail", type: "email", section: "Empresa" },
    { name: "zip_code", label: "CEP", type: "cep", section: "Endereço" },
    { name: "street", label: "Logradouro", type: "text", section: "Endereço" },
    { name: "number", label: "Número", type: "text", section: "Endereço" },
    { name: "district", label: "Bairro", type: "text", section: "Endereço" },
    { name: "city", label: "Cidade", type: "text", section: "Endereço" },
    { name: "state", label: "UF", type: "text", maxLength: 2, section: "Endereço" },
    { name: "city_ibge", label: "Código IBGE", type: "text", mask: "9999999", section: "Endereço" },
    { name: "require_open_cash_session", label: "Exige caixa aberto", type: "boolean", default: true, section: "Operação" },
    { name: "cash_closing_tolerance", label: "Tolerância no fechamento (R$)", type: "money", section: "Operação" },
    { name: "cash_action_password", label: "Senha de ações do caixa", type: "password", section: "Operação",
      hint: "Autoriza sangria/desconto no PDV sem gerente presente. Em branco mantém a atual." },
    { name: "require_seller", label: "Exige vendedor na venda", type: "boolean", section: "Operação" },
    { name: "auto_print_receipt", label: "Imprime recibo ao concluir", type: "boolean", default: true, section: "Operação" },
    { name: "scale_barcode_mode", label: "Etiqueta de balança", type: "select", section: "Operação",
      options: [{ label: "Não usa", value: "" }, { label: "Traz o preço", value: "price" }, { label: "Traz o peso", value: "weight" }] },
    { name: "is_active", label: "Ativa", type: "boolean", default: true, section: "Operação" },
  ],
});

export const users = defineResource({
  name: "usuarios",
  title: "Usuários",
  singular: "usuário",
  endpoint: "/users/",
  permission: "users",
  icon: "pi pi-user",
  group: "Configurações",
  searchable: true,
  columns: [
    { key: "username", label: "Usuário" },
    { key: "first_name", label: "Nome" },
    { key: "roles_label", label: "Cargos", sortable: false },
    { key: "all_stores", label: "Todas as filiais", type: "boolean" },
    { key: "is_seller", label: "Vendedor", type: "boolean" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "role", label: "Cargo", type: "relation", relation: { endpoint: "/roles/" } },
    { name: "is_seller", label: "Vendedor", type: "boolean", options: yesNo },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "username", label: "Usuário (login)", type: "text", required: true, section: "Acesso" },
    { name: "password", label: "Senha", type: "password", section: "Acesso", hint: "Na edição, em branco mantém a atual." },
    { name: "first_name", label: "Nome", type: "text", section: "Acesso" },
    { name: "last_name", label: "Sobrenome", type: "text", section: "Acesso" },
    { name: "email", label: "E-mail", type: "email", section: "Acesso" },
    { name: "role", label: "Cargo principal", type: "relation", required: true, relation: { endpoint: "/roles/" },
      section: "Acesso" },
    { name: "extra_roles", label: "Outros cargos (somam permissões)", type: "multirelation", default: [],
      relation: { endpoint: "/roles/", params: { is_active: "true" } }, section: "Acesso", full: true,
      hint: "Ex.: Coordenador de logística + Assistente financeiro. Vale o maior nível e o maior desconto." },
    { name: "all_stores", label: "Acessa todas as filiais", type: "boolean", section: "Filiais" },
    { name: "stores", label: "Filiais que acessa", type: "multirelation", relation: { endpoint: "/stores/" },
      section: "Filiais", visible: (v) => !v.all_stores },
    { name: "default_store", label: "Filial padrão", type: "relation", relation: { endpoint: "/stores/" }, section: "Filiais" },
    { name: "is_seller", label: "É vendedor", type: "boolean", section: "Vendedor" },
    { name: "seller_code", label: "Código do vendedor", type: "text", section: "Vendedor", visible: (v) => Boolean(v.is_seller) },
    { name: "commission_percent", label: "Comissão (%)", type: "percent", section: "Vendedor", visible: (v) => Boolean(v.is_seller) },
    { name: "is_active", label: "Ativo", type: "boolean", default: true, section: "Vendedor" },
  ],
});

/**
 * Cargos FIXOS do sistema (o catálogo vem do backend e é sincronizado em toda conta): cobrem
 * o sistema todo por área e nível. A conta não cria cargo — combina cargos no usuário
 * (principal + outros) e só ajusta o desconto máximo e o "ativo".
 */
export const roles = defineResource({
  name: "cargos",
  title: "Cargos",
  singular: "cargo",
  endpoint: "/roles/",
  permission: "users",
  icon: "pi pi-shield",
  group: "Configurações",
  systemData: true,
  systemNote: "Cargos fixos do sistema, por área e nível. Para juntar áreas (ex.: logística + financeiro), some cargos "
    + "no usuário. Aqui a conta só ajusta o desconto máximo e desativa um cargo.",
  ordering: "-rank",
  searchable: true,
  columns: [
    { key: "name", label: "Cargo", title: true },
    { key: "area", label: "Área" },
    { key: "rank", label: "Nível" },
    { key: "description", label: "O que faz", sortable: false, width: "360px" },
    { key: "max_discount_percent", label: "Desconto máx.", type: "percent" },
    { key: "user_count", label: "Usuários", sortable: false },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "area", label: "Área", type: "select", options: ["Direção", "Vendas", "Estoque e compras", "Logística",
      "Financeiro", "Fiscal", "Marketing", "Patrimônio", "TI", "Auditoria"].map((a) => ({ label: a, value: a })) },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  sections: {
    Cargo: { icon: "pi pi-shield", description: "Cargo fixo do sistema. Para juntar áreas (ex.: logística + financeiro), "
      + "some cargos no usuário em vez de criar um novo." },
    "Ajustes da conta": { icon: "pi pi-sliders-h", description: "O que a sua empresa decide neste cargo." },
    Permissões: { icon: "pi pi-key", description: "Vêm do sistema e acompanham as atualizações." },
  },
  fields: [
    { name: "name", label: "Nome", type: "text", readOnly: true, section: "Cargo", span: 3 },
    { name: "area", label: "Área", type: "text", readOnly: true, section: "Cargo", span: 2 },
    { name: "rank", label: "Nível (o maior aprova o menor)", type: "number", readOnly: true, section: "Cargo", span: 1 },
    { name: "description", label: "O que faz", type: "textarea", readOnly: true, section: "Cargo", full: true },
    { name: "max_discount_percent", label: "Desconto máximo sem autorização (%)", type: "percent", section: "Ajustes da conta",
      span: 3 },
    { name: "is_active", label: "Ativo (pode ser atribuído)", type: "boolean", default: true, section: "Ajustes da conta", span: 3 },
    { name: "permission_names", label: "Permissões", type: "tags", full: true, readOnly: true, section: "Permissões" },
  ],
});


export const paymentMethods = defineResource({
  name: "formas-de-pagamento",
  title: "Formas de pagamento",
  singular: "forma de pagamento",
  feminine: true,
  endpoint: "/payment-methods/",
  systemData: true,
  permission: "settings",
  icon: "pi pi-credit-card",
  group: "Financeiro",
  columns: [
    { key: "name", label: "Nome" },
    { key: "kind", label: "Tipo", type: "tag", map: paymentKind.map },
    { key: "max_installments", label: "Parcelas" },
    { key: "fee_percent", label: "Taxa", type: "percent" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Tipo", type: "select", options: paymentKind.options },
    { name: "store", label: "Filial", type: "relation", relation: { endpoint: "/stores/" } },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true },
    { name: "kind", label: "Tipo", type: "select", required: true, options: paymentKind.options },
    { name: "max_installments", label: "Máximo de parcelas", type: "number", default: 1 },
    { name: "fee_percent", label: "Taxa da adquirente (%)", type: "percent" },
    { name: "settlement_days", label: "Dias para receber (D+N)", type: "number", default: 0 },
    { name: "requires_reference", label: "Pede NSU/autorização", type: "boolean" },
    { name: "opens_drawer", label: "Abre a gaveta", type: "boolean" },
    { name: "position", label: "Ordem no PDV", type: "number", default: 0 },
    { name: "is_active", label: "Ativa", type: "boolean", default: true },
  ],
});

export const cashRegisters = defineResource({
  name: "caixas",
  views: [
    { name: "turnos", label: "Turnos", icon: "pi pi-inbox",
      list: { endpoint: "/cash/sessions/", params: (id) => ({ register: id }), ordering: "-opened_at", searchable: false,
              rowLink: (row) => `/cadastros/turnos-de-caixa/${row.id}/extrato`,
              columns: [{ key: "opened_at", label: "Abertura", type: "datetime" }, { key: "opened_by_name", label: "Operador" },
                        { key: "status", label: "Situação", type: "tag", map: { open: "Aberto", pending_approval: "Aguardando gerente",
                          closed: "Fechado", cancelled: "Cancelado" } },
                        { key: "expected_amount", label: "Esperado", type: "money" }, { key: "counted_amount", label: "Contado", type: "money" },
                        { key: "difference", label: "Diferença", type: "money" }] } },
  ],
  title: "Caixas",
  singular: "caixa",
  endpoint: "/cash/registers/",
  permission: "settings",
  icon: "pi pi-wallet",
  group: "Financeiro",
  columns: [
    { key: "code", label: "Código" },
    { key: "name", label: "Nome" },
    { key: "operator_names", label: "Operadores", sortable: false },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "store", label: "Filial", type: "relation", relation: { endpoint: "/stores/" } },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  sections: {
    Caixa: { icon: "pi pi-wallet", description: "O caixa físico da filial (a gaveta)." },
    Operadores: { icon: "pi pi-users", description: "Só eles abrem, fazem sangria/suprimento e fecham este caixa. "
      + "Gerente e supervisor (quem aprova) assumem qualquer caixa da filial." },
  },
  fields: [
    { name: "code", label: "Código", type: "text", required: true, section: "Caixa", span: 2 },
    { name: "name", label: "Nome", type: "text", required: true, section: "Caixa", span: 3 },
    { name: "is_active", label: "Ativo", type: "boolean", default: true, section: "Caixa", span: 2 },
    { name: "operators", label: "Operadores do caixa", type: "multirelation", default: [], section: "Operadores", full: true,
      relation: { endpoint: "/users/", valueKey: "user_id", labelKey: "full_name", params: { is_active: "true" } },
      hint: "Quem não está aqui não vê este caixa no PDV." },
  ],
});

export const freightKind = choices({ zip_range: "Por faixa de CEP", distance: "Por distância (km)" });

/**
 * Tabelas de frete (padrão do StarHub): por faixa de CEP (valor/prazo da faixa que contém o
 * CEP — a mais estreita ganha) ou por distância (taxa fixa + km × preço, com mínimo e
 * distância máxima; km por estrada a partir do CEP de origem). No PDV, a entrega cota
 * todas as ativas para o endereço do cliente.
 */
export const freightTables = defineResource({
  name: "tabelas-de-frete",
  title: "Tabelas de frete",
  singular: "tabela de frete",
  feminine: true,
  endpoint: "/logistics/freight-tables/",
  permission: "logistics",
  icon: "pi pi-truck",
  group: "Logística",
  searchable: true,
  columns: [
    { key: "name", label: "Nome" },
    { key: "kind", label: "Forma", type: "tag", map: freightKind.map },
    { key: "range_count", label: "Faixas" },
    { key: "price_per_km", label: "Preço/km", type: "money" },
    { key: "lead_days", label: "Prazo (dias)" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "kind", label: "Forma", type: "select", options: freightKind.options },
    { name: "is_active", label: "Ativa", type: "boolean", options: yesNo },
  ],
  sections: {
    Tabela: { icon: "pi pi-truck", description: "Nome que o vendedor vê no PDV, a forma de cobrar e o prazo." },
    "Faixas de CEP": { icon: "pi pi-map", description: "Faixa dentro de faixa vale: a mais estreita ganha (Centro dentro de Capital)." },
    Distância: { icon: "pi pi-directions",
                 description: "Taxa fixa + km × preço, nunca abaixo do mínimo. Km por estrada a partir do CEP de origem "
                   + "(sem a rota, estimativa em linha reta × 1,3)." },
  },
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, section: "Tabela", span: 3, placeholder: "Motoboy, Caminhão…" },
    { name: "kind", label: "Forma de cobrar", type: "segmented", options: freightKind.options, default: "zip_range",
      section: "Tabela", span: 3 },
    { name: "lead_days", label: "Prazo (dias úteis)", type: "number", default: 0, section: "Tabela", span: 2 },
    { name: "store", label: "Só na filial", type: "relation", relation: { endpoint: "/stores/" }, section: "Tabela", span: 2,
      hint: "Vazio = todas as filiais." },
    { name: "position", label: "Ordem", type: "number", default: 0, section: "Tabela", span: 1 },
    { name: "is_active", label: "Ativa", type: "boolean", default: true, section: "Tabela", span: 1 },
    { name: "ranges", label: "Faixas", type: "zip-ranges", default: [], section: "Faixas de CEP", visible: (v) => v.kind !== "distance" },
    { name: "origin_zip", label: "CEP de origem", type: "cep", section: "Distância", visible: (v) => v.kind === "distance",
      hint: "De onde a entrega sai (filial ou depósito)." },
    { name: "price_per_km", label: "Preço por km", type: "money", section: "Distância", visible: (v) => v.kind === "distance" },
    { name: "fixed_fee", label: "Taxa fixa", type: "money", default: "0.00", section: "Distância", visible: (v) => v.kind === "distance" },
    { name: "min_value", label: "Valor mínimo", type: "money", default: "0.00", section: "Distância", visible: (v) => v.kind === "distance" },
    { name: "max_distance_km", label: "Distância máxima (km)", type: "measure", section: "Distância",
      visible: (v) => v.kind === "distance", hint: "Vazio = sem limite." },
  ],
});

export const metafieldOwner = choices({ product: "Produto", customer: "Cliente", sale: "Pedido" });
export const metafieldType = choices({ text: "Texto", number: "Número", boolean: "Sim/Não", select: "Lista de opções", date: "Data" });

/**
 * Campos personalizados (definições de metacampos): viram campo no formulário do produto,
 * cliente ou pedido e, no produto, linha da ficha técnica ("Tempo de montagem: 2 h").
 */
export const metafieldDefinitions = defineResource({
  name: "campos-personalizados",
  title: "Campos personalizados",
  singular: "campo personalizado",
  endpoint: "/metafield-definitions/",
  permission: "settings",
  icon: "pi pi-list-check",
  group: "Catálogo",
  searchable: true,
  columns: [
    { key: "name", label: "Campo" },
    { key: "owner", label: "Em", type: "tag", map: metafieldOwner.map },
    { key: "type", label: "Tipo", type: "tag", map: metafieldType.map },
    { key: "unit", label: "Unidade" },
    { key: "key", label: "Chave" },
    { key: "show_in_specs", label: "Ficha técnica", type: "boolean" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "owner", label: "Em", type: "select", options: metafieldOwner.options },
    { name: "type", label: "Tipo", type: "select", options: metafieldType.options },
  ],
  sections: {
    Campo: { icon: "pi pi-list-check", description: "Nome na tela, tipo do valor e unidade (h, meses, kg)." },
    Onde: { icon: "pi pi-filter", description: "Em que cadastro aparece. No produto, dá para limitar a categorias." },
  },
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, section: "Campo", span: 3, placeholder: "Tempo de montagem" },
    { name: "type", label: "Tipo", type: "select", options: metafieldType.options, default: "text", section: "Campo", span: 2 },
    { name: "unit", label: "Unidade", type: "text", section: "Campo", span: 1, placeholder: "h" },
    { name: "options", label: "Opções da lista", type: "tags", default: [], section: "Campo", full: true,
      visible: (v) => v.type === "select", placeholder: "3 meses, 12 meses… (Enter para adicionar)" },
    { name: "help_text", label: "Ajuda", type: "text", section: "Campo", full: true,
      placeholder: "Aparece embaixo do campo, para quem preenche." },
    { name: "key", label: "Chave", type: "text", section: "Campo", span: 3,
      hint: "Gerada pelo nome. É a chave em metafields (integrações)." },
    { name: "position", label: "Ordem", type: "number", default: 0, section: "Campo", span: 1 },
    { name: "owner", label: "Aparece em", type: "segmented", options: metafieldOwner.options, default: "product", section: "Onde", span: 3 },
    { name: "show_in_specs", label: "Na ficha técnica", type: "boolean", default: true, section: "Onde", span: 2,
      visible: (v) => v.owner === "product" },
    { name: "required", label: "Obrigatório", type: "boolean", default: false, section: "Onde", span: 1 },
    { name: "is_active", label: "Ativo", type: "boolean", default: true, section: "Onde", span: 1 },
    { name: "categories", label: "Só nas categorias", type: "multirelation", relation: { endpoint: "/catalog/categories/" },
      section: "Onde", full: true, visible: (v) => v.owner === "product", hint: "Vazio = todos os produtos. As de dentro entram." },
  ],
});

/** Logística de cada filial: uma linha por filial (nasce sozinha); só edita. */
export const logisticsSettings = defineResource({
  name: "configuracoes-de-logistica",
  title: "Configurações de logística",
  singular: "configuração de logística",
  feminine: true,
  endpoint: "/logistics/settings/",
  permission: "logistics",
  icon: "pi pi-sliders-h",
  group: "Logística",
  creatable: false,
  deletable: false,
  searchable: false,
  columns: [
    { key: "store_name", label: "Filial", title: true },
    { key: "allow_manual_conference", label: "Conferência manual", type: "boolean" },
  ],
  sections: {
    Recebimento: { icon: "pi pi-inbox", description: "Como a mercadoria que chega (entrada da NF-e) é conferida nesta filial." },
  },
  fields: [
    { name: "store_name", label: "Filial", type: "text", readOnly: true, section: "Recebimento" },
    { name: "allow_manual_conference", label: "Permitir conferência manual no recebimento", type: "boolean",
      section: "Recebimento", full: true,
      hint: "Marca item a item se a quantidade está correta, sem ler os códigos com leitor ou câmera. "
        + "Desligado, a entrada da nota só é conferida lendo cada item." },
  ],
});
