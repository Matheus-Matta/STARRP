/**
 * Modo offline: o PDV continua vendendo quando o servidor não responde (internet fora ou
 * backend com erro), e acerta tudo quando ele volta.
 *
 * - de 15 em 15 s verifica o servidor (`/health/`) e avisa a tela (`net:status`);
 * - com o servidor no ar: baixa o catálogo inteiro (`/pdv/catalog-snapshot/`, a cada 15 min)
 *   e o kit fiscal (a cada 30 min), e esvazia a fila;
 * - a fila (`outbox.json`) guarda, em ordem, as vendas feitas offline (com a nota emitida
 *   nelas) — cada uma com um `offline_id` fixo: reenviar nunca duplica no servidor;
 * - notas em contingência são transmitidas à SEFAZ assim que o comunicador consegue;
 * - o que o servidor RECUSA (regra de negócio) fica marcado como falha, com o motivo, para o
 *   operador ver na tela de pedidos e tentar de novo ou descartar. Nada some sozinho.
 */
import { randomUUID } from "node:crypto";

import type { BrowserWindow } from "electron";

import type { AuthorizeRequest, AuthorizeResult, NetStatus, OfflineCache, OutboxEntry, Snapshot } from "../shared/ipc";
import { hasSession, request as api } from "./api";
import { getConfig } from "./config";
import * as fiscal from "./fiscal";
import * as local from "./local";
import { readJson, readSecret, writeJson, writeSecret } from "./files";

const CHECK_MS = 15_000;
const SNAPSHOT_MS = 15 * 60_000;
const KIT_MS = 30 * 60_000;

let win: BrowserWindow | null = null;
let online = true;
let syncing = false;
let lastSync: string | null = null;
let lastKit = 0;

const outbox = () => readJson<OutboxEntry[]>("outbox.json", []);
const saveOutbox = (rows: OutboxEntry[]) => writeJson("outbox.json", rows);
/** Grava SÓ esta linha, relendo a fila do disco: enquanto um envio espera a rede, o operador pode
 *  concluir outra venda (que entra na fila); gravar a lista lida antes apagaria essa venda. */
function saveEntry(entry: OutboxEntry) {
  saveOutbox(outbox().map((row) => (row.id === entry.id ? entry : row)));
}
const snapshotFile = () => `snapshot-${getConfig().storeId ?? "none"}.json`;

export function status(): NetStatus {
  const rows = outbox();
  const invoices = fiscal.localInvoices().filter((i) => !i.synced && i.saleId);
  return {
    online, syncing, lastSync,
    pending: rows.filter((r) => r.status === "pending").length + invoices.length,
    failed: rows.filter((r) => r.status === "failed").length,
    snapshotAt: readJson<Snapshot | null>(snapshotFile(), null)?.generated_at ?? null,
  };
}

const notify = () => win?.webContents.send("net:status", status());

export const getSnapshot = () => readJson<Snapshot | null>(snapshotFile(), null);
export const getCache = () => readSecret<OfflineCache>(`cache-${getConfig().storeId ?? "none"}.bin`, {});
export const saveCache = (cache: OfflineCache) =>
  writeSecret(`cache-${getConfig().storeId ?? "none"}.bin`, { ...cache, savedAt: new Date().toISOString() });
export const listOutbox = () => outbox().filter((r) => r.status !== "done");

export function nextLocalNumber() {
  const state = readJson<{ next: number }>("offline-seq.json", { next: 1 });
  writeJson("offline-seq.json", { next: state.next + 1 });
  return state.next;
}

/** Segura o envio enquanto a nota é emitida (a venda vai com a nota, PRONTA). Se o app cair
 *  nesse meio, depois de 2 minutos ela vai sozinha (a nota segue depois). */
const HOLD_MS = 2 * 60_000;

/** Comprovantes que o servidor deu em `/pdv/authorize/` (S-06): vão junto com a venda para o servidor
 *  conferir que o gerente autorizou de verdade. Ficam 3 dias (o mesmo prazo do servidor). */
const PROOF_DAYS = 3;
type Proof = { proof: string; at: number };

function rememberProof(proof: unknown) {
  if (typeof proof !== "string" || !proof) return;
  const now = Date.now();
  const kept = readSecret<Proof[]>("approval-proofs.bin", []).filter((p) => now - p.at < PROOF_DAYS * 86_400_000);
  writeSecret("approval-proofs.bin", [...kept, { proof, at: now }].slice(-200));
}

const proofs = () => {
  const now = Date.now();
  return readSecret<Proof[]>("approval-proofs.bin", []).filter((p) => now - p.at < PROOF_DAYS * 86_400_000)
    .map((p) => p.proof);
};

export function enqueueSale(payload: Record<string, unknown>, label: string, hold = false): OutboxEntry {
  return enqueue("sale", { ...payload, approval_proofs: proofs() }, label, hold);
}

