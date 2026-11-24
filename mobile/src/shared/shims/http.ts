/**
 * Substituto do cliente HTTP da retaguarda (axios): mesma forma (`http.get(url, { params })` → `{ data }`),
 * mas pelo cliente do app (token, filial ativa, renovação do token e erros já traduzidos).
 */
import { type Params, request } from "@/api/client";

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type ListParams = Record<string, string | number | boolean | undefined | null>;

type Config = { params?: ListParams; headers?: Record<string, string> };

const wrap = <T>(promise: Promise<T>) => promise.then((data) => ({ data, status: 200 }));

export const http = {
  get: <T>(url: string, config: Config = {}) => wrap(request<T>("GET", url, { params: config.params as Params })),
  delete: <T>(url: string, config: Config = {}) => wrap(request<T>("DELETE", url, { params: config.params as Params })),
  post: <T>(url: string, body?: unknown, config: Config = {}) =>
    wrap(request<T>("POST", url, { body: body ?? {}, params: config.params as Params })),
  patch: <T>(url: string, body?: unknown, config: Config = {}) =>
    wrap(request<T>("PATCH", url, { body: body ?? {}, params: config.params as Params })),
  put: <T>(url: string, body?: unknown, config: Config = {}) =>
    wrap(request<T>("PUT", url, { body: body ?? {}, params: config.params as Params })),
  defaults: { baseURL: "/api/v1" },
};

export function configureHttp() {}

export function cleanParams(params: ListParams = {}) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null));
}

export function idempotencyKey() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}
