/**
 * NFC-e / NF-e do PDV desktop pelo Comunicador Fiscal DESKTOP (app-fiscal-acbr, modo `local`)
 * instalado neste PC: JSON comum com o token, o emitente (A1, CSC) guardado nele, e
 * contingência offline aqui mesmo quando a internet cai.
 *
 * A lógica inteira (montar a nota, numerar, emitir, contingência, transmitir, registrar) é o
 * núcleo COMPARTILHADO com o PDV web (`shared/fiscal/engine.ts`): os dois emitem igual. Aqui
 * fica só onde o desktop guarda, cifrado com o cofre do Windows:
 *
 * - `fiscal-secrets.bin`: o token do comunicador (tela Acesso dele → configurações daqui);
 * - `fiscal-kit.bin`: o kit do servidor (emitente, perfis, fiscal das variações, série do terminal);
 * - `fiscal-numbers.json`: a numeração deste terminal;
 * - `fiscal-invoices.bin`: as notas emitidas aqui (com o XML), até o servidor saber.
 *
 * Certificado A1 e CSC NÃO ficam aqui: estão guardados no comunicador (tela Emitente dele, ou
 * Configurações → Nota fiscal → "Gravar certificado no comunicador", por quem administra o fiscal).
 */
import { createFiscal } from "../../../shared/fiscal/engine";
import { localTransport } from "../../../shared/fiscal/transport";
import type { EmitRequest, EmitResult, Kit, LocalInvoice, Numbers } from "../../../shared/fiscal/types";
import { BrowserWindow, dialog } from "electron";

import type { FiscalSecrets } from "../shared/ipc";
import { acbrUrlProblem } from "../shared/serverUrl";
import { request as api } from "./api";
import { getConfig, installationId } from "./config";
import { readJson, readSecret, writeJson, writeSecret } from "./files";

type Secrets = { token?: string };
const secrets = () => readSecret<Secrets>("fiscal-secrets.bin", {});
export const secretStatus = (): FiscalSecrets => ({ token: Boolean(secrets().token) });
export function setSecrets(values: Secrets): FiscalSecrets {
  // Só o token: no modo local o comunicador não usa cifra (a chave antiga, se houver, sai).
  const next: Secrets = { token: secrets().token };
  if (values.token !== undefined) next.token = values.token.trim() || undefined;
  writeSecret("fiscal-secrets.bin", next);
  return secretStatus();
}

let kitCache: Kit | null | undefined;

const engine = createFiscal({
  storage: {
    kit: () => (kitCache === undefined ? (kitCache = readSecret<Kit | null>("fiscal-kit.bin", null)) : kitCache),
    saveKit: (kit) => {
      kitCache = kit;
      writeSecret("fiscal-kit.bin", kit);
    },
    numbers: () => readJson<Numbers>("fiscal-numbers.json", { series: {}, next: {}, bySale: {} }),
    saveNumbers: (numbers) => writeJson("fiscal-numbers.json", numbers),
    invoices: () => readSecret<LocalInvoice[]>("fiscal-invoices.bin", []),
    saveInvoices: (invoices) => writeSecret("fiscal-invoices.bin", invoices),
  },
  server: {
    get: (path, params) => api({ method: "GET", path, params }),
    post: (path, data) => api({ method: "POST", path, data }),
  },
  transport: localTransport(() => ({ url: getConfig().fiscal.acbrUrl, token: secrets().token })),
  storeId: () => getConfig().storeId,
  installationId: () => installationId(getConfig().storeId ?? ""),
});

export const getKitInfo = engine.kitInfo;
export const refreshKit = engine.refreshKit;
export const health = engine.health;
/** Gravar o certificado A1 + CSC no comunicador: confirma com quem está no PC, mostrando PARA ONDE vai (S-14),
 *  e só para um comunicador deste computador. */
export async function storeEmitter(): Promise<{ ok: boolean; message: string }> {
  const url = getConfig().fiscal.acbrUrl;
  const problem = acbrUrlProblem(url);
  if (problem) return { ok: false, message: problem };
  const parent = BrowserWindow.getFocusedWindow();
  const options = {
    type: "warning" as const, buttons: ["Enviar o certificado", "Cancelar"], defaultId: 1, cancelId: 1,
    title: "Gravar certificado no comunicador",
    message: "Enviar o certificado A1 e o CSC da filial para o comunicador fiscal?",
    detail: `Destino: ${url}
Só confirme se este é o Comunicador Fiscal instalado neste computador.`,
  };
  const answer = parent ? await dialog.showMessageBox(parent, options) : await dialog.showMessageBox(options);
  if (answer.response !== 0) return { ok: false, message: "Envio do certificado cancelado." };
  return engine.storeEmitter();
}
export const localInvoices = engine.localInvoices;
export const invoicesFor = engine.invoicesFor;
export const registerInvoice = engine.registerInvoice;
export const transmitPending = engine.transmitPending;
export const linkInvoices = engine.linkInvoices;

export function emit(req: EmitRequest): Promise<EmitResult> {
  const config = getConfig().fiscal;
  if (!config.enabled) return Promise.resolve({ ok: false, error: "A emissão de nota está desligada nas configurações deste PDV." });
  return engine.emit(req, { contingency: config.contingency });
}
