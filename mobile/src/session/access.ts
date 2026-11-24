/**
 * Regras de acesso do app — espelho do backend (`core/permissions.py`):
 * admin da conta/superusuário vê tudo (`"*"`), o resto depende dos códigos
 * `<área>.view` / `<área>.manage` e dos módulos contratados pela conta.
 * O backend confere de novo em toda requisição; aqui só se esconde o que não dá para usar.
 */
import { visibleGroups } from "@front/reports/catalog";

import type { Me } from "@/api/types";

export const MODULE_BASE = "base";

export function can(me: Me | null, code: string) {
  if (!me) return false;
  if (me.is_superuser || me.is_account_admin) return true;
  return me.permissions.includes("*") || me.permissions.includes(code);
}

export function hasModule(me: Me | null, module: string) {
  if (!me) return false;
  if (module === MODULE_BASE || me.is_superuser) return true;
  return Boolean(me.account?.modules.includes(module));
}

/** Permissão E módulo, a mesma dupla que o backend cobra nos relatórios. */
export function allowed(me: Me | null, permission: string, module = MODULE_BASE) {
  return can(me, permission) && hasModule(me, module);
}

/** Funções do app (atalhos da Início e do menu). */
export const FEATURES = {
  stockView: { permission: "stock.view", module: "stock" },
  stockManage: { permission: "stock.manage", module: "stock" },
  catalogView: { permission: "catalog.view", module: MODULE_BASE },
  salesView: { permission: "sales.view", module: MODULE_BASE },
  cashView: { permission: "cash.view", module: MODULE_BASE },
} as const;

export type Feature = keyof typeof FEATURES;

export function canUse(me: Me | null, feature: Feature) {
  const f = FEATURES[feature];
  return allowed(me, f.permission, f.module);
}

/** Relatórios: o MESMO livro da retaguarda (`frontend/src/reports/catalog.ts`), filtrado pelo cargo e módulos. */
export function reportGroups(me: Me | null) {
  return visibleGroups((code) => !code || can(me, code), (module) => !module || hasModule(me, module));
}

export function canSeeReports(me: Me | null) {
  return reportGroups(me).length > 0;
}
