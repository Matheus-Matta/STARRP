/**
 * Sessão: quem está logado, em qual conta, quais lojas acessa e qual está ativa.
 *
 * A loja ativa é lembrada no navegador, mas SEMPRE revalidada contra `/me/`:
 * se o acesso à loja foi retirado, ela é descartada e o backend escolhe outra.
 * As permissões aqui só escondem botões — quem barra de verdade é o backend.
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { authApi } from "@/api/auth";
import { ApiError } from "@/api/errors";
import { configureHttp } from "@/api/http";
import type { Me } from "@/api/types";

const STORE_KEY = "starrp.activeStore";
/** Valor do header que pede a visão consolidada das lojas permitidas. */
export const ALL_STORES = "*";

function readStoredStore() {
  try {
    return localStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
}

export const useSession = defineStore("session", () => {
  const me = ref<Me | null>(null);
  const activeStoreId = ref<string | null>(readStoredStore());
  const loaded = ref(false);

  const isAuthenticated = computed(() => me.value !== null);
  /** Vendedor e operador de caixa trabalham no PDV: entram direto nele. */
  /** Vendedor/caixa entram direto no PDV — só se TODOS os cargos dele são de frente de loja
   *  (caixa que também é da logística precisa da retaguarda). */
  const pdvFirst = computed(() => {
    const codes = (me.value?.roles?.length ? me.value.roles : me.value?.role ? [me.value.role] : []).map((r) => r.code);
    return codes.length > 0 && codes.every((c) => ["seller", "cashier"].includes(c));
  });
  const stores = computed(() => me.value?.stores ?? []);
  const activeStore = computed(() => stores.value.find((s) => s.id === activeStoreId.value) ?? null);
  /** Telas que operam UMA loja (PDV, caixa) exigem loja ativa concreta. */
  const hasConcreteStore = computed(() => activeStore.value !== null);

  function setActiveStore(id: string | null) {
    activeStoreId.value = id;
    try {
      if (id) localStorage.setItem(STORE_KEY, id);
      else localStorage.removeItem(STORE_KEY);
    } catch {
      // navegador sem storage (aba privada): a escolha vale só nesta aba
    }
  }

  async function load() {
    try {
      me.value = await authApi.me(activeStoreId.value);
    } catch (error) {
      me.value = null;
      // A loja lembrada perdeu o acesso: esquece e deixa o backend escolher.
      if (error instanceof ApiError && error.code === "store_forbidden") {
        setActiveStore(null);
        me.value = await authApi.me().catch(() => null);
      }
    } finally {
      loaded.value = true;
    }
    if (me.value && activeStoreId.value !== ALL_STORES) setActiveStore(me.value.active_store_id);
    return me.value;
  }

  async function login(username: string, password: string) {
    await authApi.login(username, password);
    return load();
  }

  async function logout() {
    await authApi.logout().catch(() => undefined);
    me.value = null;
  }

  function can(code: string | undefined) {
    if (!code) return true;
    const perms = me.value?.permissions ?? [];
    return perms.includes("*") || perms.includes(code);
  }

  function hasModule(module: string | undefined) {
    return !module || module === "base" || (me.value?.account?.modules ?? []).includes(module);
  }

  return { me, loaded, isAuthenticated, stores, activeStore, activeStoreId, hasConcreteStore, setActiveStore, load,
    login, logout, can, hasModule, pdvFirst };
});

/** Liga o cliente HTTP à sessão. Chamado uma vez em `main.ts`. */
export function bindHttpToSession(onUnauthorized: () => void) {
  const session = useSession();
  configureHttp({
    storeId: () => session.activeStoreId,
    onUnauthorized: () => {
      session.me = null;
      onUnauthorized();
    },
  });
}
