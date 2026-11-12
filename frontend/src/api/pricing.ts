/** Precificação: preço dos produtos comparado com o mercado (Vendas › Precificação). */
import { http } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export type CompetitorImport = {
  imported: number; products: number; error_count: number; errors: { linha: number; erro: string }[];
};

/** Quais produtos a leitura pega. Nada marcado = todos. */
export type PriceRules = {
  categories: string[]; brands: string[]; products: string[]; exclude_products: string[];
  min_price: string | number | null; max_price: string | number | null;
  only_in_stock: boolean; only_with_barcode: boolean;
};

export const pricingApi = {
  /** Botão "Precificar" do produto: cria o item de cada variação na hora; a leitura roda no worker. */
  product: (product: string) => data(http.post<{ checked: number; ids: string[] }>("/price-checks/product/", { product })),
  rules: () => data(http.get<PriceRules & { in_scope: number }>("/price-checks/rules/")),
  saveRules: (rules: PriceRules) => data(http.post<PriceRules & { in_scope: number }>("/price-checks/rules/", rules)),
  /** Aplica o preço sugerido (ou `price`, se a pessoa escolheu outro) no cadastro. */
  approve: (id: string, price?: string) => data(http.post(`/price-checks/${id}/approve/`, price ? { price } : {})),
  reject: (id: string) => data(http.post(`/price-checks/${id}/reject/`, {})),
  refresh: (id: string) => data(http.post(`/price-checks/${id}/refresh/`, {})),
  importCompetitors: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return data(http.post<CompetitorImport>("/competitor-prices/import/", form, { timeout: 120_000 }));
  },
  /** Começa a rodada no worker: tudo o que está na vez nas regras, em lotes. */
  run: () => data(http.post<{ checked: number }>("/price-checks/run/", {})),
  runStatus: () => data(http.get<{ running: boolean; done: number; total: number; task: string | null }>("/price-checks/run-status/")),
};
