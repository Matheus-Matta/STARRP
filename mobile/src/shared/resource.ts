/**
 * Regras das telas genéricas de cadastro, as mesmas da retaguarda (ResourceListPage/ResourceFormPage):
 * quem cria, edita e exclui; para onde a linha leva; e o CRUD pela API.
 */
import type { Href } from "expo-router";

import { api, type Page } from "@/api/client";
import type { Me } from "@/api/types";
import { hrefFor } from "@/shared/frontend";
import type { FieldDef, ResourceDef } from "@/shared/types";

export type Row = Record<string, unknown> & { id: string };

export const resourceApi = {
  list: (endpoint: string, params: Record<string, unknown> = {}) =>
    api.get<Page<Row>>(endpoint, clean(params) as Record<string, string>),
  get: (endpoint: string, id: string) => api.get<Row>(`${endpoint}${id}/`),
  create: (endpoint: string, body: Record<string, unknown>) => api.post<Row>(endpoint, body),
  update: (endpoint: string, id: string, body: Record<string, unknown>) => api.patch<Row>(`${endpoint}${id}/`, body),
  remove: (endpoint: string, id: string) => api.delete(`${endpoint}${id}/`),
};

function clean(params: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    .map(([k, v]) => [k, String(v)]));
}

/** Diálogo ou tela própria da retaguarda (Vue): no app vira "só na retaguarda". */
export const isWebOnly = (component: unknown) => Boolean(component && typeof component === "object"
  && (component as Record<string, unknown>).__starrpWebOnly);

type Can = (code?: string) => boolean;

export function accessOf(resource: ResourceDef, can: Can, me: Me | null) {
  const canWrite = !resource.readOnly && can(`${resource.permission}.manage`);
  const locked = Boolean(resource.systemData) && !me?.is_superuser;
  return {
    canWrite,
    canCreate: MOBILE_SCREENS[resource.name]?.canCreate?.(can) ?? (canWrite && resource.creatable !== false && !locked),
    canDelete: canWrite && resource.deletable !== false && !locked,
    /** Registro salvo: edita se o cadastro deixa e ele não está travado (confirmado, cancelado...). */
    canEdit: (values: Record<string, unknown>) => canWrite && resource.editable !== false && !resource.lockedWhen?.(values),
  };
}

/**
 * Telas próprias do app que fazem melhor que o formulário genérico (leitor de código, quantidades com +/−):
 * lançamento de estoque cria e edita pela tela do app.
 */
const MOBILE_SCREENS: Record<string, { create: (query: Record<string, string>) => Href; edit: (id: string) => Href;
                                        canCreate?: (can: Can) => boolean }> = {
  "entradas-e-saidas": {
    create: (q) => ({ pathname: "/documentos/novo", params: q.kind ? { kind: q.kind } : {} }),
    edit: (id) => ({ pathname: "/documentos/novo", params: { id } }),
  },
  // Venda não tem formulário: nasce no PDV. No celular, o "PDV móvel".
  vendas: {
    create: () => "/venda",
    edit: (id) => ({ pathname: "/venda", params: { id } }),
    canCreate: (can) => can("sales.manage"),
  },
};

export function createHref(resource: ResourceDef, query: Record<string, string> = {}): Href {
  return MOBILE_SCREENS[resource.name]?.create(query)
    ?? { pathname: "/cadastros/[resource]/novo", params: { resource: resource.name, ...query } };
}

export function editHref(resource: ResourceDef, id: string): Href {
  return MOBILE_SCREENS[resource.name]?.edit(id)
    ?? { pathname: "/cadastros/[resource]/[id]/editar", params: { resource: resource.name, id } };
}

export function recordHref(resource: ResourceDef, id: string): Href {
  return { pathname: "/cadastros/[resource]/[id]", params: { resource: resource.name, id } };
}

/** Para onde a linha leva: o `rowLink` do cadastro (traduzido) ou o próprio registro. */
export function rowHref(resource: ResourceDef, row: Row): Href {
  const to = resource.rowLink?.(row);
  return to ? hrefFor(to) : recordHref(resource, String(row.id));
}

/** Valores iniciais do cadastro novo: padrões dos campos + valores fixos do cadastro. */
export function defaultsOf(resource: ResourceDef) {
  const values = Object.fromEntries(resource.fields.filter((f) => f.default !== undefined).map((f) => [f.name, f.default]));
  return { ...values, ...resource.params } as Record<string, unknown>;
}

/** Só os campos do formulário vão para a API; senha vazia não troca a senha. */
export function payloadOf(resource: ResourceDef, values: Record<string, unknown>, isNew: boolean) {
  const body: Record<string, unknown> = isNew ? { ...resource.params } : {};
  for (const field of resource.fields) {
    if (!(field.name in values)) continue;
    const value = values[field.name];
    if (field.type === "password" && !value) continue;
    body[field.name] = value === undefined ? null : value;
  }
  return body;
}

/** Seções do formulário, com os campos que valem agora (condição, só-criação, permissão, módulo). */
export function formSections(resource: ResourceDef, values: Record<string, unknown>, isNew: boolean, can: Can,
                             hasModule: Can) {
  const groups = new Map<string, FieldDef[]>();
  for (const field of resource.fields) {
    if (field.visible && !field.visible(values)) continue;
    if (field.createOnly && !isNew) continue;
    if (field.permission && !can(field.permission)) continue;
    if (field.module && !hasModule(field.module)) continue;
    const name = field.section ?? "Dados";
    groups.set(name, [...(groups.get(name) ?? []), field]);
  }
  return [...groups.entries()];
}

/** "Novo produto" / "Nova conta a pagar". */
export const newLabel = (r: ResourceDef) => `${r.feminine ? "Nova" : "Novo"} ${r.singular}`;
