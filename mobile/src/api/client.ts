/**
 * Cliente HTTP do app. Mesma API da retaguarda (/api/v1), mas com o token no
 * header `Authorization: Bearer` (como o PDV desktop), guardado no SecureStore.
 *
 * - toda requisição leva a filial ativa (`X-Store-ID`);
 * - um 401 renova o token UMA vez (requisições simultâneas esperam a mesma
 *   renovação) e, se falhar, avisa a sessão para voltar ao login;
 * - todo erro sai como `ApiError`, com a mensagem do envelope do backend.
 */
import Constants from "expo-constants";
import { Platform } from "react-native";

import { storage } from "@/lib/storage";

const KEYS = { server: "starrp.server", access: "starrp.access", refresh: "starrp.refresh", store: "starrp.store" };

type State = { server: string; access: string | null; refresh: string | null; storeId: string | null;
                /** Filial principal do usuário (`default_store_id`): vale para criar/editar em "Todas as filiais". */
                defaultStore: string | null;
                /** Tela de criação/edição aberta em "Todas as filiais": tudo dela (leituras também) vai para esta filial. */
                scopeStore: string | null };
const state: State = { server: "", access: null, refresh: null, storeId: null, defaultStore: null, scopeStore: null };

export function setDefaultStore(id: string | null) {
  state.defaultStore = id;
}
export function getDefaultStore() {
  return state.defaultStore;
}
/** Liga/desliga a filial da tela de criação/edição (ver `DefaultStoreScope`). */
export function setScopedStore(id: string | null) {
  state.scopeStore = id;
}
let onUnauthorized: () => void = () => undefined;

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;

  constructor(status: number, message: string, code = "error", fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type Params = Record<string, string | number | boolean | undefined | null>;

/** Lê o que ficou salvo no aparelho (servidor, tokens e filial). */
export async function loadStoredSession() {
  const [server, access, refresh, storeId] = await Promise.all(
    [KEYS.server, KEYS.access, KEYS.refresh, KEYS.store].map((k) => storage.get(k)),
  );
  Object.assign(state, { server: server ?? "", access, refresh, storeId });
  return { server: state.server, hasToken: Boolean(refresh) };
}

export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

/** App de produção (build da loja / EAS): servidor só em HTTPS. Em desenvolvimento (Expo Go, IP do PC) vale http. */
const PRODUCTION = !__DEV__;

/** "app.loja.com.br" → "https://app.loja.com.br" ("192.168.0.10:8000" → "http://..." só em desenvolvimento);
 *  sem barra e sem /api no fim. */
export function normalizeServer(raw: string) {
  let url = raw.trim().replace(/\/+$/, "").replace(/\/api(\/v1)?$/, "");
  if (url && !/^https?:\/\//i.test(url)) url = `${PRODUCTION ? "https" : "http"}://${url}`;
  return url;
}

/** Problema do endereço para o usuário; `null` = pode usar. O token e a senha nunca trafegam sem criptografia. */
export function serverProblem(raw: string, production = PRODUCTION): string | null {
  const url = normalizeServer(raw);
  if (!url) return "Informe o endereço do servidor.";
  if (!/^https?:\/\/[^/\s]+$/i.test(url)) return "Endereço inválido. Ex.: https://app.suaempresa.com.br";
  if (production && url.toLowerCase().startsWith("http://")) {
    return "Use https:// — o app não envia a senha nem o login por conexão sem criptografia.";
  }
  return null;
}

/** Servidor padrão do app: o `API_URL` do `.env` da raiz (lido pelo app.config.js). */
export const DEFAULT_SERVER = normalizeServer(String(Constants.expoConfig?.extra?.apiUrl ?? ""));

export type ServerTest = { ok: boolean; ms: number; message: string };

/** "Testar conexão": chama o `/health/` do backend (sem login) e diz se respondeu e em quanto tempo. */
export async function testServer(raw: string): Promise<ServerTest> {
  const url = normalizeServer(raw);
  const problem = serverProblem(raw);
  if (problem) return { ok: false, ms: 0, message: problem };
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`${url}/health/`, { signal: controller.signal, headers: { Accept: "application/json" } });
    const ms = Date.now() - started;
    if (response.status === 401 && /tunnel/i.test(response.headers.get("www-authenticate") ?? "")) {
      return { ok: false, ms, message: "O túnel do VS Code está privado: deixe a porta 8001 como Pública na aba Portas." };
    }
    if (response.status === 400) return { ok: false, ms, message: "O servidor recusou este endereço (falta no DJANGO_ALLOWED_HOSTS)." };
    const body = await response.json().catch(() => null) as { status?: string } | null;
    if (response.ok && body?.status === "ok") return { ok: true, ms, message: `Servidor do Starrp respondeu em ${ms} ms.` };
    return { ok: false, ms, message: `O endereço respondeu (${response.status}), mas não parece ser o servidor do Starrp.` };
  } catch (error) {
    const ms = Date.now() - started;
    return { ok: false, ms, message: (error as Error)?.name === "AbortError"
      ? "Sem resposta em 8 s. Confira o endereço, a rede e se o servidor está no ar."
      : "Não foi possível conectar. No celular, \"localhost\" é o próprio aparelho: use o IP do PC ou o túnel." };
  } finally {
    clearTimeout(timer);
  }
}

