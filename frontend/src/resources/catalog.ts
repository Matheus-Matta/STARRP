import { resourceApi } from "@/api/resource";
import { MASKS } from "@/utils/masks";

import { choices, defineResource, yesNo } from "./types";
import { saleItemColumns, saleLink } from "./sales";
import { balanceColumns, lotColumns, movementColumns, stockLinks } from "./stock";

/** Como o produto se monta (espelha `Product.Type` do backend). */
export const productType = choices({
  simple: "Simples", variable: "Com variação (grade)", kit: "Kit / combo", service: "Serviço",
});
/** Para que a loja tem o item: é o "tipo do item" do SPED. */
export const productPurpose = choices({
  "00": "Mercadoria para revenda", "01": "Matéria-prima / insumo", "02": "Embalagem", "04": "Produção própria",
  "07": "Uso e consumo", "08": "Ativo imobilizado", "09": "Serviço", "99": "Outros",
});
export const saleMethod = choices({ unit: "Por unidade", weight: "Por peso (balança)", fraction: "Fracionado (metro, litro...)" });
export const units = choices({
  UN: "Unidade", KG: "Quilo", G: "Grama", L: "Litro", ML: "Mililitro", M: "Metro", M2: "Metro²", CX: "Caixa",
  PCT: "Pacote", PAR: "Par",
});

const stocks = (v: Record<string, unknown>) => !["kit", "service"].includes(String(v.type ?? "simple"));

