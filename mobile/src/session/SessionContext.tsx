/**
 * Sessão do app: carrega servidor/tokens salvos, faz login, lê `/me/`
 * (permissões, cargos, módulos e filiais) e guarda a filial ativa.
 */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { AppState } from "react-native";

import { COST_PERMISSION, setSeesCosts } from "@front/utils/costs";

import * as client from "@/api/client";
import type { Me } from "@/api/types";
import { allowed, can, canUse, type Feature, hasModule } from "@/session/access";

type Status = "loading" | "signedOut" | "signedIn" | "unreachable";

type Session = {
  status: Status;
  me: Me | null;
  server: string;
  storeId: string | null;
  storeName: string;
  signIn: (server: string, username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  resume: () => Promise<void>;
  reload: () => Promise<void>;
  selectStore: (id: string | null) => Promise<void>;
  can: (code: string) => boolean;
  hasModule: (module: string) => boolean;
  allowed: (permission: string, module?: string) => boolean;
  canUse: (feature: Feature) => boolean;
};

const SessionContext = createContext<Session | null>(null);

/** "*" = todas as filiais permitidas (visão consolidada, sem filial ativa). */
export const ALL_STORES = "*";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [server, setServerState] = useState("");
  const [storeId, setStoreIdState] = useState<string | null>(null);

  const fetchMe = useCallback(async () => {
    const data = await client.api.get<Me>("/me/");
    // Filial salva que o usuário não acessa mais: volta para a que o backend escolheu.
    let current = client.getStoreId();
    const known = current === ALL_STORES || data.stores.some((s) => s.id === current);
    if (!current || !known || (current === ALL_STORES && !data.all_stores && data.stores.length <= 1)) {
      current = data.active_store_id ?? data.default_store_id ?? data.stores[0]?.id ?? null;
      await client.setStoreId(current);
    }
    client.setDefaultStore(data.default_store_id ?? data.stores[0]?.id ?? null);
    setStoreIdState(current);
    // Cadastros da retaguarda (`findResource`) sem colunas de custo/margem para quem não tem a permissão.
    setSeesCosts(can(data, COST_PERMISSION));
    setMe(data);
    return data;
  }, []);

  const signOut = useCallback(async () => {
    await client.logout();
    setMe(null);
    setStoreIdState(null);
    setStatus("signedOut");
  }, []);

  /** Retoma o login salvo. Sem rede, não derruba a sessão: mostra "tentar de novo". */
  const resume = useCallback(async () => {
    setStatus("loading");
    try {
      await fetchMe();
      setStatus("signedIn");
    } catch (error) {
      // Endereço salvo com http:// no app de produção: vai ao login para trocar (tentar de novo não resolve).
      if (error instanceof client.ApiError && error.code === "insecure_server") setStatus("signedOut");
      else if (error instanceof client.ApiError && error.status === 0) setStatus("unreachable");
      else await signOut();
    }
  }, [fetchMe, signOut]);

  useEffect(() => {
    client.setUnauthorizedHandler(() => {
      void signOut();
    });
    (async () => {
      const stored = await client.loadStoredSession();
      setServerState(stored.server);
      if (!stored.hasToken) {
        setStatus("signedOut");
        return;
      }
      await resume();
    })();
  }, [resume, signOut]);

  // Voltou do segundo plano: confere a sessão no servidor (usuário desativado, senha trocada, token revogado →
  // o 401 encerra a sessão e o app volta para o login). Sem rede, não derruba: fica como está.
  useEffect(() => {
    if (status !== "signedIn") return;
    const subscription = AppState.addEventListener("change", (next) => {
      if (next === "active") void fetchMe().catch(() => undefined);
    });
    return () => subscription.remove();
  }, [status, fetchMe]);

  const signIn = useCallback(
    async (address: string, username: string, password: string) => {
      await client.setServer(address);
      setServerState(client.getServer());
      await client.setStoreId(null);
      await client.login(username.trim(), password);
      await fetchMe();
      setStatus("signedIn");
    },
    [fetchMe],
  );

  const selectStore = useCallback(
    async (id: string | null) => {
      await client.setStoreId(id);
      setStoreIdState(id);
      await fetchMe();
    },
    [fetchMe],
  );

  const value = useMemo<Session>(() => {
    const storeName =
      storeId === ALL_STORES
        ? "Todas as filiais"
        : me?.stores.find((s) => s.id === storeId)?.name ?? (me?.stores.length ? "Selecione a filial" : "—");
    return {
      status,
      me,
      server,
      storeId,
      storeName,
      signIn,
      signOut,
      resume,
      reload: async () => {
        await fetchMe();
      },
      selectStore,
      can: (code) => can(me, code),
      hasModule: (module) => hasModule(me, module),
      allowed: (permission, module) => allowed(me, permission, module),
      canUse: (feature) => canUse(me, feature),
    };
  }, [status, me, server, storeId, signIn, signOut, resume, selectStore, fetchMe]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession fora do SessionProvider");
  return session;
}
