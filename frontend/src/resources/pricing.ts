/**
 * Precificação (Vendas): o preço de cada produto comparado com o mercado.
 * Liga em Configurações da conta › Cosmos, onde a conta escolhe as fontes. Cada linha é o processo de um produto: a referência
 * do mercado, o que o custo permite e o novo preço esperando aprovação — nada muda no cadastro
 * sem Aprovar. A seção "Achados" lista cada oferta com valor e link, para conferir à mão. O botão "Regras" escolhe
 * quais produtos a leitura pega; o botão "Precificar" do produto lê só aquele.
 *
 * `competitorPrices` é a pesquisa da equipe. Fica fora do menu (o grupo dela não é um grupo do menu):
 * abre pelo botão "Preços de concorrentes" da Precificação.
 */
import { defineAsyncComponent } from "vue";

import { pricingApi } from "@/api/pricing";

import { choices, defineResource, linkTo, rowsOf } from "./types";

const ApprovePriceDialog = defineAsyncComponent(() => import("@/components/pricing/ApprovePriceDialog.vue"));
const ImportCompetitorPricesDialog = defineAsyncComponent(
  () => import("@/components/pricing/ImportCompetitorPricesDialog.vue"));
const PriceStanding = defineAsyncComponent(() => import("@/components/pricing/PriceStanding.vue"));
const PriceRulesDialog = defineAsyncComponent(() => import("@/components/pricing/PriceRulesDialog.vue"));

export const pricePosition = choices({ above: "Acima do mercado", inside: "No mercado", below: "Ótimo preço",
                                       unknown: "Sem dados" });
export const priceStatus = choices({ pending: "Aguardando aprovação", applied: "Preço aplicado", rejected: "Recusada",
                                     none: "Sem sugestão" });
