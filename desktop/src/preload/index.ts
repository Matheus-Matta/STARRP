/** Ponte segura entre a tela e o processo principal: só estas funções ficam visíveis em `window.starrp`. */
import { contextBridge, ipcRenderer } from "electron";

import type { StarrpBridge } from "../shared/ipc";

const bridge: StarrpBridge = {
  api: (request) => ipcRenderer.invoke("api:request", request),
  auth: {
    login: (username, password) => ipcRenderer.invoke("auth:login", username, password),
    logout: () => ipcRenderer.invoke("auth:logout"),
    hasSession: () => ipcRenderer.invoke("auth:has-session"),
    onExpired: (listener) => {
      const handler = () => listener();
      ipcRenderer.on("auth:expired", handler);
      return () => ipcRenderer.removeListener("auth:expired", handler);
    },
  },
  config: {
    get: () => ipcRenderer.invoke("config:get"),
    set: (patch) => ipcRenderer.invoke("config:set", patch),
    installationId: (storeId) => ipcRenderer.invoke("config:installation-id", storeId),
  },
  printers: {
    list: () => ipcRenderer.invoke("printers:list"),
    print: (job) => ipcRenderer.invoke("printers:print", job),
    test: (slot, target) => ipcRenderer.invoke("printers:test", slot, target),
  },
  fiscal: {
    secrets: () => ipcRenderer.invoke("fiscal:secrets"),
    setSecrets: (values) => ipcRenderer.invoke("fiscal:set-secrets", values),
    health: () => ipcRenderer.invoke("fiscal:health"),
    storeEmitter: () => ipcRenderer.invoke("fiscal:store-emitter"),
    kit: () => ipcRenderer.invoke("fiscal:kit"),
    refreshKit: () => ipcRenderer.invoke("fiscal:refresh-kit"),
    emit: (request) => ipcRenderer.invoke("fiscal:emit", request),
    invoices: (saleRef) => ipcRenderer.invoke("fiscal:invoices", saleRef),
  },
  local: {
    currentSale: (userId) => ipcRenderer.invoke("local:current", userId),
    saveCurrentSale: (userId, sale) => ipcRenderer.invoke("local:save-current", userId, sale),
    parked: () => ipcRenderer.invoke("local:parked"),
    park: (sale) => ipcRenderer.invoke("local:park", sale),
    unpark: (id) => ipcRenderer.invoke("local:unpark", id),
    history: () => ipcRenderer.invoke("local:history"),
    remember: (sale) => ipcRenderer.invoke("local:remember", sale),
    authorize: (body) => ipcRenderer.invoke("local:authorize", body),
    unlock: (username, password) => ipcRenderer.invoke("local:unlock", username, password),
    cash: () => ipcRenderer.invoke("local:cash"),
    saveCash: (state) => ipcRenderer.invoke("local:save-cash", state),
  },
  offline: {
    status: () => ipcRenderer.invoke("offline:status"),
    onStatus: (listener) => {
      const handler = (_e: unknown, status: Parameters<typeof listener>[0]) => listener(status);
      ipcRenderer.on("net:status", handler);
      return () => ipcRenderer.removeListener("net:status", handler);
    },
    snapshot: () => ipcRenderer.invoke("offline:snapshot"),
    refreshSnapshot: () => ipcRenderer.invoke("offline:refresh-snapshot"),
    cache: () => ipcRenderer.invoke("offline:cache"),
    saveCache: (cache) => ipcRenderer.invoke("offline:save-cache", cache),
    enqueueSale: (payload, label, hold) => ipcRenderer.invoke("offline:enqueue-sale", payload, label, hold),
    flush: (id) => ipcRenderer.invoke("offline:flush", id),
    enqueueCash: (payload, label) => ipcRenderer.invoke("offline:enqueue-cash", payload, label),
    nextLocalNumber: () => ipcRenderer.invoke("offline:next-number"),
    outbox: () => ipcRenderer.invoke("offline:outbox"),
    retry: (id) => ipcRenderer.invoke("offline:retry", id),
    discard: (id) => ipcRenderer.invoke("offline:discard", id),
    syncNow: () => ipcRenderer.invoke("offline:sync-now"),
  },
  app: {
    version: () => ipcRenderer.invoke("app:version"),
    toggleFullscreen: () => ipcRenderer.invoke("app:fullscreen"),
    quit: () => ipcRenderer.invoke("app:quit"),
  },
};

contextBridge.exposeInMainWorld("starrp", bridge);
