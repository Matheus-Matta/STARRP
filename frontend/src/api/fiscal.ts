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

export type FiscalCheck = { key: string; label: string; ok: boolean; message: string; scope: "all" | "cloud" | "desktop" };
export type StoreFiscal = {
  ready: boolean;
  cloud_ready?: boolean;
  checks: FiscalCheck[];
  config: null | {
    id: string; name: string; cnpj: string; legal_name: string; state: string; environment: "1" | "2"; crt: string;
    provider: string; local_fiscal_enabled: boolean; local_fiscal_contingency: boolean; csc_id: string;
    has_csc_token: boolean; has_certificate: boolean; certificate_name: string; certificate_cnpj: string;
    certificate_valid_until: string | null; certificate_days: number | null; default_profile: string | null; stores: string[];
  };
};
export type StoreFiscalInput = Partial<{
  environment: string; crt: string; local_fiscal_enabled: boolean; local_fiscal_contingency: boolean;
  csc_id: string; csc_token: string; default_profile: string | null;
}>;

/** Aba "Nota fiscal" da filial: grava nos dados fiscais vinculados (cria pelo CNPJ da filial se faltar). */
export const storeFiscalApi = {
  get: (store: string) => data(http.get<StoreFiscal>(`/stores/${store}/fiscal/`)),
  save: (store: string, input: StoreFiscalInput) => data(http.post<StoreFiscal>(`/stores/${store}/fiscal/`, input)),
  certificate: (store: string, file: File, password: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("password", password);
    return data(http.post<StoreFiscal>(`/stores/${store}/fiscal/certificate/`, form));
  },
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
  // Voltar passos
  unignoreItem: (item: string) => data(http.post(`/inbound-nfe/items/${item}/unignore/`, {})),
  unmapItem: (item: string, forget = true) => data(http.post(`/inbound-nfe/items/${item}/unmap/`, { forget })),
  discardEntry: (id: string) => data(http.post(`/inbound-nfe/${id}/discard-entry/`, {})),
  undoReceipt: (id: string, reason: string) => data(http.post(`/inbound-nfe/${id}/undo-receipt/`, { reason })),
  restore: (id: string) => data(http.post(`/inbound-nfe/${id}/restore/`, {})),
};
