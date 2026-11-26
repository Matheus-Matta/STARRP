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
 * Por FILIAL (o PDV troca de filial: número e nota de uma nunca entram na outra):
 * - `fiscal-kit-<filial>.bin`: o kit do servidor (emitente, perfis, fiscal das variações, série do terminal);
 * - `fiscal-numbers-<filial>.json`: a numeração deste terminal;
 * - `fiscal-invoices-<filial>.bin`: as notas emitidas aqui (com o XML), até o servidor saber.
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
import { hasFile, readJson, readSecret, writeJson, writeSecret } from "./files";
import * as local from "./local";

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

const kits = new Map<string, Kit | null>();
const scope = () => getConfig().storeId ?? "none";
/** Os arquivos eram um só para o PC: valem para a filial do kit guardado neles. */
function scoped<T>(name: string, ext: "bin" | "json", fallback: T): T {
  const read = ext === "bin" ? readSecret : readJson;
  const file = `fiscal-${name}-${scope()}.${ext}`;
  if (hasFile(file) || !hasFile(`fiscal-${name}.${ext}`)) return read(file, fallback);
  return readSecret<Kit | null>("fiscal-kit.bin", null)?.storeId === scope() ? read(`fiscal-${name}.${ext}`, fallback) : fallback;
}

/** Notas do arquivo antigo (um só para o PC): cada uma é da filial do emitente dela. */
function invoicesHere(): LocalInvoice[] {
  const file = `fiscal-invoices-${scope()}.bin`;
  if (hasFile(file) || !hasFile("fiscal-invoices.bin")) return readSecret<LocalInvoice[]>(file, []);
  const cnpj = kitHere()?.issuer.cnpj;
  if (!cnpj) return []; // sem o kit ainda não se sabe de quem são
  return readSecret<LocalInvoice[]>("fiscal-invoices.bin", []).filter((i) => {
    const issuer = (i.register.issuer as { cnpj?: string } | undefined)?.cnpj;
    return !issuer || issuer.replace(/\D/g, "") === cnpj.replace(/\D/g, "");
  });
}

function kitHere(): Kit | null {
  if (!kits.has(scope())) kits.set(scope(), scoped<Kit | null>("kit", "bin", null));
  return kits.get(scope()) ?? null;
}

const engine = createFiscal({
  storage: {
    kit: kitHere,
    saveKit: (kit) => {
      kits.set(kit.storeId, kit);
      writeSecret(`fiscal-kit-${kit.storeId}.bin`, kit);
    },
    numbers: () => scoped<Numbers>("numbers", "json", { series: {}, next: {}, bySale: {} }),
    saveNumbers: (numbers) => writeJson(`fiscal-numbers-${scope()}.json`, numbers),
    invoices: invoicesHere,
    saveInvoices: (invoices) => writeSecret(`fiscal-invoices-${scope()}.bin`, invoices),
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

/** Uma emissão por vez neste PC, e o caixa não troca de filial no meio dela (`busy`). */
let emitting: Promise<unknown> = Promise.resolve();
let running = 0;
export const busy = () => running > 0;

export async function emit(req: EmitRequest): Promise<EmitResult> {
  const config = getConfig().fiscal;
  if (!config.enabled) return { ok: false, error: "A emissão de nota está desligada nas configurações deste PDV." };
  running += 1;
  const turn = emitting.then(async () => {
    // Pedido do servidor que nasceu aqui: é a MESMA venda (mesmo número reservado), não outra nota.
    const link = local.linkOf(req.saleRef);
    const result = await engine.emit({ ...req, saleRef: link?.localId ?? req.saleRef, saleId: link?.serverId }, { contingency: config.contingency });
    // A venda foi ao servidor enquanto a nota saía (demorou mais que a espera): liga e registra agora.
    const server = local.linkOf(req.saleRef)?.serverId;
    if (result.invoice && server && !result.invoice.saleId) {
      const linked = { ...result.invoice, saleId: server, synced: false };
      engine.saveInvoice(linked);
      void engine.registerInvoice(linked);
      return { ...result, invoice: linked };
    }
    return result;
  }).finally(() => {
    running -= 1;
  });
  emitting = turn.catch(() => undefined);
  return turn;
}
