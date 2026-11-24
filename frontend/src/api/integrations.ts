/** Integrações da conta (Asaas, Shopify...): tipos declarados no backend e as integrações salvas. */
import { http } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export type IntegrationFieldType = "text" | "secret" | "url" | "email" | "number" | "boolean" | "select" | "relation";
export type IntegrationField = {
  name: string; label: string; type: IntegrationFieldType; required: boolean; default: unknown; help: string;
  placeholder: string; options: { value: string; label: string }[]; relation: string | null;
  when: Record<string, string[]> | null;
};
export type IntegrationPurpose = { key: string; label: string; description: string; default: boolean };
export type IntegrationType = {
  key: string; label: string; description: string; category: string; icon: string; logo: string | null; docs_url: string;
  multiple: boolean; available: boolean; testable: boolean; fields: IntegrationField[]; purposes: IntegrationPurpose[];
};
export type Integration = {
  id: string; kind: string; kind_label: string; name: string; is_active: boolean; is_default: boolean;
  fields: Record<string, unknown>; purposes: string[]; purpose_labels: string[]; notes: string;
  last_check_at: string | null; last_check_ok: boolean | null; last_check_message: string; updated_at: string;
};
export type IntegrationInput = Partial<Pick<Integration, "kind" | "name" | "is_active" | "is_default" | "fields" |
  "purposes" | "notes">>;
export type CheckResult = { ok: boolean; message: string; data: Record<string, unknown> };

/** O que a tela recebe no lugar de um segredo já guardado (mandar de volta = manter). */
export const SECRET_MASK = "••••••••";

type Page<T> = { results: T[] } | T[];
const rows = <T>(page: Page<T>) => (Array.isArray(page) ? page : page.results);

export const integrationsApi = {
  types: () => data(http.get<IntegrationType[]>("/integrations/types/")),
  list: () => data(http.get<Page<Integration>>("/integrations/", { params: { page_size: 200 } })).then(rows),
  create: (input: IntegrationInput) => data(http.post<Integration>("/integrations/", input)),
  update: (id: string, input: IntegrationInput) => data(http.patch<Integration>(`/integrations/${id}/`, input)),
  remove: (id: string) => http.delete(`/integrations/${id}/`),
  /** Testa valores ainda não salvos (com `id`, os segredos em branco usam os guardados). */
  check: (kind: string, fields: Record<string, unknown>, id?: string) =>
    data(http.post<CheckResult>("/integrations/check/", { kind, fields, id }, { timeout: 40_000 })),
  test: (id: string) => data(http.post<CheckResult>(`/integrations/${id}/test/`, {}, { timeout: 40_000 })),
};