export const products = defineResource({
  name: "produtos",
  views: [
    { name: "estoque", label: "Estoque", icon: "pi pi-chart-bar", permission: "stock.view", module: "stock",
      description: "Saldo de cada variação em cada depósito. Clique para ver o kardex.",
      list: { endpoint: "/stock/balances/", params: (id) => ({ variant__product: id }), columns: balanceColumns,
              ordering: "variant__product__name", rowLink: stockLinks.kardexLink } },
    { name: "movimentacoes", label: "Movimentações", icon: "pi pi-arrow-right-arrow-left", permission: "stock.view", module: "stock",
      description: "Kardex: toda entrada, saída, ajuste e transferência deste produto.",
      list: { endpoint: "/stock/movements/", params: (id) => ({ variant__product: id }), columns: movementColumns, ordering: "-created_at" } },
    { name: "vendas", label: "Vendas", icon: "pi pi-shopping-cart", permission: "sales.view",
      description: "Cada venda concluída que levou este produto, com cliente, vendedor e margem.",
      list: { endpoint: "/sales/items/", params: (id) => ({ variant__product: id, sale__status: "completed" }),
              columns: saleItemColumns, ordering: "-completed_at", rowLink: saleLink } },
    { name: "lotes", label: "Lotes", icon: "pi pi-calendar-clock", permission: "stock.view", module: "stock",
      list: { endpoint: "/stock/lots/", params: (id) => ({ variant__product: id }), columns: lotColumns, ordering: "expires_at" } },
  ],
  title: "Produtos",
  singular: "produto",
  endpoint: "/catalog/products/",
  permission: "catalog",
  icon: "pi pi-box",
  group: "Catálogo",
  searchable: true,
  ordering: "name",
  /** Produto com grade abre as variantes: cada linha com SKU, preço e situação da variação. */
  tree: {
    hasChildren: (row) => Number(row.variant_count ?? 0) > 1,
    children: async (row) => (await resourceApi.list("/catalog/variants/", { product: String(row.id), page_size: 200 }))
      .results.map((v) => ({ id: v.id, cover: v.image, sku: v.sku, name: v.name || v.display_name, price: v.price,
                             is_active: v.is_active, type: undefined })),
  },
  columns: [
    { key: "cover", label: "", type: "image", sortable: false },
    { key: "sku", label: "SKU" },
    { key: "name", label: "Produto", sortable: true, title: true },
    { key: "type", label: "Tipo", type: "tag", map: productType.map },
    { key: "category_name", label: "Categoria" },
    { key: "variant_count", label: "Variantes" },
    { key: "price", label: "Preço (a partir de)", type: "money" },
    { key: "is_active", label: "Ativo", type: "boolean" },
  ],
  filters: [
    { name: "type", label: "Tipo", type: "select", options: productType.options },
    { name: "tag", label: "Tag", type: "relation", relation: { endpoint: "/tags/", params: { scope: "product" }, valueKey: "name" } },
    { name: "category", label: "Categoria", type: "relation", relation: { endpoint: "/catalog/categories/" } },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  sections: {
    Identificação: { icon: "pi pi-id-card", description: "Nome, tipo e onde o produto aparece. Categoria e marca podem ser criadas aqui mesmo." },
    Imagens: { icon: "pi pi-images",
               description: "Fotos do produto. Arraste para mudar a ordem: a 1ª é a capa (lista, PDV e loja virtual)." },
    Grade: { icon: "pi pi-th-large",
             description: "Eixos e valores. A grade manda: combinação nova é criada e o que sair (eixo ou valor) sai das variantes." },
    Venda: { icon: "pi pi-shopping-cart", description: "SKU, preço, códigos de barras e caixas. Com grade, uma linha por variação." },
    Descrição: { icon: "pi pi-align-left", description: "Texto do produto para o cliente: o que é, para que serve, medidas." },
    "Ficha técnica": { icon: "pi pi-list-check",
                       description: "Campos personalizados (tempo de montagem, garantia, material...) e metacampos livres. "
                         + "Os marcados com ✓ aparecem na ficha técnica do PDV." },
    "SEO e loja virtual": { icon: "pi pi-globe", description: "Como o produto aparece no Google e o endereço dele na loja virtual." },
    Fiscal: { icon: "pi pi-file", description: "NCM, CEST e origem vão para a nota. O perfil traz CFOP e alíquotas." },
    Estoque: { icon: "pi pi-box", description: "Controle de saldo, lote e série, e a comissão do vendedor." },
  },
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, section: "Identificação", maxLength: 180, span: 4,
      placeholder: "Ex.: Camiseta Básica Algodão" },
    { name: "reference", label: "Referência", type: "text", maxLength: 60, section: "Identificação", span: 2,
      placeholder: "CAM01", hint: "Base do SKU das variantes." },
    { name: "type", label: "Tipo", type: "segmented", options: productType.options, default: "simple", section: "Identificação", full: true },
    { name: "category", label: "Categoria", type: "relation", relation: { endpoint: "/catalog/categories/" }, creatable: true,
      section: "Identificação" },
    { name: "brand", label: "Marca", type: "relation", relation: { endpoint: "/catalog/brands/" }, creatable: true,
      section: "Identificação" },
    { name: "unit", label: "Unidade", type: "select", options: units.options, default: "UN", section: "Identificação" },
    { name: "sale_method", label: "Como vende", type: "segmented", options: saleMethod.options, default: "unit",
      section: "Identificação", span: 4 },
    { name: "purpose", label: "Finalidade (SPED)", type: "select", options: productPurpose.options, default: "00",
      section: "Identificação" },
    { name: "tags", label: "Tags", type: "tags", section: "Identificação", full: true,
      tagSource: { endpoint: "/tags/", params: { scope: "product" } }, placeholder: "lançamento, verão… (Enter para adicionar)" },
    { name: "images", label: "Fotos", type: "images", default: [], section: "Imagens" },
    { name: "grid", label: "Eixos da grade", type: "grid", section: "Grade", visible: (v) => v.type === "variable",
      hint: "Ex.: Cor = Azul, Preto · Tamanho = P, M, G." },
    { name: "variants", label: "Variantes", type: "variants", section: "Venda" },
    { name: "description", label: "Descrição", type: "richtext", full: true, section: "Descrição",
      hint: "Aparece na loja virtual. Use títulos, listas e negrito para facilitar a leitura." },
    { name: "metafields", label: "Ficha técnica", type: "metafields", owner: "product", default: {}, section: "Ficha técnica" },
    { name: "slug", label: "Endereço amigável (slug)", type: "text", maxLength: 180, section: "SEO e loja virtual", span: 2,
      placeholder: "gerado pelo nome", hint: "Vazio = gerado pelo nome. Ex.: camiseta-basica." },
    { name: "seo_title", label: "Título no Google", type: "text", maxLength: 70, counter: true, section: "SEO e loja virtual",
      span: 4, placeholder: "Vazio = o nome" },
    { name: "seo_description", label: "Resumo no Google", type: "textarea", maxLength: 160, counter: true, full: true,
      section: "SEO e loja virtual", placeholder: "Uma ou duas frases que fazem a pessoa clicar." },
    { name: "seo_preview", label: "Como aparece no Google", type: "seo-preview", full: true, section: "SEO e loja virtual" },
    { name: "fiscal_profile", label: "Perfil fiscal", type: "relation", relation: { endpoint: "/fiscal/profiles/" },
      section: "Fiscal", span: 3 },
    { name: "ncm", label: "NCM", type: "text", mask: MASKS.ncm, section: "Fiscal", span: 1 },
    { name: "cest", label: "CEST", type: "text", mask: MASKS.cest, section: "Fiscal", span: 1 },
    { name: "origin", label: "Origem", type: "text", default: "0", maxLength: 1, section: "Fiscal", span: 1 },
    { name: "track_stock", label: "Controla estoque", type: "boolean", default: true, section: "Estoque", visible: stocks },
    { name: "track_lots", label: "Lote e validade", type: "boolean", section: "Estoque", visible: stocks },
    { name: "track_serial", label: "Número de série", type: "boolean", section: "Estoque", visible: stocks },
    { name: "commission_percent", label: "Comissão (%)", type: "percent", section: "Estoque",
      hint: "Vazio = usa a comissão do vendedor." },
    { name: "is_active", label: "Ativo", type: "boolean", default: true, section: "Estoque" },
  ],
});

