/**
 * Cliente da API no processo principal.
 *
 * - toda chamada leva `Authorization: Bearer <access>` e a loja do PDV (`X-Store-ID`);
 * - 401 renova o access com o refresh UMA vez (chamadas simultâneas esperam a mesma
 *   renovação) e repete; o backend gira o refresh (ROTATE_REFRESH_TOKENS) e o novo é guardado;
 * - refresh recusado (400/401/403): apaga os tokens e avisa a tela (`onExpired`) para voltar ao login.
 *   Sem rede ou com erro 5xx o refresh NÃO é apagado: a sessão volta quando o servidor voltar.
 */
import type { ApiRequest, ApiResponse } from "../shared/ipc";
import { app } from "electron";

import { serverUrlProblem } from "../shared/serverUrl";
import { getConfig } from "./config";
import { clearTokens, readTokens, saveTokens } from "./tokens";

const TIMEOUT_MS = 20_000;
let expiredListener: () => void = () => undefined;
export const onExpired = (listener: () => void) => {
  expiredListener = listener;
};

function url(path: string, params?: ApiRequest["params"]) {
  const target = new URL(`${getConfig().serverUrl}/api/v1${path.startsWith("/") ? path : `/${path}`}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") target.searchParams.set(key, String(value));
  }
  return target.toString();
}

async function send(request: ApiRequest, access?: string): Promise<ApiResponse> {
  // Configuração antiga com http:// no app instalado: nem tenta (o token não sai sem criptografia).
  const problem = serverUrlProblem(getConfig().serverUrl, app.isPackaged);
  if (problem) return { ok: false, status: 0, data: { detail: problem } };
  const headers: Record<string, string> = { Accept: "application/json", ...request.headers };
  if (request.data !== undefined) headers["Content-Type"] = "application/json";
  if (access) headers.Authorization = `Bearer ${access}`;
  const storeId = getConfig().storeId;
  if (storeId && !Object.keys(headers).some((h) => h.toLowerCase() === "x-store-id")) headers["X-Store-ID"] = storeId;
  try {
    const response = await fetch(url(request.path, request.params), {
      method: request.method,
      headers,
      signal: AbortSignal.timeout(TIMEOUT_MS),
      body: request.data === undefined ? undefined : JSON.stringify(request.data),
    });
    const text = await response.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text.slice(0, 300) };
    }
    return { ok: response.ok, status: response.status, data };
  } catch (error) {
    // status 0 = sem resposta (servidor fora do ar, sem rede, tempo esgotado)
    return { ok: false, status: 0, data: { detail: error instanceof Error ? error.message : String(error) } };
  }
}

let refreshing: Promise<boolean> | null = null;

function refresh(): Promise<boolean> {
  refreshing ??= (async () => {
    const current = readTokens();
    if (!current) return false;
    const result = await send({ method: "POST", path: "/auth/refresh/", data: { refresh: current.refresh } });
    if (!result.ok) {
      // Só o "refresh inválido" (vencido, girado, revogado) desloga; servidor fora ou com erro 5xx não.
      if ([400, 401, 403].includes(result.status)) clearTokens();
      return false;
    }
    const body = result.data as { access: string; refresh?: string };
    saveTokens({ access: body.access, refresh: body.refresh ?? current.refresh });
    return true;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

export async function request(req: ApiRequest): Promise<ApiResponse> {
  const first = await send(req, readTokens()?.access);
  if (first.status !== 401 || req.path.startsWith("/auth/")) return first;
  if (await refresh()) return send(req, readTokens()?.access);
  if (!readTokens()) expiredListener();
  return first;
}

export async function login(username: string, password: string): Promise<ApiResponse> {
  const result = await send({ method: "POST", path: "/auth/login/", data: { username, password } });
  if (result.ok) {
    const body = result.data as { access: string; refresh: string };
    saveTokens({ access: body.access, refresh: body.refresh });
  }
  return result;
}

export async function logout() {
  const current = readTokens();
  clearTokens();
  // Invalida o refresh no servidor (blacklist); sem rede, ele só expira sozinho.
  if (current) await send({ method: "POST", path: "/auth/logout/", data: { refresh: current.refresh } });
}

export const hasSession = () => readTokens() !== null;
