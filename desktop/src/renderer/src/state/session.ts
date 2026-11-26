/**
 * Sessão do PDV: quem está logado e em qual loja.
 *
 * O login vai pela API (`/auth/login/`); o access e o refresh token ficam no processo principal,
 * criptografados no disco — reabrir o PDV entra direto enquanto o refresh valer (7 dias).
 * A loja do PDV fica na configuração do app e é SEMPRE revalidada contra `/me/`.
 */
import { setServerUrl } from "@/api/client";
import { ApiError, fromResponse } from "@/api/errors";
import { authApi } from "@/api/pdv";
import type { Me } from "@/api/types";

import { notify } from "./toast";

import type { AppConfig } from "../../../shared/ipc";
import { createStore } from "./store";

export type Session = {
  status: "loading" | "anonymous" | "ready";
  /** Entrou com o último usuário guardado porque o servidor não respondeu. */
  offline?: boolean;
  me: Me | null;
  config: AppConfig | null;
  storeId: string | null;
};

export const session = createStore<Session>({ status: "loading", me: null, config: null, storeId: null });

const patch = (next: Partial<Session>) => session.set((prev) => ({ ...prev, ...next }));

export async function loadConfig() {
  const config = await window.starrp.config.get();
  setServerUrl(config.serverUrl);
  applyTheme(config.theme);
  patch({ config });
  return config;
}

export async function saveConfig(changes: Partial<AppConfig>) {
  const config = await window.starrp.config.set(changes);
  setServerUrl(config.serverUrl);
  patch({ config });
  return config;
}

/** Carrega o usuário e acerta a loja do PDV (a lembrada, se ainda tiver acesso; senão a padrão). */
export async function loadSession(): Promise<Me | null> {
  const config = session.get().config ?? (await loadConfig());
  if (!(await window.starrp.auth.hasSession())) {
    patch({ status: "anonymous", me: null });
    return null;
  }
  let me: Me | null = null;
  try {
    me = await authApi.me(config.storeId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "store_forbidden") {
      await saveConfig({ storeId: null }); // perdeu o acesso à loja lembrada
      me = await authApi.me().catch(() => null);
    } else if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
      // Servidor fora (ou com erro): entra com o último usuário guardado e vende offline.
      const cached = (await window.starrp.offline.cache()).me as Me | undefined;
      if (!cached) throw error; // nunca entrou online neste PC: não há com o que trabalhar
      const storeId = cached.stores.find((s) => s.id === config.storeId)?.id ?? null;
      if (!storeId) throw error;
      patch({ status: "ready", me: cached, storeId, offline: true });
      return cached;
    }
  }
  if (!me) {
    patch({ status: "anonymous", me: null });
    return null;
  }
  const remembered = me.stores.find((s) => s.id === config.storeId)?.id;
  const storeId = remembered ?? me.default_store_id ?? me.active_store_id ?? me.stores[0]?.id ?? null;
  if (storeId !== config.storeId) await saveConfig({ storeId });
  patch({ status: "ready", me, storeId, offline: false });
  const cache = await window.starrp.offline.cache();
  await window.starrp.offline.saveCache({ ...cache, me });
  return me;
}

export async function login(username: string, password: string) {
  const result = await window.starrp.auth.login(username, password);
  if (!result.ok) throw fromResponse(result.status, result.data);
  return loadSession();
}

export async function logout() {
  await window.starrp.auth.logout();
  patch({ status: "anonymous", me: null });
}

export async function switchStore(storeId: string) {
  const problem = await window.starrp.config.switchProblem();
  if (problem) {
    notify.warn("Filial não trocada", problem);
    return;
  }
  await saveConfig({ storeId });
  patch({ storeId });
}

export function expire() {
  patch({ status: "anonymous", me: null });
}

export function applyTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
}

export async function toggleTheme() {
  const next = session.get().config?.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  await saveConfig({ theme: next });
}

export const can = (me: Me | null, code: string) => {
  const perms = me?.permissions ?? [];
  return perms.includes("*") || perms.includes(code);
};
