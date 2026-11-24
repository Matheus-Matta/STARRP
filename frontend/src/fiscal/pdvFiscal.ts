/**
 * Nota fiscal do PDV web (nuvem), com o MESMO núcleo do PDV desktop (`shared/fiscal/engine.ts`):
 * a nota é montada igual nos dois.
 *
 * O navegador NÃO fala com o comunicador: manda o INI ao backend (`POST /pdv/acbr/`), que chama
 * o Comunicador Fiscal em Docker (modo `nuvem`, app-fiscal-acbr) com o token, a cifra de ponta a
 * ponta e o certificado A1 + CSC dos dados fiscais da filial. Nenhum segredo vem ao navegador.
 *
 * Guardado NESTE navegador (por filial): os ajustes de emissão, o kit fiscal (sem segredo), a
 * numeração do terminal e as notas até o servidor saber.
 */
import { reactive } from "vue";

import { createFiscal } from "../../../shared/fiscal/engine";
import { cloudTransport } from "../../../shared/fiscal/transport";
import type { Kit, LocalInvoice, Numbers } from "../../../shared/fiscal/types";
import { http } from "@/api/http";
import { useSession } from "@/stores/session";

export type { LocalInvoice };

export type FiscalSettings = {
  enabled: boolean;
  model: "65" | "55";
  autoEmit: boolean;
  contingency: boolean;
};

const SETTINGS_KEY = "starrp.pdv.fiscal";
const DEFAULTS: FiscalSettings = { enabled: false, model: "65", autoEmit: true, contingency: true };

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? ({ ...fallback, ...JSON.parse(raw) } as T) : fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // armazenamento cheio/bloqueado: vale até fechar a aba
  }
}

/** Ajustes deste navegador (reativo: a tela do PDV e o diálogo leem o mesmo). */
// Antes o navegador chamava o comunicador e guardava endereço, token e chave: saem daqui.
const stored = read<FiscalSettings & { url?: string; token?: string; key?: string }>(SETTINGS_KEY, DEFAULTS);
const clean: FiscalSettings = { enabled: stored.enabled, model: stored.model, autoEmit: stored.autoEmit, contingency: stored.contingency };
export const fiscalSettings = reactive<FiscalSettings>(clean);
if (stored.token || stored.key || stored.url) write(SETTINGS_KEY, clean);
export function saveFiscalSettings(patch: Partial<FiscalSettings>) {
  Object.assign(fiscalSettings, patch);
  write(SETTINGS_KEY, { ...fiscalSettings });
}

const storeId = () => useSession().activeStoreId ?? null;
const scoped = (name: string) => `starrp.fiscal.${name}:${storeId() ?? "none"}`;
const TERMINAL_KEY = "starrp.pdv.terminal"; // o mesmo id do bootstrap do PDV web

function asResponse(promise: Promise<{ status: number; data: unknown }>) {
  return promise
    .then((r) => ({ ok: true, status: r.status, data: r.data }))
    .catch((error: { response?: { status: number; data: unknown } }) => ({
      ok: false, status: error.response?.status ?? 0, data: error.response?.data ?? null,
    }));
}

const server = {
  get: (path: string, params?: Record<string, string>) => asResponse(http.get(path, { params })),
  post: (path: string, data: unknown) => asResponse(http.post(path, data, { timeout: 90_000 })),
};

export const fiscal = createFiscal({
  storage: {
    kit: () => {
      const raw = localStorage.getItem(scoped("kit"));
      return raw ? (JSON.parse(raw) as Kit) : null;
    },
    saveKit: (kit) => write(scoped("kit"), kit),
    numbers: () => read<Numbers>(scoped("numbers"), { series: {}, next: {}, bySale: {} }),
    saveNumbers: (numbers) => write(scoped("numbers"), numbers),
    invoices: () => {
      try {
        return JSON.parse(localStorage.getItem(scoped("invoices")) ?? "[]") as LocalInvoice[];
      } catch {
        return [];
      }
    },
    saveInvoices: (invoices) => write(scoped("invoices"), invoices),
  },
  server,
  transport: cloudTransport(server),
  storeId,
  installationId: () => localStorage.getItem(TERMINAL_KEY) ?? "",
});

/** Emite a nota da venda concluída e já registra no servidor (devolve a nota com o id de lá). */
export async function emitForSale(sale: Record<string, unknown> & { id: string }, model = fiscalSettings.model) {
  const result = await fiscal.emit({ sale, model, saleRef: sale.id }, { contingency: fiscalSettings.contingency });
  if (result.invoice && !result.invoice.server_invoice_id) {
    await fiscal.registerInvoice(result.invoice);
    return { ...result, invoice: fiscal.invoicesFor(sale.id).find((i) => i.key === result.invoice!.key) ?? result.invoice };
  }
  return result;
}

let timer: ReturnType<typeof setInterval> | null = null;
/** Enquanto o PDV está aberto: contingência transmitida e notas registradas, de minuto em minuto. */
export function startFiscalSync() {
  if (timer) return;
  const tick = async () => {
    if (!fiscalSettings.enabled) return;
    await fiscal.transmitPending().catch(() => undefined);
    await fiscal.syncPending().catch(() => undefined);
  };
  void fiscal.refreshKit().catch(() => undefined);
  void tick();
  timer = setInterval(() => void tick(), 60_000);
}
export function stopFiscalSync() {
  if (timer) clearInterval(timer);
  timer = null;
}
