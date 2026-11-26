/**
 * Cliente HTTP único. Autenticação por cookie httpOnly (o JS nunca vê o token, nem no corpo do login).
 *
 * - toda requisição leva a loja ativa (`X-Store-ID`), lida do store de sessão;
 * - um 401 tenta renovar o token UMA vez (requisições simultâneas esperam a
 *   mesma renovação) e, se falhar, avisa a sessão para ir ao login;
 * - todo erro sai como `ApiError` (envelope do backend já traduzido).
 */
import axios, { type AxiosRequestConfig } from "axios";

import { readBlobError, toApiError } from "./errors";

/** O app web trabalha SÓ com o cookie httpOnly: com este cabeçalho o backend não põe o token no corpo do
 *  login (um script injetado na página não teria o que ler). PDV desktop e app móvel não mandam. */
const COOKIE_ONLY = { "X-Auth-Transport": "cookie" };

export const http = axios.create({ baseURL: "/api/v1", withCredentials: true, timeout: 20_000, headers: COOKIE_ONLY });

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

/** "ok" renovou; "invalid" o servidor recusou (login de novo); "offline" rede/servidor fora (a sessão continua). */
type Refresh = "ok" | "invalid" | "offline";
let refreshing: Promise<Refresh> | null = null;

const plain = { withCredentials: true, headers: COOKIE_ONLY, timeout: 20_000 };
const failure = (error: unknown): Refresh =>
  axios.isAxiosError(error) && [400, 401, 403].includes(error.response?.status ?? 0) ? "invalid" : "offline";

async function renew(): Promise<Refresh> {
  try {
    await axios.post("/api/v1/auth/refresh/", {}, plain);
    return "ok";
  } catch (error) {
    return failure(error);
  }
}

/** Uma aba por vez: o refresh é girado, e duas abas renovando juntas derrubavam a sessão da segunda. Quem esperou
 *  confere primeiro se a outra aba já renovou (o cookie é o mesmo). */
async function renewInTurn(): Promise<Refresh> {
  try {
    await axios.get("/api/v1/me/", plain);
    return "ok";
  } catch (error) {
    const result = failure(error);
    // 403 = logado, mas sem acesso a algo: a sessão vale. Só o 401 pede renovação.
    if (axios.isAxiosError(error) && error.response?.status === 403) return "ok";
    return result === "invalid" ? renew() : result;
  }
}

function refresh(): Promise<Refresh> {
  if (refreshing) return refreshing;
  const running = (async (): Promise<Refresh> =>
    navigator.locks ? await navigator.locks.request("starrp.refresh", renewInTurn) : renewInTurn())();
  refreshing = running;
  void running.finally(() => {
    refreshing = null;
  });
  return running;
}

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config as AxiosRequestConfig & { _retried?: boolean };
    if (error.response?.status === 401 && original && !original._retried && !original.url?.startsWith("/auth/")) {
      original._retried = true;
      const result = await refresh();
      if (result === "ok") return http(original);
      if (result === "invalid") hooks.onUnauthorized();
    }
    await readBlobError(error);
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
