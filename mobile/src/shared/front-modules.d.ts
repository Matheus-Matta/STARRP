/**
 * Tipos dos módulos da retaguarda que o app usa (`@front/...`, resolvidos pelo metro.config.js).
 * Só o que o app chama; o formato dos cadastros vem de `./types` (gerado do frontend).
 */
declare module "@front/resources" {
  import type { ResourceDef } from "@/shared/types";

  export const resources: ResourceDef[];
  export function findResource(name: string): ResourceDef | undefined;
}

declare module "@front/utils/costs" {
  /** `catalog.view_costs`: sem ela, `findResource` devolve o cadastro sem colunas/itens de custo e margem. */
  export const COST_PERMISSION: string;
  export function setSeesCosts(value: boolean): void;
  export function isCostEntry(entry: { key?: string; label?: string; title?: unknown }): boolean;
}

declare module "@front/components/layout/navigation" {
  export type NavItem = {
    label: string; icon: string; to: string; permission?: string; module?: string;
    children?: { label: string; icon: string; items: NavItem[] }[];
  };
  export type NavGroup = { label: string; items: NavItem[] };
  export function buildNavigation(can: (code?: string) => boolean, hasModule: (m?: string) => boolean): NavGroup[];
}

declare module "@front/reports/catalog" {
  export type ReportAbout = { purpose: string; read: string[]; decide: string[] };
  export type ReportDef = { slug: string; title: string; description: string; icon: string; permission: string;
                            module?: string; about: ReportAbout };
  export type ReportGroup = { label: string; icon: string; description: string; reports: ReportDef[] };
  export const REPORT_GROUPS: ReportGroup[];
  export function findReport(slug: string): (ReportDef & { group: string }) | undefined;
  export function visibleGroups(can: (code?: string) => boolean, hasModule: (m?: string) => boolean): ReportGroup[];
}

declare module "@front/utils/validation" {
  import type { FieldDef } from "@/shared/types";

  export function validate(fields: FieldDef[], values: Record<string, unknown>): Record<string, string>;
  export function validateField(field: FieldDef, values: Record<string, unknown>): string | undefined;
}

declare module "@front/utils/format" {
  export function money(value: unknown): string;
  export function quantity(value: unknown): string;
  export function percent(value: unknown): string;
  export function date(value: unknown): string;
  export function dateTime(value: unknown): string;
}

declare module "@front/utils/masks" {
  export const MASKS: Record<"cpf" | "cnpj" | "phone" | "mobile" | "cep" | "ncm" | "cest" | "ibge", string>;
  export function applyMask(value: unknown, mask: string): string;
  export function formatPhone(value: unknown): string;
  export type CepAddress = { street: string; district: string; city: string; state: string; city_ibge: string;
                             complement: string; source: string };
  export function lookupCep(cep: string): Promise<CepAddress | null>;
}

declare module "@front/utils/formats" {
  export function formatOf(field: { type?: string; format?: string }): { mask?: string } | undefined;
}

declare module "@front/utils/documents" {
  export function formatDocument(value: string): string;
}

declare module "@front/utils/fieldHints" {
  import type { FieldDef } from "@/shared/types";

  export function unitOf(field: Pick<FieldDef, "label" | "unit">): string | undefined;
  export function placeholderOf(field: FieldDef): string | undefined;
}

declare module "@front/api/operations" {
  export type Balances = { accounts: { id: string; name: string; kind: string; balance: string }[]; total: string };
  export type Aging = Record<"receivable" | "payable", Record<"overdue" | "next_7_days" | "next_30_days" | "later", string>>;
  export type CashFlow = {
    period: { from: string; to: string };
    opening_balance: string; inflow: string; outflow: string; closing_balance: string;
    by_day: { date: string; inflow: string; outflow: string }[];
    by_category: { category__name: string; kind: string; total: string }[];
    forecast: Partial<Record<"receivable" | "payable", string>>;
  };
  export const financeApi: {
    balances: () => Promise<Balances>;
    aging: () => Promise<Aging>;
    cashFlow: (params: Record<string, string | number | undefined>) => Promise<CashFlow>;
  };
}

declare module "@front/api/notifications" {
  export type AppNotification = {
    id: string; category: "system" | "sales" | "cash" | "stock" | "fiscal" | "finance";
    level: "info" | "success" | "warning" | "error"; title: string; body: string; url: string; entity: string;
    object_id: string; read_at: string | null; created_at: string;
  };
  export const notificationsApi: {
    list: () => Promise<{ count: number; results: AppNotification[] }>;
    unreadCount: () => Promise<number>;
    read: (id: string) => Promise<AppNotification>;
    readAll: () => Promise<number>;
  };
}

declare module "@front/utils/notifications" {
  import type { AppNotification } from "@front/api/notifications";
  export const NOTIFICATION_CATEGORIES: Record<AppNotification["category"], { label: string; icon: string }>;
  export const NOTIFICATION_LEVELS: Record<AppNotification["level"], { label: string; icon: string }>;
  export function notificationRelative(value: string): string;
}