export function getServer() {
  return state.server;
}

export async function setServer(url: string) {
  const problem = serverProblem(url);
  if (problem) throw new ApiError(0, problem, "insecure_server");
  const next = normalizeServer(url);
  // Outro servidor: o login deste não vale lá (e o token nunca vai para um servidor diferente).
  if (next !== state.server) await saveTokens(null, null);
  state.server = next;
  await storage.set(KEYS.server, state.server);
}

export function getStoreId() {
  return state.storeId;
}

export async function setStoreId(id: string | null) {
  state.storeId = id;
  if (id) await storage.set(KEYS.store, id);
  else await storage.remove(KEYS.store);
}

/** Expo web publicado: o token fica só na memória (nada no localStorage, que qualquer script da página lê). */
const MEMORY_ONLY_TOKENS = PRODUCTION && Platform.OS === "web";

async function saveTokens(access: string | null, refresh: string | null) {
  state.access = access;
  state.refresh = refresh;
  if (MEMORY_ONLY_TOKENS) return;
  await Promise.all([
    access ? storage.set(KEYS.access, access) : storage.remove(KEYS.access),
    refresh ? storage.set(KEYS.refresh, refresh) : storage.remove(KEYS.refresh),
  ]);
}

function query(params?: Params) {
  if (!params) return "";
  const parts = Object.entries(params)
    .filter(([, v]) => v !== "" && v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

/** Envelope `{success:false, error:{code, message}}` → mensagem legível. */
function flattenMessage(message: unknown, fields: Record<string, string>, prefix = ""): string {
  if (typeof message === "string") return message;
  if (Array.isArray(message)) return message.map((m) => flattenMessage(m, fields, prefix)).filter(Boolean).join(" ");
  if (message && typeof message === "object") {
    const parts: string[] = [];
    for (const [key, value] of Object.entries(message as Record<string, unknown>)) {
      const text = flattenMessage(value, fields, key);
      if (key !== "detail" && key !== "non_field_errors") fields[prefix || key] = text;
      parts.push(text);
    }
    return parts.filter(Boolean).join(" ");
  }
  return "";
}

async function toError(response: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await response.json();
  } catch {
    /* corpo não-JSON */
  }
  const fields: Record<string, string> = {};
  const raw = body?.error?.message ?? body?.detail ?? body;
  const message = flattenMessage(raw, fields) || `Erro ${response.status} no servidor.`;
  return new ApiError(response.status, message, body?.error?.code ?? "error", fields);
}

/** "ok" renovou; "invalid" o servidor recusou o refresh (vencido, girado, revogado → login); "offline" sem
 *  resposta ou erro do servidor: a sessão CONTINUA (4G oscilando não pode mandar o usuário para o login). */
type Refresh = "ok" | "invalid" | "offline";
let refreshing: Promise<Refresh> | null = null;

function refreshToken(): Promise<Refresh> {
  refreshing ??= (async (): Promise<Refresh> => {
    if (!state.refresh) return "invalid";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch(`${state.server}/api/v1/auth/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: state.refresh }),
        signal: controller.signal,
      });
      if ([400, 401, 403].includes(response.status)) {
        await saveTokens(null, null);
        return "invalid";
      }
      if (!response.ok) return "offline";
      const data = await response.json();
      await saveTokens(data.access, data.refresh ?? state.refresh);
      return "ok";
    } catch {
      return "offline";
    } finally {
      clearTimeout(timer);
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

const OFFLINE = () => new ApiError(0, "Sem conexão com o servidor. Confira a rede e tente de novo.", "network");

/** 401: renova e diz se dá para repetir; recusado → encerra a sessão; sem rede → erro de conexão (sessão fica). */
async function renewAfter401(): Promise<boolean> {
  const result = await refreshToken();
  if (result === "ok") return true;
  if (result === "offline") throw OFFLINE();
  onUnauthorized();
  return false;
}

type RequestOptions = { params?: Params; body?: unknown; store?: string | null; timeoutMs?: number;
                        headers?: Record<string, string> };

/**
 * Toda chamada à API (menos o próprio login) exige o token de acesso: sem ele, tenta renovar com o token salvo;
 * se não der, encerra a sessão e o app volta para o login. Nada sai do app sem autenticação.
 */
async function ensureAccess(path: string) {
  if (path.startsWith("/auth/") || state.access) return;
  if (state.refresh) {
    const result = await refreshToken();
    if (result === "ok") return;
    if (result === "offline") throw OFFLINE();
  }
  onUnauthorized();
  throw new ApiError(401, "Sua sessão terminou. Entre de novo.", "not_authenticated");
}

export async function request<T>(method: string, path: string, options: RequestOptions = {}, retried = false): Promise<T> {
  if (!state.server) throw new ApiError(0, "Configure o endereço do servidor.", "no_server");
  const insecure = serverProblem(state.server);
  if (insecure) throw new ApiError(0, insecure, "insecure_server"); // endereço antigo com http:// salvo
  await ensureAccess(path);
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (state.access) headers.Authorization = `Bearer ${state.access}`;
  let storeId = options.store !== undefined ? options.store : state.storeId;
  // "Todas as filiais" não serve para gravar: criar/editar usa a filial principal do usuário, sem perguntar.
  if (options.store === undefined && (!storeId || storeId === "*")) {
    storeId = state.scopeStore ?? (method !== "GET" ? state.defaultStore : null) ?? storeId;
  }
  if (storeId) headers["X-Store-ID"] = storeId;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 20_000);
  let response: Response;
  try {
    response = await fetch(`${state.server}/api/v1${path}${query(options.params)}`, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
  } catch (error: any) {
    throw new ApiError(
      0,
      error?.name === "AbortError"
        ? "O servidor demorou para responder. Verifique a conexão."
        : "Sem conexão com o servidor. Confira o endereço e a rede.",
      "network",
    );
  } finally {
    clearTimeout(timer);
  }

  if (response.status === 401 && !retried && !path.startsWith("/auth/")) {
    if (await renewAfter401()) return request<T>(method, path, options, true);
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Baixa um ARQUIVO da API (Excel, CSV...) com o token e a filial, como `request`; devolve os bytes e o nome
 * que o backend mandou (`Content-Disposition`). Renova o token uma vez se ele venceu.
 */
export async function download(method: "GET" | "POST", path: string, options: { params?: Params; body?: unknown } = {},
                               retried = false): Promise<{ bytes: Uint8Array; filename: string | null; type: string }> {
  if (!state.server) throw new ApiError(0, "Configure o endereço do servidor.", "no_server");
  const insecure = serverProblem(state.server);
  if (insecure) throw new ApiError(0, insecure, "insecure_server"); // endereço antigo com http:// salvo
  await ensureAccess(path);
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (state.access) headers.Authorization = `Bearer ${state.access}`;
  const storeId = state.storeId && state.storeId !== "*" ? state.storeId : state.scopeStore ?? state.storeId;
  if (storeId) headers["X-Store-ID"] = storeId;
  let response: Response;
  // Exportação grande (Excel do relatório) demora mais que uma chamada comum, mas não fica pendurada para sempre.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120_000);
  try {
    response = await fetch(`${state.server}/api/v1${path}${query(options.params)}`, {
      method, headers, body: options.body !== undefined ? JSON.stringify(options.body) : undefined, signal: controller.signal,
    });
  } catch (error: any) {
    throw new ApiError(0, error?.name === "AbortError" ? "O servidor demorou demais para gerar o arquivo. Tente de novo."
      : "Sem conexão com o servidor. Confira o endereço e a rede.", "network");
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 401 && !retried) {
    if (await renewAfter401()) return download(method, path, options, true);
  }
  if (!response.ok) throw await toError(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)?.[1] ?? null;
  return { bytes: new Uint8Array(await response.arrayBuffer()), filename: filename && decodeURIComponent(filename),
           type: response.headers.get("content-type") ?? "application/octet-stream" };
}

/**
 * Endereço de uma mídia (foto de produto, logo) que o celular consegue abrir. O backend manda o caminho relativo
 * (`/media/images/...`) — o navegador da retaguarda completa sozinho, o app não — ou um endereço com
 * `localhost`, que no celular aponta para o próprio aparelho. Os dois viram o servidor configurado no app.
 */
export function mediaUrl(path: unknown): string | null {
  if (typeof path !== "string" || !path) return null;
  if (path.startsWith("data:") || path.startsWith("file:")) return path;
  if (path.startsWith("/")) return `${state.server}${path}`;
  const local = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/i;
  return local.test(path) && state.server ? path.replace(local, state.server) : path;
}

export const api = {
  get: <T>(path: string, params?: Params, store?: string | null) => request<T>("GET", path, { params, store }),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    request<T>("POST", path, { body: body ?? {}, headers }),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, { body }),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, { body }),
  delete: <T>(path: string, body?: unknown) => request<T>("DELETE", path, { body }),
};

export async function login(username: string, password: string) {
  const data = await request<{ access: string; refresh: string }>("POST", "/auth/login/", {
    body: { username, password },
    store: null,
  });
  await saveTokens(data.access, data.refresh);
}

export async function logout() {
  const refresh = state.refresh;
  await saveTokens(null, null);
  await setStoreId(null);
  if (refresh) {
    try {
      await request("POST", "/auth/logout/", { body: { refresh }, store: null, timeoutMs: 5000 });
    } catch {
      /* sair continua mesmo sem rede */
    }
  }
}