/** O que a API devolve: nunca o nome da API usada. */
export const priceSource = choices({ manual: "Pesquisa da equipe", google_shopping: "Google Shopping", collaborative: "Banco colaborativo" });
const sourceTones = { manual: "brand", google_shopping: "info", collaborative: "info" } as const;
const worth = choices({ true: "Vale a pena", false: "Não vale" });
const positionTones = { above: "danger", inside: "info", below: "success", unknown: "neutral" } as const;
/** Quanto o preço está abaixo da mediana do mercado, em texto ("12,5%"). */
const belowBy = (v: Record<string, unknown>) => `${((1 - Number(v.price_index)) * 100).toLocaleString("pt-BR",
  { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const statusTones = { pending: "warning", applied: "success", rejected: "neutral", none: "neutral" } as const;
const pending = (v: Record<string, unknown>) => v.status === "pending" && !v.reading;
const reading = (v: Record<string, unknown>) => v.reading === true;
const index = (v: Record<string, unknown>) => (v.price_index ? `${Number(v.price_index).toLocaleString("pt-BR",
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×` : "—");

export const priceChecks = defineResource({
  name: "precificacao",
  title: "Precificação",
  singular: "precificação",
  feminine: true,
  endpoint: "/price-checks/",
  permission: "catalog",
  module: "pricing",
  icon: "pi pi-chart-scatter",
  group: "Vendas",
  ordering: "-checked_at",
  creatable: false,
  editable: false,
  deletable: false,
  readOnly: true,
  searchable: true,
  summary: PriceStanding,
  progress: { load: () => pricingApi.runStatus(), label: (done, total) => `Lendo o mercado: ${done} de ${total} produtos. Os itens aparecem aqui conforme ficam prontos, de 10 em 10.` },
  poll: { while: reading, done: "Precificação concluída",
          message: "Aguarde: estamos lendo o preço no mercado. Esta tela se atualiza sozinha quando terminar, e você pode sair e voltar depois." },
  columns: [
    { key: "product_name", label: "Produto", title: true },
    { key: "position", label: "Posição", type: "tag", map: pricePosition.map, tones: positionTones },
    { key: "current_price", label: "Seu preço", type: "money" },
    { key: "market_median", label: "Mediana do mercado", type: "money" },
    { key: "market_min", label: "Menor", type: "money", mobile: false },
    { key: "market_max", label: "Maior", type: "money", mobile: false },
    { key: "standing", label: "Nosso lugar", sortable: false },
    { key: "reading", label: "Leitura", type: "tag", map: { true: "Lendo o mercado", false: "Concluída" }, tones: { true: "info", false: "neutral" },
      mobile: false, sortable: false },
    { key: "suggested_price", label: "Novo preço", type: "money" },
    { key: "suggested_margin", label: "Margem nova", type: "percent", mobile: false },
    { key: "worth_it", label: "Custo", type: "tag", map: worth.map, tones: { true: "success", false: "danger" } },
    { key: "status", label: "Situação", type: "tag", map: priceStatus.map, tones: statusTones },
    { key: "checked_at", label: "Lido em", type: "datetime", mobile: false },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: priceStatus.options },
    { name: "position", label: "Posição", type: "select", options: pricePosition.options },
    { name: "worth_it", label: "Vale a pena", type: "boolean" },
    { name: "needs_review", label: "Precisa conferir", type: "boolean" },
  ],
  fields: [],
  display: {
    badges: (v) => [
      reading(v) ? { label: "Lendo o mercado", tone: "info", icon: "pi pi-spin pi-spinner" } : null,
      { label: pricePosition.map[String(v.position)] ?? "", tone: positionTones[v.position as keyof typeof positionTones],
        icon: v.position === "below" ? "pi pi-thumbs-up" : undefined },
      { label: priceStatus.map[String(v.status)] ?? "", tone: statusTones[v.status as keyof typeof statusTones] },
      v.needs_review ? { label: "Conferir ofertas", tone: "warning", icon: "pi pi-eye" } : null,
    ],
    stats: [
      { label: "Seu preço", value: (v) => v.current_price, type: "money", icon: "pi pi-tag" },
      { label: "Mediana do mercado", value: (v) => v.market_median, type: "money", icon: "pi pi-chart-line",
        hint: (v) => `Índice ${index(v)}` },
      { label: "Novo preço", value: (v) => v.suggested_price, type: "money", icon: "pi pi-sparkles",
        visible: (v) => Boolean(v.suggested_price),
        tone: (v) => (v.worth_it === false ? "danger" : "success") },
      { label: "Margem", value: (v) => v.suggested_margin ?? v.current_margin, type: "percent", icon: "pi pi-percentage",
        hint: (v) => (v.suggested_margin ? `hoje ${Number(v.current_margin ?? 0).toLocaleString("pt-BR")}%` : undefined) },
    ],
    sections: [
      { title: "Análise", icon: "pi pi-lightbulb", items: [
        { label: "Ótimo preço", value: (v) => `Seu preço está ${belowBy(v)} abaixo da mediana do mercado.`, span: "full", strong: true,
          visible: (v) => v.position === "below", tone: () => "success" },
        { label: "O que a Cosmos concluiu", key: "reason", span: "full", strong: true },
        { label: "Vale a pena aderir?", value: (v) => (v.worth_it === null || v.worth_it === undefined ? "Sem custo para decidir"
          : v.worth_it ? "Sim" : "Não"), tone: (v) => (v.worth_it === false ? "danger" : v.worth_it ? "success" : undefined) },
        { label: "Menor preço com a margem mínima", key: "floor_price", type: "money" },
        { label: "Revisão da Cosmos", key: "ai_note", span: "full", visible: (v) => Boolean(v.ai_note) },
        { label: "Falha na última leitura", key: "error", span: "full", visible: (v) => Boolean(v.error),
          tone: () => "danger" },
        { label: "A leitura não terminou", value: () => "Passou de 10 minutos sem resposta. Clique em \"Ler o mercado agora\" para tentar de novo; "
          + "se repetir, confira se o worker está rodando.", span: "full", visible: (v) => v.reading_stalled === true, tone: () => "danger" },
      ] },
      { title: "Mercado", icon: "pi pi-globe", description: "Só as ofertas do mesmo produto, sem as fora da curva.",
        items: [
          { label: "Menor", key: "market_min", type: "money" },
          { label: "P25 (mais baratos)", key: "market_p25", type: "money" },
          { label: "Mediana", key: "market_median", type: "money", strong: true },
          { label: "Média", key: "market_avg", type: "money" },
          { label: "P75", key: "market_p75", type: "money" },
          { label: "Maior", key: "market_max", type: "money" },
          { label: "Concorrentes usados", value: (v) => `${v.competitors ?? 0} de ${v.offers_found ?? 0} ofertas` },
          { label: "Confiança do pareamento", key: "confidence", type: "percent" },
          { label: "Espalhamento", key: "dispersion", type: "percent", hint: () => "(P75 − P25) ÷ mediana" },
        ] },
      { title: "O que foi pesquisado", icon: "pi pi-search", description: "As buscas da última leitura, na ordem em que rodaram. "
        + "O código de barras só é pesquisado se o título não trouxer nenhuma oferta aceita.",
      table: { rows: (v) => rowsOf(v, "searches"), empty: "Nenhuma busca registrada na última leitura.", columns: [
        { key: "query", label: "Pesquisado", title: true },
        { key: "source", label: "Fonte", type: "tag", map: priceSource.map, tones: sourceTones },
        { key: "offers", label: "Ofertas" },
        { key: "matched", label: "Do mesmo produto" },
      ] } },
      { title: "Achados", icon: "pi pi-list", description: "Tudo o que o mercado trouxe na última leitura, com o link para "
        + "conferir. Só as marcadas como usadas entram na referência.",
      table: { rows: (v) => rowsOf(v, "offers"), empty: "Nenhuma oferta na última leitura.", columns: [
        { key: "title", label: "Oferta", title: true },
        { key: "price", label: "Preço", type: "money" },
        { key: "used", label: "Usada", type: "boolean" },
        { key: "seller", label: "Vendedor" },
        { key: "url", label: "Link", type: "link" },
        { key: "query", label: "Pesquisado por" },
        { key: "source", label: "Fonte", type: "tag", map: priceSource.map, tones: sourceTones },
        { key: "match_score", label: "Pareamento", type: "percent" },
        { key: "match_reason", label: "Por quê" },
        { key: "observed_at", label: "Visto em", type: "datetime" },
      ] } },
    ],
    aside: [
      { title: "Produto", icon: "pi pi-box", items: [
        { label: "Produto", key: "product_name", link: (v) => linkTo("produtos", v.product) },
        { label: "SKU", key: "sku" },
        { label: "Preço no cadastro", key: "shelf_price", type: "money" },
        { label: "Custo", key: "cost", type: "money" },
        { label: "Margem atual", key: "current_margin", type: "percent" },
        { label: "Lido em", key: "checked_at", type: "datetime" },
        { label: "Fontes", key: "source", visible: (v) => Boolean(v.source) },
      ] },
      { title: "Decisão", icon: "pi pi-user-edit", visible: (v) => Boolean(v.decided_at), items: [
        { label: "Quem decidiu", key: "decided_by_name" },
        { label: "Quando", key: "decided_at", type: "datetime" },
        { label: "Preço anterior", key: "previous_price", type: "money", visible: (v) => Boolean(v.previous_price) },
        { label: "Preço aplicado", key: "applied_price", type: "money", visible: (v) => Boolean(v.applied_price) },
      ] },
    ],
  },
  formActions: [
    { label: "Aprovar novo preço", icon: "pi pi-check", severity: "success", permission: "catalog.manage", visible: pending,
      confirm: "Aplicar o preço sugerido no cadastro do produto?", success: "Preço aplicado",
      run: ({ id }) => pricingApi.approve(id) },
    { label: "Outro preço", icon: "pi pi-pencil", severity: "secondary", permission: "catalog.manage", visible: pending,
      dialog: ApprovePriceDialog },
    { label: "Recusar", icon: "pi pi-times", severity: "danger", permission: "catalog.manage", visible: pending,
      success: "Sugestão recusada", run: ({ id }) => pricingApi.reject(id) },
    { label: "Ler o mercado agora", icon: "pi pi-refresh", severity: "secondary", permission: "catalog.manage",
      visible: (v) => !reading(v), success: "Leitura iniciada. Aguarde", run: ({ id }) => pricingApi.refresh(id) },
  ],
  rowActions: [
    { label: "Aprovar novo preço", icon: "pi pi-check", permission: "catalog.manage", visible: pending,
      confirm: "Aplicar o preço sugerido no cadastro do produto?", success: "Preço aplicado",
      run: (row) => pricingApi.approve(String(row.id)) },
    { label: "Recusar", icon: "pi pi-times", danger: true, permission: "catalog.manage", visible: pending,
      success: "Sugestão recusada", run: (row) => pricingApi.reject(String(row.id)) },
  ],
  listActions: [
    { label: "Preços de concorrentes", icon: "pi pi-users", severity: "secondary", permission: "catalog.view",
      run: async () => {
        const { router } = await import("@/router");
        await router.push("/cadastros/precos-de-concorrentes");
      } },
    { label: "Regras", icon: "pi pi-filter", severity: "secondary", permission: "catalog.manage", dialog: PriceRulesDialog },
    { label: "Ler o mercado agora", icon: "pi pi-refresh", severity: "secondary", permission: "catalog.manage",
      success: "Leitura iniciada, de 10 em 10. A lista se atualiza sozinha", run: () => pricingApi.run() },
  ],
});

export const competitorPrices = defineResource({
  name: "precos-de-concorrentes",
  title: "Preços de concorrentes",
  singular: "preço de concorrente",
  endpoint: "/competitor-prices/",
  permission: "catalog",
  module: "pricing",
  icon: "pi pi-users",
  group: "Precificação",
  ordering: "-observed_on",
  searchable: true,
  columns: [
    { key: "product_name", label: "Produto", title: true },
    { key: "competitor", label: "Concorrente" },
    { key: "price", label: "Preço", type: "money" },
    { key: "observed_on", label: "Visto em", type: "date" },
    { key: "sku", label: "SKU", mobile: false },
    { key: "notes", label: "Observação", sortable: false, mobile: false },
  ],
  filters: [{ name: "variant", label: "Produto", type: "relation",
              relation: { endpoint: "/catalog/variants/", labelKey: "display_name" } }],
  sections: {
    Preço: { icon: "pi pi-tag", description: "O preço que você viu no concorrente. Vale o mais novo de cada um, por "
      + "60 dias, e a Precificação recalcula na hora." },
  },
  fields: [
    { name: "variant", label: "Produto", type: "relation", required: true, section: "Preço", span: 6,
      relation: { endpoint: "/catalog/variants/", labelKey: "display_name" } },
    { name: "competitor", label: "Concorrente", type: "text", required: true, maxLength: 120, section: "Preço", span: 3 },
    { name: "price", label: "Preço", type: "money", required: true, section: "Preço", span: 2 },
    { name: "observed_on", label: "Visto em", type: "date", section: "Preço", span: 1 },
    { name: "url", label: "Link", type: "text", section: "Preço", span: 6 },
    { name: "notes", label: "Observação", type: "text", maxLength: 200, section: "Preço", span: 6 },
  ],
  listActions: [
    { label: "Importar planilha", icon: "pi pi-upload", severity: "secondary", permission: "catalog.manage",
      dialog: ImportCompetitorPricesDialog },
  ],
});
