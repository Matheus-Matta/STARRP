/**
 * Cliente HTTP único. Autenticação por cookie httpOnly (o JS nunca vê o token).
 *
 * - toda requisição leva a loja ativa (`X-Store-ID`), lida do store de sessão;
 * - um 401 tenta renovar o token UMA vez (requisições simultâneas esperam a
 *   mesma renovação) e, se falhar, avisa a sessão para ir ao login;
 * - todo erro sai como `ApiError` (envelope do backend já traduzido).
 */
import axios, { type AxiosRequestConfig } from "axios";

import { toApiError } from "./errors";

export const http = axios.create({ baseURL: "/api/v1", withCredentials: true, timeout: 20_000 });

type Hooks = { storeId: () => string | null; onUnauthorized: () => void };
let hooks: Hooks = { storeId: () => null, onUnauthorized: () => undefined };

/** Chamado pelo store de sessão (evita import circular http ⇄ store). */
export function configureHttp(next: Hooks) {
  hooks = next;
}

http.interceptors.request.use((config) => {
  const storeId = hooks.storeId();
  if (storeId && !config.headers.has("X-Store-ID")) config.headers.set("X-Store-ID", storeId);
  return config;
});

let refreshing: Promise<boolean> | null = null;

function refresh(): Promise<boolean> {
  refreshing ??= axios
    .post("/api/v1/auth/refresh/", {}, { withCredentials: true })
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config as AxiosRequestConfig & { _retried?: boolean };
    if (error.response?.status === 401 && original && !original._retried && !original.url?.startsWith("/auth/")) {
      original._retried = true;
      if (await refresh()) return http(original);
      hooks.onUnauthorized();
    }
    throw toApiError(error);
  },
);

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type ListParams = Record<string, string | number | boolean | undefined | null>;

/** Remove parâmetros vazios: `?search=` vazio não deve virar filtro. */
export function cleanParams(params: ListParams = {}) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null));
}

/** Chave para o backend deduplicar reenvio (checkout, pagamento). */
export function idempotencyKey() {
  return crypto.randomUUID();
}