/** Abertura, sangria/suprimento e fechamento feitos neste PC: vão na MESMA fila das vendas,
 *  em ordem (abertura → vendas → fechamento). */
export function enqueueCash(payload: Record<string, unknown>, label: string): OutboxEntry {
  // Sangria/abertura/fechamento aprovados no PC: o servidor só aceita com o comprovante (uso único).
  return enqueue("cash", { ...payload, approval_proofs: proofs() }, label, false);
}

function enqueue(kind: OutboxEntry["kind"], payload: Record<string, unknown>, label: string, hold: boolean): OutboxEntry {
  const entry: OutboxEntry = {
    id: `${kind === "cash" ? "cash:" : ""}${String(payload.offline_id ?? randomUUID())}`, kind, label, createdAt: new Date().toISOString(),
    attempts: 0, status: "pending", lastError: "", payload,
    ...(hold ? { heldUntil: new Date(Date.now() + HOLD_MS).toISOString() } : {}),
  };
  saveOutbox([...outbox().filter((r) => r.id !== entry.id), entry]);
  notify();
  if (!hold) void tick();
  return entry;
}

const held = (row: OutboxEntry) => Boolean(row.heldUntil && Date.parse(row.heldUntil) > Date.now());

export type FlushResult = { status: "done" | "queued" | "failed"; sale?: Record<string, unknown>; error?: string };

/** Solta a venda e já envia (servidor no ar): a tela recebe a venda do servidor (número real).
 *  Sem servidor ela fica na fila e vai no próximo ciclo. */
export async function flush(id: string): Promise<FlushResult> {
  const entry = outbox().find((r) => r.id === id);
  if (!entry) return { status: "failed", error: "Venda fora da fila." };
  saveEntry({ ...entry, heldUntil: undefined });
  // A fila anda em ordem: o que está antes vai primeiro (o tick já faz isso).
  if (!online || !hasSession()) {
    notify();
    return { status: "queued" };
  }
  await tick();
  const row = outbox().find((r) => r.id === id);
  if (!row || row.status === "done") return { status: "done", sale: row?.serverSale };
  if (row.status === "failed") return { status: "failed", error: row.lastError };
  return { status: "queued", error: row.lastError || undefined };
}

/** Só o que o servidor RECUSOU pode ser descartado: descartar venda ainda não enviada sumiria com o dinheiro dela. */
export function discard(id: string) {
  saveOutbox(outbox().filter((r) => r.id !== id || r.status !== "failed"));
  notify();
}

export function retry(id?: string) {
  saveOutbox(outbox().map((r) => (!id || r.id === id) && r.status === "failed" ? { ...r, status: "pending", lastError: "" } : r));
  void tick();
  return status();
}

async function ping() {
  try {
    const response = await fetch(`${getConfig().serverUrl}/health/`, { signal: AbortSignal.timeout(5000) });
    return response.ok;
  } catch {
    return false;
  }
}

export async function refreshSnapshot() {
  if (!getConfig().storeId || !hasSession()) return status();
  const response = await api({ method: "GET", path: "/pdv/catalog-snapshot/" });
  if (response.ok) writeJson(snapshotFile(), response.data);
  notify();
  return status();
}

/** Rede caiu no meio do envio (ou o servidor deu erro interno): tenta de novo depois. */
const transient = (code: number) => code === 0 || code >= 500 || code === 401 || code === 408 || code === 429;
const errorText = (data: unknown) => {
  const d = data as { error?: { message?: string }; detail?: string } | null;
  return d?.error?.message ?? d?.detail ?? JSON.stringify(data).slice(0, 300);
};

async function sendCash(entry: OutboxEntry): Promise<OutboxEntry> {
  const response = await api({ method: "POST", path: "/pdv/offline-cash/", data: entry.payload });
  if (response.ok) return { ...entry, status: "done", serverId: String((response.data as { id: string }).id), attempts: entry.attempts + 1, lastError: "" };
  return failedOrRetry(entry, response.status, response.data);
}

/** Erro de rede/servidor: tenta depois. "Turno ainda não chegou": espera a vez (fila em ordem).
 *  Regra de negócio: marca recusado com o motivo. */
function failedOrRetry(entry: OutboxEntry, code: number, data: unknown): OutboxEntry {
  const errCode = (data as { error?: { code?: string } } | null)?.error?.code;
  if (transient(code) || errCode === "offline_session_missing") {
    if (code === 0 || code >= 500) online = false;
    return { ...entry, attempts: entry.attempts + 1, lastError: errorText(data) };
  }
  return { ...entry, status: "failed", attempts: entry.attempts + 1, lastError: errorText(data) };
}

const send = (entry: OutboxEntry) => (entry.kind === "cash" ? sendCash(entry) : sendSale(entry));

