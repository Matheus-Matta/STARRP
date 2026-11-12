/** Organização do estoque: as recomendações da Cosmos para os endereços. */
import { http } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export const stockAdviceApi = {
  run: () => data(http.post<{ opened: number; open: number }>("/stock/advices/run/", {})),
  /** Cria a movimentação em rascunho: o estoque só muda quando a equipe confirmar. */
  apply: (id: string) => data(http.post<{ document: string }>(`/stock/advices/${id}/apply/`, {})),
  dismiss: (id: string) => data(http.post(`/stock/advices/${id}/dismiss/`, {})),
};
