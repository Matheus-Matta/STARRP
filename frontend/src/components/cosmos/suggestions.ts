/**
 * Atalhos do início da Cosmos, escolhidos para quem está usando — no máximo 4, nesta ordem:
 * 1. a tela aberta agora (no cadastro de um produto: "confira este cadastro");
 * 2. alertas abertos da equipe (quem supervisiona);
 * 3. o que a pessoa mais faz no sistema (`status.habits`, lido do histórico dos últimos 30 dias);
 * 4. o básico do perfil dela.
 * Só entra o que o perfil permite (permissão da área, propor gravação, supervisionar).
 */
import type { CosmosStatus } from "@/api/cosmos";
import { resources } from "@/resources";

export type Suggestion = { icon: string; text: string };
type Topic = "products" | "sales" | "customers" | "suppliers" | "stock" | "cash" | "finance" | "team";
type Item = Suggestion & { needs?: string; write?: boolean; supervise?: boolean };

const MAX = 4;

const TOPICS: Record<Topic, Item[]> = {
  sales: [
    { icon: "pi pi-chart-line", text: "Como estão as vendas de hoje comparadas com ontem?", needs: "reports.view" },
    { icon: "pi pi-users", text: "Relatório de vendas deste mês por vendedor", needs: "reports.view" },
  ],
  products: [
    { icon: "pi pi-plus-circle", text: "Quero cadastrar um produto novo", write: true },
    { icon: "pi pi-file-excel", text: "Quero cadastrar produtos de uma planilha", write: true },
    { icon: "pi pi-search", text: "Quais produtos estão sem NCM, categoria ou com preço zerado?", needs: "catalog.view" },
  ],
  stock: [
    { icon: "pi pi-box", text: "Quais produtos estão com estoque baixo?", needs: "stock.view" },
    { icon: "pi pi-exclamation-triangle", text: "Tem produto com estoque negativo? Por quê?", needs: "stock.view" },
  ],
  customers: [
    { icon: "pi pi-star", text: "Quem são os clientes que mais compraram este mês?", needs: "reports.view" },
    { icon: "pi pi-user-plus", text: "Quero cadastrar um cliente novo", write: true },
  ],
  suppliers: [
    { icon: "pi pi-truck", text: "Quero cadastrar um fornecedor novo", write: true },
  ],
  cash: [
    { icon: "pi pi-wallet", text: "Como estão os caixas hoje? Tem diferença em aberto?", needs: "cash.view" },
  ],
  finance: [
    { icon: "pi pi-calendar", text: "Quais contas vencem nesta semana?", needs: "finance.view" },
    { icon: "pi pi-chart-bar", text: "Resumo de contas a pagar e a receber deste mês", needs: "finance.view" },
  ],
  team: [
    { icon: "pi pi-users", text: "O que a equipe fez hoje? Tem algo errado?", supervise: true },
  ],
};

const BASICS: Item[] = [
  ...TOPICS.sales.slice(0, 1), ...TOPICS.stock.slice(0, 1), ...TOPICS.products.slice(0, 1), ...TOPICS.team,
  { icon: "pi pi-question-circle", text: "Como faço uma troca/devolução no sistema?" },
];

/** Endereço da API do cadastro → tema. */
function topicOfEndpoint(endpoint: string): Topic | null {
  const path = endpoint.replace(/^\/+/, "");
  if (path.startsWith("catalog/")) return "products";
  if (path.startsWith("sales")) return "sales";
  if (path.startsWith("customers")) return "customers";
  if (path.startsWith("suppliers")) return "suppliers";
  if (path.startsWith("stock")) return "stock";
  if (path.startsWith("cash")) return "cash";
  if (path.startsWith("finance")) return "finance";
  return null;
}

/** A tela aberta: o tema e, num registro aberto, um atalho só dele. */
function fromScreen(path: string): { topic: Topic | null; first: Item | null } {
  if (path.startsWith("/estoque")) return { topic: "stock", first: null };
  if (path.startsWith("/financeiro")) return { topic: "finance", first: null };
  if (path.startsWith("/relatorios/")) {
    return { topic: "sales", first: { icon: "pi pi-lightbulb", text: "Explique os destaques do relatório desta tela" } };
  }
  if (path.startsWith("/relatorios")) return { topic: "sales", first: null };
  const match = /^\/cadastros\/([^/]+)(?:\/([^/]+))?/.exec(path);
  const resource = match ? resources.find((r) => r.name === match[1]) : undefined;
  if (!resource) return { topic: null, first: null };
  const record = match?.[2] && match[2] !== "novo"
    ? { icon: "pi pi-check-square", text: `Confira ${resource.feminine ? "esta" : "este"} ${resource.singular}: tem algo errado ou faltando?` }
    : null;
  return { topic: topicOfEndpoint(resource.endpoint), first: record };
}

export function suggestionsFor(path: string, status: CosmosStatus | null, can: (code: string) => boolean): Suggestion[] {
  const allowed = (item: Item) => (!item.needs || can(item.needs)) && (!item.write || Boolean(status?.can_write))
    && (!item.supervise || Boolean(status?.can_supervise));
  const screen = fromScreen(path);
  const ordered: Item[] = [];
  if (screen.first) ordered.push(screen.first);
  if (screen.topic) ordered.push(...TOPICS[screen.topic]);
  if (status?.can_supervise && status.open_alerts > 0) {
    ordered.push({ icon: "pi pi-shield", text: `Temos ${status.open_alerts} alertas abertos: quais e como corrigir?` });
  }
  for (const habit of status?.habits ?? []) {
    if (habit in TOPICS) ordered.push(...TOPICS[habit as Topic].slice(0, 2));
  }
  ordered.push(...BASICS);
  const seen = new Set<string>();
  const out: Suggestion[] = [];
  for (const item of ordered) {
    if (out.length >= MAX) break;
    if (seen.has(item.text) || !allowed(item)) continue;
    seen.add(item.text);
    out.push({ icon: item.icon, text: item.text });
  }
  return out;
}