export const categories = defineResource({
  name: "categorias",
  tree: { parent: "parent" },
  views: [
    { name: "produtos", label: "Produtos", icon: "pi pi-box",
      list: { endpoint: "/catalog/products/", params: (id) => ({ category: id }), ordering: "name",
              rowLink: (row) => `/cadastros/produtos/${row.id}`,
              columns: [{ key: "name", label: "Produto" }, { key: "sku", label: "SKU", sortable: false },
                        { key: "variant_count", label: "Variantes" }, { key: "price", label: "Preço", type: "money" },
                        { key: "is_active", label: "Ativo", type: "boolean" }] } },
  ],
  title: "Categorias",
  singular: "categoria",
  feminine: true,
  endpoint: "/catalog/categories/",
  permission: "catalog",
  icon: "pi pi-sitemap",
  group: "Catálogo",
  searchable: true,
  columns: [
    { key: "name", label: "Nome" },
    { key: "position", label: "Ordem" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "parent", label: "Categoria pai", type: "relation", relation: { endpoint: "/catalog/categories/" } },
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  sections: {
    Categoria: { icon: "pi pi-sitemap", description: "Nome, onde fica na árvore e a ordem no menu da loja." },
    Descrição: { icon: "pi pi-align-left", description: "Texto da página da categoria." },
    "SEO e loja virtual": { icon: "pi pi-globe", description: "Como a categoria aparece no Google e o endereço dela na loja." },
  },
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, section: "Categoria" },
    { name: "parent", label: "Categoria pai", type: "relation", relation: { endpoint: "/catalog/categories/" }, section: "Categoria" },
    { name: "position", label: "Ordem de exibição", type: "number", default: 0, section: "Categoria" },
    { name: "is_active", label: "Ativa", type: "boolean", default: true, section: "Categoria" },
    { name: "description", label: "Descrição", type: "richtext", full: true, section: "Descrição",
      hint: "Texto da página da categoria na loja virtual." },
    { name: "slug", label: "Endereço amigável (slug)", type: "text", maxLength: 180, section: "SEO e loja virtual", span: 2,
      placeholder: "gerado pelo nome", hint: "Vazio = gerado pelo nome. Ex.: camiseta-basica." },
    { name: "seo_title", label: "Título no Google", type: "text", maxLength: 70, counter: true, section: "SEO e loja virtual",
      span: 4, placeholder: "Vazio = o nome" },
    { name: "seo_description", label: "Resumo no Google", type: "textarea", maxLength: 160, counter: true, full: true,
      section: "SEO e loja virtual", placeholder: "Uma ou duas frases que fazem a pessoa clicar." },
    { name: "seo_preview", label: "Como aparece no Google", type: "seo-preview", full: true, section: "SEO e loja virtual" },
  ],
});

