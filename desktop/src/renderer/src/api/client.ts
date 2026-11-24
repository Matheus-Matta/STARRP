/**
 * Cliente HTTP da tela. Não faz rede: pede ao processo principal (`window.starrp.api`), que
 * guarda o access/refresh token, põe o `Authorization: Bearer` e renova o token sozinho.
 */
import type { ApiRequest, HttpMethod } from "../../../shared/ipc";
import { fromResponse } from "./errors";

export type Params = ApiRequest["params"];
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

async function call<T>(method: HttpMethod, path: string, options: Omit<ApiRequest, "method" | "path"> = {}): Promise<T> {
  const response = await window.starrp.api({ method, path, ...options });
  if (!response.ok) throw fromResponse(response.status, response.data);
  return response.data as T;
}

export const http = {
  get: <T>(path: string, params?: Params, headers?: Record<string, string>) => call<T>("GET", path, { params, headers }),
  post: <T>(path: string, data: unknown = {}, headers?: Record<string, string>) => call<T>("POST", path, { data, headers }),
  patch: <T>(path: string, data: unknown) => call<T>("PATCH", path, { data }),
  delete: <T>(path: string, data?: unknown) => call<T>("DELETE", path, { data }),
};

/** Chave para o backend deduplicar reenvio (checkout): a mesma tentativa nunca cobra 2x. */
export const idempotencyKey = () => crypto.randomUUID();

/** Imagens do backend podem vir relativas (`/media/...`): completa com o endereço do servidor. */
let serverUrl = "";
export const setServerUrl = (url: string) => {
  serverUrl = url.replace(/\/+$/, "");
};
export const mediaUrl = (url: string | null | undefined) =>
  !url ? null : /^(https?:|data:|blob:)/.test(url) ? url : `${serverUrl}${url.startsWith("/") ? "" : "/"}${url}`;
