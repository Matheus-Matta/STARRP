/**
 * Conexão com o servidor, vista pela tela. Quem decide é o processo principal (`sync.ts`):
 * ele verifica o servidor de 15 em 15 s e também marca offline na hora em que uma chamada
 * falha por rede ou erro interno (5xx). Aqui só se escuta.
 */
import { ApiError } from "@/api/errors";

import type { NetStatus } from "../../../shared/ipc";
import { createStore } from "./store";

export const net = createStore<NetStatus>({
  online: true, pending: 0, failed: 0, lastSync: null, snapshotAt: null, syncing: false,
});

export function watchNet() {
  void window.starrp.offline.status().then((s) => net.set(s));
  return window.starrp.offline.onStatus((s) => net.set(s));
}

export const isOffline = () => !net.get().online;

/** Falha que é do servidor/rede (dá para seguir offline), e não uma recusa de regra de negócio. */
export const isNetworkError = (error: unknown) => error instanceof ApiError && (error.status === 0 || error.status >= 500);
