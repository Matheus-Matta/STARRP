/** Configuração do PDV (servidor, loja, terminal), num JSON na pasta de dados do app. */
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { hostname } from "node:os";
import { dirname, join } from "node:path";

import { app } from "electron";

import type { AppConfig, PrinterTarget } from "../shared/ipc";
import { acbrUrlProblem, normalizeServerUrl, serverUrlProblem } from "../shared/serverUrl";
import { clearTokens } from "./tokens";

const file = () => join(app.getPath("userData"), "config.json");

const defaults = (): AppConfig => ({
  serverUrl: process.env.STARRP_SERVER_URL ?? "http://localhost:8001",
  storeId: null,
  terminalName: `PDV ${hostname()}`,
  installations: {},
  theme: "light",
  printing: {
    mode: "direct", autoReceipt: true, autoInvoice: true, copies: 1, openDrawer: false,
    receipt: printer(), fiscal: printer(),
  },
  fiscal: { enabled: false, acbrUrl: "http://127.0.0.1:8030", model: "65", autoEmit: true, contingency: true },
});

const printer = (): PrinterTarget => ({ kind: "system", name: "", host: "", port: 9100, paper: 80 });

let cached: AppConfig | null = null;

export function getConfig(): AppConfig {
  if (cached) return cached;
  let stored: Partial<AppConfig> = {};
  try {
    if (existsSync(file())) stored = JSON.parse(readFileSync(file(), "utf8")) as Partial<AppConfig>;
  } catch {
    stored = {}; // arquivo corrompido: volta ao padrão
  }
  const base = defaults();
  const legacy = stored as Partial<AppConfig> & { silentPrint?: boolean };
  cached = {
    ...base, ...stored,
    // Configurações em grupos: o que faltar no arquivo (versão antiga) vem do padrão.
    printing: {
      ...base.printing, ...(legacy.silentPrint === false ? { mode: "ask" as const } : {}), ...stored.printing,
      receipt: { ...base.printing.receipt, ...stored.printing?.receipt },
      fiscal: { ...base.printing.fiscal, ...stored.printing?.fiscal },
    },
    fiscal: { ...base.fiscal, ...stored.fiscal },
  };
  return cached;
}

export function setConfig(patch: Partial<AppConfig>): AppConfig {
  const before = getConfig();
  const next = { ...before, ...patch };
  if (patch.serverUrl !== undefined) {
    next.serverUrl = normalizeServerUrl(patch.serverUrl);
    const problem = serverUrlProblem(next.serverUrl, app.isPackaged);
    if (problem) throw new Error(problem);
    // Outro servidor: o login deste não vale lá (e o token nunca vai para um servidor diferente).
    if (next.serverUrl !== before.serverUrl) clearTokens();
  }
  if (patch.fiscal?.acbrUrl !== undefined) {
    const acbrUrl = normalizeServerUrl(patch.fiscal.acbrUrl);
    const problem = acbrUrlProblem(acbrUrl);
    if (problem) throw new Error(problem);
    next.fiscal = { ...next.fiscal, acbrUrl };
  }
  mkdirSync(dirname(file()), { recursive: true });
  writeFileSync(file(), JSON.stringify(next, null, 2));
  cached = next;
  return next;
}

/** Um installation_id fixo por loja: o mesmo computador vira um terminal em cada loja. */
export function installationId(storeId: string): string {
  const config = getConfig();
  const existing = config.installations[storeId];
  if (existing) return existing;
  const id = randomUUID();
  setConfig({ installations: { ...config.installations, [storeId]: id } });
  return id;
}
