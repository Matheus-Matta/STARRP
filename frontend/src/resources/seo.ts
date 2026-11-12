/**
 * Analítico de SEO (Vendas): a nota do cadastro de cada produto, o que melhorar e sugestões para aprovar.
 * Mesmo jeito da Precificação: a análise roda no worker e nada muda no cadastro sem aprovação. A nota mede o preenchimento:
 * não promete posição no Google.
 */
import { defineAsyncComponent } from "vue";

import { seoApi } from "@/api/seo";

import { choices, defineResource, linkTo, rowsOf } from "./types";

const SeoSuggestions = defineAsyncComponent(() => import("@/components/seo/SeoSuggestions.vue"));
const SeoRulesDialog = defineAsyncComponent(() => import("@/components/seo/SeoRulesDialog.vue"));

export const seoStatus = choices({ pending: "Aguardando aprovação", applied: "Sugestões aplicadas", rejected: "Recusada", none: "Sem sugestão" });
const statusTones = { pending: "warning", applied: "success", rejected: "neutral", none: "neutral" } as const;
const severity = choices({ warning: "Melhorar", info: "Dica" });
const origin = choices({ regra: "Boas práticas", busca: "Dados de busca do Google", ia: "Cosmos" });
const competition = choices({ LOW: "Baixa", MEDIUM: "Média", HIGH: "Alta", UNSPECIFIED: "—", UNKNOWN: "—" });
const reading = (v: Record<string, unknown>) => v.reading === true;
const pending = (v: Record<string, unknown>) => v.status === "pending" && !v.reading;
const scoreTone = (v: Record<string, unknown>) => {
  if (v.score === null || v.score === undefined) return undefined;
  const score = Number(v.score);
  return score >= 80 ? "success" : score >= 50 ? "warning" : "danger";
};

