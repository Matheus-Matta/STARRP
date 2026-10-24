/** Fiscal: dados fiscais (certificado, busca na SEFAZ) e NF-e de entrada. */
import { http } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);
/** A SEFAZ pode demorar (vários lotes de 30 s): estas chamadas esperam mais que o padrão. */
const SLOW = { timeout: 180_000 };

export type DfeResult = { config: string; ok: boolean; notes: number; received: number; message: string };

export const fiscalApi = {
  fromStores: () => data(http.post<{ linked: number; skipped: string[] }>("/fiscal/configs/from-stores/", {})),
  certificate: (id: string, file: File, password: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("password", password);
    return data(http.post(`/fiscal/configs/${id}/certificate/`, form));
  },
  syncDfe: (id: string) => data(http.post(`/fiscal/configs/${id}/sync-dfe/`, {}, SLOW)),
};

export const nfeApi = {
  /** Busca em todos os CNPJs com a busca ligada (ou só em `config`). */
  sync: (config?: string) =>
    data(http.post<{ results: DfeResult[]; notes: number }>("/inbound-nfe/sync/", config ? { config } : {}, SLOW)),
  importXml: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return data(http.post<{ id: string }>("/inbound-nfe/import/", form));
  },
  science: (id: string) => data(http.post(`/inbound-nfe/${id}/science/`, {}, SLOW)),
  download: (id: string) => data(http.post(`/inbound-nfe/${id}/download/`, {}, SLOW)),
  manifest: (id: string, code: string, reason = "") => data(http.post(`/inbound-nfe/${id}/manifest/`, { code, reason }, SLOW)),
  mapItem: (id: string, item: string, variant: string, factor: number | string = 1) =>
    data(http.post(`/inbound-nfe/${id}/map-item/`, { item, variant, conversion_factor: factor })),
  rematch: (id: string) => data(http.post(`/inbound-nfe/${id}/rematch/`, {})),
  receive: (id: string, warehouse?: string) =>
    data(http.post<{ id: string; number: number }>(`/inbound-nfe/${id}/receive/`, warehouse ? { warehouse } : {})),
  ignore: (id: string, reason = "") => data(http.post(`/inbound-nfe/${id}/ignore/`, { reason })),
  createProduct: (item: string, price?: string) =>
    data(http.post(`/inbound-nfe/items/${item}/create-product/`, price ? { price } : {})),
  ignoreItem: (item: string, reason = "") => data(http.post(`/inbound-nfe/items/${item}/ignore/`, { reason })),
};