async function sendSale(entry: OutboxEntry): Promise<OutboxEntry> {
  const saleRef = `off:${entry.id}`;
  const invoice = fiscal.invoicesFor(saleRef).find((i) => i.status === "authorized" || i.status === "contingency");
  const body = { ...entry.payload, ...(invoice ? { invoice: invoice.register } : {}) };
  const response = await api({ method: "POST", path: "/pdv/offline-sales/", data: body });
  if (response.ok) {
    const server = response.data as Record<string, unknown> & { id: string };
    const serverId = String(server.id);
    if (invoice) fiscal.linkInvoices(saleRef, serverId);
    local.linkServer(saleRef, server);
    return { ...entry, status: "done", serverId, serverSale: server, attempts: entry.attempts + 1, lastError: "" };
  }
  return failedOrRetry(entry, response.status, response.data);
}

let running: Promise<NetStatus> | null = null;

/** Um ciclo por vez; quem chama durante um ciclo espera ele terminar. */
export function tick(): Promise<NetStatus> {
  running ??= cycle().finally(() => {
    running = null;
  });
  return running;
}

async function cycle(): Promise<NetStatus> {
  if (syncing) return status();
  syncing = true;
  try {
    const wasOnline = online;
    online = await ping();
    notify();
    if (!online || !hasSession() || !getConfig().storeId) return status();

    // Fila: em ordem; para no primeiro erro de rede (o resto espera o próximo ciclo). Cada volta relê
    // a fila (pode ter entrado venda nova, ou o operador descartado uma) e grava só a linha enviada.
    const sent = new Set<string>();
    for (;;) {
      const row = outbox().find((r) => r.status === "pending" && (r.kind === "sale" || r.kind === "cash") && !sent.has(r.id));
      if (!row || held(row)) break; // a nota desta venda ainda está saindo: ela (e as de depois) esperam
      sent.add(row.id);
      const result = await send(row);
      if (!outbox().some((r) => r.id === row.id)) continue; // descartada durante o envio
      saveEntry(result);
      notify();
      if (result.status === "pending") break;
    }
    // Feitas há mais de 1 dia saem da fila (o servidor já tem).
    saveOutbox(outbox().filter((r) => r.status !== "done" || Date.now() - Date.parse(r.createdAt) < 86_400_000));

    for (const invoice of fiscal.localInvoices().filter((i) => !i.synced && i.saleId)) await fiscal.registerInvoice(invoice);
    if (getConfig().fiscal.enabled) await fiscal.transmitPending();

    const snap = getSnapshot();
    if (!wasOnline || !snap || Date.now() - Date.parse(snap.generated_at) > SNAPSHOT_MS) await refreshSnapshot();
    if (getConfig().fiscal.enabled && (!wasOnline || Date.now() - lastKit > KIT_MS)) {
      lastKit = Date.now();
      await fiscal.refreshKit();
    }
    lastSync = new Date().toISOString();
    return status();
  } finally {
    syncing = false;
    notify();
  }
}

export function start(window: BrowserWindow) {
  win = window;
  setTimeout(() => void tick(), 3000);
  setInterval(() => void tick(), CHECK_MS);
}

/** Uma chamada da tela falhou por rede/servidor: já marca offline (sem esperar o próximo ciclo). */
export function reportFailure(code: number) {
  if ((code === 0 || code >= 500) && online) {
    online = false;
    notify();
  }
}

/**
 * Autorização da venda montada no PC: com o servidor no ar, confere lá (`/pdv/authorize/`) e
 * aprende a senha que passou; fora do ar, confere pelas senhas aprendidas (`local.ts`).
 */
export async function authorize(body: AuthorizeRequest): Promise<AuthorizeResult> {
  if (online && hasSession()) {
    const response = await api({ method: "POST", path: "/pdv/authorize/", data: body });
    if (response.ok) {
      const info = response.data as local.ApproverInfo & { proof?: string };
      local.learnApproval(body.approval, info);
      rememberProof(info.proof);
      return { ok: true, offline: false, approver: info.approver, by: info.by };
    }
    if (!transient(response.status)) {
      const error = (response.data as { error?: { code?: string; message?: string } } | null)?.error;
      return { ok: false, status: response.status, code: error?.code ?? "error", message: error?.message ?? errorText(response.data) };
    }
    reportFailure(response.status);
  }
  try {
    const info = local.verifyApproval(body.approval, body.code, body.percent);
    return { ok: true, offline: true, approver: info.approver, by: info.by };
  } catch (error) {
    const e = error as local.OfflineApprovalError;
    return { ok: false, status: 403, code: e.code ?? "approval_invalid", message: e.message };
  }
}

/** Desbloqueio da tela: online confere no servidor; offline, pela senha aprendida. */
export async function unlock(username: string, password: string): Promise<boolean> {
  if (online && hasSession()) {
    const response = await api({ method: "POST", path: "/pdv/unlock/", data: { password } });
    if (response.ok) return true;
    if (!transient(response.status)) return false;
    reportFailure(response.status);
  }
  return local.verifyUnlock(username, password);
}
