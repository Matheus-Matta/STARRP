/** Analítico de SEO: nota do cadastro de cada produto e sugestões (Vendas › Analítico de SEO). */
import { http } from "./http";

import type { PriceRules } from "./pricing";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export const seoApi = {
  /** Botão "Analisar SEO" do produto: cria a análise na hora; o trabalho roda no worker. */
  product: (product: string) => data(http.post<{ id: string }>("/seo-checks/product/", { product })),
  /** Começa a rodada no worker: tudo o que está nas regras, em lotes. */
  run: () => data(http.post<{ checked: number }>("/seo-checks/run/", {})),
  runStatus: () => data(http.get<{ running: boolean; done: number; total: number; task: string | null }>("/seo-checks/run-status/")),
  rules: () => data(http.get<PriceRules & { in_scope: number }>("/seo-checks/rules/")),
  saveRules: (rules: PriceRules) => data(http.post<PriceRules & { in_scope: number }>("/seo-checks/rules/", rules)),
  refresh: (id: string) => data(http.post(`/seo-checks/${id}/refresh/`, {})),
  /** Grava no cadastro só as sugestões marcadas. */
  apply: (id: string, fields: string[]) => data(http.post(`/seo-checks/${id}/apply/`, { fields })),
  reject: (id: string) => data(http.post(`/seo-checks/${id}/reject/`, {})),
};
