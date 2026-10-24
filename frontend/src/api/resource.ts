/** CRUD genérico para os cadastros declarados em `resources/`. */
import { cleanParams, http, type ListParams, type Page } from "./http";

export type Row = Record<string, unknown> & { id: string };

export const resourceApi = {
  list: <T = Row>(endpoint: string, params?: ListParams) =>
    http.get<Page<T>>(endpoint, { params: cleanParams(params) }).then((r) => r.data),
  get: <T = Row>(endpoint: string, id: string) => http.get<T>(`${endpoint}${id}/`).then((r) => r.data),
  create: <T = Row>(endpoint: string, body: Record<string, unknown>) =>
    http.post<T>(endpoint, body).then((r) => r.data),
  update: <T = Row>(endpoint: string, id: string, body: Record<string, unknown>) =>
    http.patch<T>(`${endpoint}${id}/`, body).then((r) => r.data),
  remove: (endpoint: string, id: string) => http.delete(`${endpoint}${id}/`),
};
