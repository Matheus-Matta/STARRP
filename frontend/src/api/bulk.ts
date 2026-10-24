/**
 * Ações em massa das listas (`/<recurso>/bulk/`, ver backend `core/bulk.py`).
 *
 * `all: true` + os mesmos filtros da tela na URL = vale para TODOS os registros
 * que a lista mostra, não só os da página.
 */
import type { FieldDef } from "@/resources/types";

import { cleanParams, http, type ListParams } from "./http";

export type BulkAction = {
  name: string;
  label: string;
  icon: string;
  danger: boolean;
  confirm: string;
  params: FieldDef[];
};

export type BulkResult = {
  affected: number;
  total: number;
  skipped: { id: string; label: string; reason: string }[];
};

export type BulkTarget = { ids: string[] } | { all: true; filters: ListParams };

function body(action: string, target: BulkTarget, params: Record<string, unknown>) {
  return "all" in target ? { action, all: true, params } : { action, ids: target.ids, params };
}

const query = (target: BulkTarget) => ("all" in target ? cleanParams(target.filters) : {});

export const bulkApi = {
  actions: (endpoint: string) => http.get<BulkAction[]>(`${endpoint}bulk/`).then((r) => r.data),

  run: (endpoint: string, action: string, target: BulkTarget, params: Record<string, unknown> = {}) =>
    http.post<BulkResult>(`${endpoint}bulk/`, body(action, target, params), { params: query(target) }).then((r) => r.data),

  /** Exporta CSV e dispara o download no navegador. */
  async download(endpoint: string, target: BulkTarget, params: Record<string, unknown>, fallbackName: string) {
    const response = await http.post<Blob>(`${endpoint}bulk/`, body("export", target, params),
      { params: query(target), responseType: "blob", timeout: 120_000 });
    const name = /filename="([^"]+)"/.exec(String(response.headers["content-disposition"] ?? ""))?.[1] ?? fallbackName;
    const url = URL.createObjectURL(response.data);
    const link = Object.assign(document.createElement("a"), { href: url, download: name });
    link.click();
    URL.revokeObjectURL(url);
  },
};
