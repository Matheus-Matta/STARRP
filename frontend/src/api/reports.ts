import { cleanParams, http, type ListParams } from "./http";

export type Summary = {
  sales_count: number;
  revenue: string;
  average_ticket: string;
  discounts: string;
  returns_total: string;
  cancelled_count: number;
  gross_margin: string;
};

export type Dashboard = {
  summary: Summary;
  by_day: { day: string; count: number; revenue: string }[];
  by_payment_method: { method__name: string; total: string; count: number }[];
  top_products: { description: string; sold_quantity: string; revenue: string; margin: string }[];
  by_seller: { seller__first_name: string; seller__username: string; revenue: string; commission: string }[];
  open_sales: number;
};

/** Livro de relatórios: indicadores + blocos (gráficos e tabela) no formato padrão do backend. */
export type BookBlock = {
  type: "line" | "bars" | "ranking" | "share" | "heatmap" | "waterfall" | "table" | "compare" | "insights";
  title: string; description?: string; span?: "full" | "half"; format?: string; stacked?: boolean;
  [key: string]: unknown;
};
export type BookKpi = { label: string; value: string | number; format: string; delta: string | null;
                        good: "up" | "down"; hint: string };
export type BookFilter = { name: string; label: string; options: { label: string; value: string }[] };
export type BookReport = { title: string; subtitle: string; period: { from: string; to: string }; grain: "day" | "week" | "month";
                           filters: BookFilter[]; kpis: BookKpi[]; blocks: BookBlock[] };

/** Baixa o arquivo que a API devolveu (o nome vem do Content-Disposition). */
function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  // Liberar o link na hora pode cancelar o download em alguns navegadores.
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const reportsApi = {
  /** Excel (resumo + uma aba por bloco) ou CSV de um bloco; `bloco`/`aba` restringem a uma tabela/classe. */
  async export(slug: string, params: ListParams, formato: "xlsx" | "csv", extra: { bloco?: number; aba?: string | null } = {}) {
    const response = await http.get<Blob>(`/reports/book/${slug}/export/`, {
      params: cleanParams({ ...params, formato, bloco: extra.bloco, aba: extra.aba ?? undefined }),
      responseType: "blob", timeout: 120_000,
    });
    const name = /filename="([^"]+)"/.exec(String(response.headers["content-disposition"] ?? ""))?.[1] ?? `${slug}.${formato}`;
    save(response.data, name);
  },
  book: (slug: string, params: ListParams = {}) =>
    http.get<BookReport>(`/reports/book/${slug}/`, { params: cleanParams(params) }).then((r) => r.data),
  dashboard: (params: ListParams = {}) =>
    http.get<Dashboard>("/reports/dashboard/", { params: cleanParams(params) }).then((r) => r.data),
};