export const brands = defineResource({
  name: "marcas",
  views: [
    { name: "produtos", label: "Produtos", icon: "pi pi-box",
      list: { endpoint: "/catalog/products/", params: (id) => ({ brand: id }), ordering: "name",
              rowLink: (row) => `/cadastros/produtos/${row.id}`,
              columns: [{ key: "name", label: "Produto" }, { key: "sku", label: "SKU", sortable: false },
                        { key: "variant_count", label: "Variantes" }, { key: "price", label: "Preço", type: "money" },
                        { key: "is_active", label: "Ativo", type: "boolean" }] } },
  ],
  title: "Marcas",
  singular: "marca",
  feminine: true,
  endpoint: "/catalog/brands/",
  permission: "catalog",
  icon: "pi pi-tag",
  group: "Catálogo",
  searchable: true,
  columns: [
    { key: "name", label: "Nome" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "is_active", label: "Ativo", type: "boolean", options: yesNo },
  ],
  fields: [
    { name: "name", label: "Nome", type: "text", required: true },
    { name: "is_active", label: "Ativa", type: "boolean", default: true },
  ],
});

/** Tipo da regra do serviço (espelha `ServiceRule.Kind`). */
export const serviceRuleKind = choices({ category: "Por categoria", product: "Por produto" });

/**
 * Serviços oferecidos com o produto (montagem, garantia estendida, embalagem) — padrão
 * do StarHub. O serviço é um produto do tipo "Serviço"; a regra diz a quais produtos
 * ele vale (por categoria, com faixa de preço opcional, ou por produto) e o preço.
 * No PDV aparecem na vitrine do produto, para marcar junto.
 */
export const serviceRules = defineResource({
  name: "servicos",
  title: "Serviços oferecidos",
  singular: "regra de serviço",
  feminine: true,
  endpoint: "/catalog/service-rules/",
  permission: "catalog",
  icon: "pi pi-wrench",
  group: "Catálogo",
  searchable: true,
  columns: [
    { key: "service_name", label: "Serviço" },
    { key: "kind", label: "Vale para", type: "tag", map: serviceRuleKind.map },
    { key: "price", label: "Preço", type: "money" },
    { key: "default_price", label: "Preço padrão", type: "money" },
    { key: "position", label: "Ordem" },
    { key: "is_active", label: "Ativa", type: "boolean" },
  ],
  filters: [
    { name: "service", label: "Serviço", type: "relation", relation: { endpoint: "/catalog/products/", params: { type: "service" } } },
    { name: "kind", label: "Tipo", type: "select", options: serviceRuleKind.options },
    { name: "is_active", label: "Ativa", type: "boolean", options: yesNo },
  ],
  sections: {
    Serviço: { icon: "pi pi-wrench", description: "Qual serviço e quanto custa nesta regra." },
    "Vale para": { icon: "pi pi-filter", description: "Por categoria (com faixa de preço opcional, as subcategorias entram) ou produto a produto." },
  },
  fields: [
    { name: "service", label: "Serviço", type: "relation", required: true, section: "Serviço", span: 4,
      relation: { endpoint: "/catalog/products/", params: { type: "service" } },
      hint: "Produto do tipo Serviço (cadastre em Produtos → Tipo: Serviço)." },
    { name: "position", label: "Ordem", type: "number", default: 10, section: "Serviço", span: 2,
      hint: "Menor primeiro: o produto que cai em duas regras fica com a de menor ordem." },
    { name: "price", label: "Preço nesta regra", type: "money", section: "Serviço", span: 3,
      hint: "Vazio: vale o preço padrão do serviço." },
    { name: "is_active", label: "Ativa", type: "boolean", default: true, section: "Serviço", span: 3 },
    { name: "kind", label: "Tipo da regra", type: "segmented", options: serviceRuleKind.options, default: "category",
      section: "Vale para", full: true },
    { name: "categories", label: "Categorias", type: "multirelation", relation: { endpoint: "/catalog/categories/" },
      section: "Vale para", full: true, visible: (v) => v.kind !== "product" },
    { name: "price_min", label: "Preço do produto a partir de", type: "money", section: "Vale para", span: 3,
      visible: (v) => v.kind !== "product" },
    { name: "price_max", label: "Preço do produto até", type: "money", section: "Vale para", span: 3,
      visible: (v) => v.kind !== "product" },
    { name: "products", label: "Produtos", type: "multirelation", relation: { endpoint: "/catalog/products/" },
      section: "Vale para", full: true, visible: (v) => v.kind === "product" },
  ],
});