export const seoChecks = defineResource({
  name: "analitico-seo",
  title: "Analítico de SEO",
  singular: "análise de SEO",
  feminine: true,
  endpoint: "/seo-checks/",
  permission: "catalog",
  module: "seo",
  icon: "pi pi-search-plus",
  group: "Vendas",
  ordering: "score",
  creatable: false,
  editable: false,
  deletable: false,
  readOnly: true,
  searchable: true,
  summary: SeoSuggestions,
  progress: { load: () => seoApi.runStatus(), label: (done, total) => `Analisando: ${done} de ${total} produtos. Os itens aparecem aqui conforme ficam prontos, de 10 em 10.` },
  poll: { while: reading, done: "Análise concluída",
          message: "Aguarde: estamos analisando o cadastro. Esta tela se atualiza sozinha quando terminar, e você pode sair e voltar depois." },
  columns: [
    { key: "product_name", label: "Produto", title: true },
    { key: "score", label: "Nota" },
    { key: "issues_count", label: "Pontos a melhorar" },
    { key: "suggestions_count", label: "Sugestões" },
    { key: "status", label: "Situação", type: "tag", map: seoStatus.map, tones: statusTones },
    { key: "reading", label: "Análise", type: "tag", map: { true: "Analisando", false: "Concluída" }, tones: { true: "info", false: "neutral" },
      mobile: false, sortable: false },
    { key: "checked_at", label: "Analisado em", type: "datetime", mobile: false },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: seoStatus.options },
  ],
  fields: [],
  display: {
    badges: (v) => [
      reading(v) ? { label: "Analisando", tone: "info", icon: "pi pi-spin pi-spinner" } : null,
      { label: seoStatus.map[String(v.status)] ?? "", tone: statusTones[v.status as keyof typeof statusTones] },
      v.reading ? null : v.has_search_data ? { label: "Com dados de busca", tone: "info" } : { label: "Sem dados de busca", tone: "neutral" },
    ],
    stats: [
      { label: "Nota do cadastro", value: (v) => (v.score === null || v.score === undefined ? "—" : `${v.score}/100`), icon: "pi pi-gauge",
        tone: scoreTone, hint: (v) => (v.has_search_data ? "Inclui a procura no Google" : "Só o preenchimento: sem dados de busca") },
      { label: "Pontos a melhorar", value: (v) => v.issues_count, icon: "pi pi-list" },
      { label: "Sugestões", value: (v) => v.suggestions_count, icon: "pi pi-sparkles" },
    ],
    sections: [
      { title: "Produto", icon: "pi pi-box", items: [
        { label: "Produto", key: "product_name", link: (v) => linkTo("produtos", v.product) },
        { label: "Analisado em", key: "checked_at", type: "datetime" },
        { label: "Quem decidiu", key: "decided_by_name", visible: (v) => Boolean(v.decided_at) },
        { label: "Quando decidiu", key: "decided_at", type: "datetime", visible: (v) => Boolean(v.decided_at) },
        { label: "Dados de busca", key: "error", span: "full", visible: (v) => Boolean(v.error), tone: () => "danger" },
        { label: "A análise não terminou", value: () => "Passou de 10 minutos. Analise de novo.", span: "full",
          visible: (v) => v.reading_stalled === true, tone: () => "danger" },
      ] },
      { title: "O que melhorar", icon: "pi pi-lightbulb", description: "Cada ponto diz de onde veio: das boas práticas, dos dados de busca do Google ou da Cosmos.",
        table: { rows: (v) => rowsOf(v, "issues"), empty: "Nada a melhorar: o cadastro está completo.", columns: [
          { key: "message", label: "Ponto", title: true, sortable: false },
          { key: "severity", label: "Tipo", type: "tag", map: severity.map, tones: { warning: "warning", info: "info" } },
          { key: "origin", label: "Origem", type: "tag", map: origin.map, tones: { regra: "neutral", busca: "brand", ia: "info" } },
        ] } },
      { title: "Como saiu a nota", icon: "pi pi-chart-bar", description: "A nota mede a qualidade do preenchimento. Não promete posição no Google.",
        table: { rows: (v) => rowsOf(v, "breakdown"), empty: "Ainda sem análise.", columns: [
          { key: "label", label: "Critério", title: true },
          { key: "points", label: "Pontos" },
          { key: "max", label: "De" },
        ] } },
      { title: "Procura no Google", icon: "pi pi-search", description: "Buscas por mês no Brasil. A concorrência é a de anúncios, não a dificuldade de aparecer de graça.",
        visible: (v) => v.has_search_data === true,
        table: { rows: (v) => rowsOf(v, "keywords").map((row) => ({ ...row,
                                                                   searches: row.avg_monthly_searches === null || row.avg_monthly_searches === undefined
                                                                     ? "—" : Number(row.avg_monthly_searches).toLocaleString("pt-BR"),
                                                                   competition_label: competition.map[String(row.competition)] ?? "—" })),
                 empty: "O Google não informou volume para estes termos.", columns: [
          { key: "term", label: "Termo", title: true },
          { key: "searches", label: "Buscas por mês" },
          { key: "competition_label", label: "Concorrência em anúncios" },
          { key: "origin", label: "Origem", type: "tag", map: { cadastro: "Do cadastro", ideia: "Ideia do Google" } },
        ] } },
    ],
  },
  formActions: [
    { label: "Recusar sugestões", icon: "pi pi-times", severity: "danger", permission: "catalog.manage", visible: pending,
      success: "Sugestões recusadas", run: ({ id }) => seoApi.reject(id) },
    { label: "Analisar de novo", icon: "pi pi-refresh", severity: "secondary", permission: "catalog.manage",
      visible: (v) => !reading(v), success: "Análise iniciada. Aguarde", run: ({ id }) => seoApi.refresh(id) },
  ],
  listActions: [
    { label: "Regras", icon: "pi pi-filter", severity: "secondary", permission: "catalog.manage", dialog: SeoRulesDialog },
    { label: "Analisar agora", icon: "pi pi-refresh", severity: "secondary", permission: "catalog.manage",
      success: "Análise iniciada, de 10 em 10. A lista se atualiza sozinha", run: () => seoApi.run() },
  ],
});
