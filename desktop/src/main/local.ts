/**
 * Dados do PDV local-first, guardados NESTE PC (criptografados com o cofre do Windows):
 *
 * - a venda em andamento de cada operador (fechou o app, faltou luz: volta igual);
 * - os pedidos guardados no próprio caixa (F4/"guardar"), que não dependem do servidor;
 * - o histórico das vendas concluídas aqui (reimprimir e consultar mesmo sem servidor);
 * - as senhas que já autorizaram algo neste PC (gerente, senha de ações do caixa, o próprio
 *   operador no login): só o resumo `scrypt` com sal, nunca a senha. Com o servidor fora, o
 *   PDV aceita a MESMA pessoa com a MESMA senha e o mesmo limite que o servidor confirmou
 *   na última vez. Quem nunca autorizou neste PC só autoriza com o servidor no ar.
 */
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

import { getConfig } from "./config";
import { readJson, readSecret, writeJson, writeSecret } from "./files";

const scope = () => getConfig().storeId ?? "none";
const file = (name: string) => `${name}-${scope()}.bin`;

/* ── venda em andamento ──────────────────────────────────────────────────── */

type Sale = Record<string, unknown> & { id: string };

export function currentSale(userId: number): Sale | null {
  return readSecret<Record<string, Sale | null>>(file("current"), {})[String(userId)] ?? null;
}

export function saveCurrentSale(userId: number, sale: Sale | null) {
  const all = readSecret<Record<string, Sale | null>>(file("current"), {});
  if (sale) all[String(userId)] = sale;
  else delete all[String(userId)];
  writeSecret(file("current"), all);
}

/* ── pedidos guardados no caixa ──────────────────────────────────────────── */

export const parked = () => readSecret<Sale[]>(file("parked"), []);

export function park(sale: Sale) {
  writeSecret(file("parked"), [{ ...sale, parked_at: new Date().toISOString() }, ...parked().filter((s) => s.id !== sale.id)]);
}

export function unpark(id: string): Sale | null {
  const all = parked();
  const found = all.find((s) => s.id === id) ?? null;
  writeSecret(file("parked"), all.filter((s) => s.id !== id));
  return found;
}

/* ── histórico das vendas concluídas aqui ────────────────────────────────── */

const HISTORY_MAX = 500;
export const history = () => readSecret<Sale[]>(file("history"), []);

export function remember(sale: Sale) {
  writeSecret(file("history"), [sale, ...history().filter((s) => s.id !== sale.id)].slice(0, HISTORY_MAX));
}

/** A venda local virou venda do servidor: o histórico guarda o número de verdade. */
export function linkServer(localId: string, server: Record<string, unknown>) {
  writeSecret(file("history"), history().map((s) => (s.id === localId
    ? { ...s, server_id: server.id, server_number: server.number } : s)));
}

/** Os dois lados de uma venda feita aqui que já está no servidor (pelo id local ou pelo do servidor). */
export function linkOf(ref: string): { localId: string; serverId: string } | null {
  const found = history().find((s) => s.server_id && (s.id === ref || s.server_id === ref));
  return found ? { localId: found.id, serverId: String(found.server_id) } : null;
}

/* ── senhas aprendidas (autorização offline) ─────────────────────────────── */

type Verifier = { salt: string; hash: string; learnedAt?: string; n?: number };

/** Custo do scrypt das senhas aprendidas (2^15): quebrar offline uma cópia do arquivo fica bem mais caro.
 *  Resumo antigo, sem `n`, foi feito com o padrão do Node (2^14) e continua valendo. */
const SCRYPT_N = 1 << 15;
const SCRYPT_OPTS = (n: number) => ({ N: n, r: 8, p: 1, maxmem: 128 * n * 8 * 2 });

/* Tentativas offline (sem o servidor, que tem o limite dele): 5 erros em 5 minutos por alvo trava. */
const OFFLINE_WINDOW = 5 * 60_000;
const OFFLINE_MAX = 5;
// No disco (rodada 1, P-19): fechar e abrir o PDV não zera as tentativas.
const ATTEMPTS = "offline-attempts.json";
function recentFailures(target: string) {
  const now = Date.now();
  const all = readJson<Record<string, number[]>>(ATTEMPTS, {});
  return (all[target] ?? []).filter((t) => now - t < OFFLINE_WINDOW);
}
function tooMany(target: string) {
  return recentFailures(target).length >= OFFLINE_MAX;
}
function failed(target: string) {
  const now = Date.now();
  const all = readJson<Record<string, number[]>>(ATTEMPTS, {});
  for (const key of Object.keys(all)) all[key] = all[key]!.filter((t) => now - t < OFFLINE_WINDOW);
  all[target] = [...recentFailures(target), now];
  writeJson(ATTEMPTS, Object.fromEntries(Object.entries(all).filter(([, v]) => v.length)));
}
const LOCKED = "Muitas tentativas de senha sem o servidor. Aguarde alguns minutos.";

/** Senha aprendida vale offline por 30 dias desde a última confirmação no servidor: gerente desligado ou
 *  cargo trocado deixa de autorizar neste PC (cada autorização com o servidor no ar renova o prazo). */
export const LEARNED_VALID_DAYS = 30;
const expired = (learnedAt?: string) =>
  learnedAt !== undefined && Date.now() - Date.parse(learnedAt) > LEARNED_VALID_DAYS * 86_400_000;
type Approver = Verifier & {
  id: number | null; username: string; name: string; codes: string[]; maxDiscount: string; learnedAt: string;
};
type Vault = { approvers: Record<string, Approver>; cash?: Verifier; operators: Record<string, Verifier> };

const VAULT = "approvers.bin";
const vault = () => readSecret<Vault>(VAULT, { approvers: {}, operators: {} });
const key = (username: string) => username.trim().toLowerCase();

function digest(password: string, salt = randomBytes(16).toString("hex")): Verifier {
  return { salt, hash: scryptSync(password, salt, 32, SCRYPT_OPTS(SCRYPT_N)).toString("hex"),
           learnedAt: new Date().toISOString(), n: SCRYPT_N };
}
function matches(password: string, verifier?: Verifier) {
  if (!verifier || !password) return false;
  const expected = Buffer.from(verifier.hash, "hex");
  const n = verifier.n ?? 1 << 14;
  const actual = scryptSync(password, verifier.salt, 32, SCRYPT_OPTS(n));
  return expected.length === actual.length && timingSafeEqual(actual, expected); // arquivo antigo/corrompido: não confere
}
const STALE = `Faz mais de ${LEARNED_VALID_DAYS} dias que esta senha não é conferida com o servidor no ar: sem ele, não dá para aceitá-la.`;

export type ApprovalInput = { username?: string; password?: string; cash_password?: string };
export type ApproverInfo = {
  approver: { id: number; username: string; name: string } | null;
  by: "self" | "approver" | "cash_password";
  codes: string[];
  max_discount_percent: string;
};

/** O servidor confirmou esta autorização: guarda o resumo da senha para usar offline. */
export function learnApproval(approval: ApprovalInput | undefined, info: ApproverInfo) {
  if (!approval) return;
  const data = vault();
  if (approval.cash_password && info.by === "cash_password") data.cash = digest(approval.cash_password);
  if (approval.username && approval.password && info.approver) {
    data.approvers[key(approval.username)] = {
      ...digest(approval.password), id: info.approver.id, username: info.approver.username, name: info.approver.name,
      codes: info.codes, maxDiscount: info.max_discount_percent, learnedAt: new Date().toISOString(),
    };
  }
  writeSecret(VAULT, data);
}

export class OfflineApprovalError extends Error {
  constructor(message: string, public code: string) {
    super(message);
  }
}

/** Servidor fora: confere a autorização pelas senhas aprendidas (mesma regra do servidor). */
export function verifyApproval(approval: ApprovalInput | undefined, code: string, percent?: number): ApproverInfo {
  const data = vault();
  const target = approval?.cash_password ? "cash" : `user:${key(approval?.username ?? "")}`;
  if ((approval?.cash_password || approval?.password) && tooMany(target)) {
    throw new OfflineApprovalError(LOCKED, "approval_invalid");
  }
  try {
    return checkApproval(data, approval, code, percent);
  } catch (error) {
    if (error instanceof OfflineApprovalError && error.message !== LOCKED) failed(target);
    throw error;
  }
}

function checkApproval(data: Vault, approval: ApprovalInput | undefined, code: string, percent?: number): ApproverInfo {
  if (approval?.cash_password) {
    if (!data.cash) throw new OfflineApprovalError("A senha de ações do caixa ainda não foi usada neste PC com o servidor no ar: sem ele, não dá para conferi-la.", "approval_invalid");
    if (expired(data.cash.learnedAt)) throw new OfflineApprovalError(STALE, "approval_invalid");
    if (!matches(approval.cash_password, data.cash)) throw new OfflineApprovalError("Senha de ações do caixa inválida.", "approval_invalid");
    return { approver: null, by: "cash_password", codes: [code], max_discount_percent: "0" };
  }
  if (approval?.username && approval.password) {
    const found = data.approvers[key(approval.username)];
    if (!found) throw new OfflineApprovalError(`${approval.username} nunca autorizou neste PC com o servidor no ar: sem ele, a senha não pode ser conferida.`, "approval_invalid");
    if (expired(found.learnedAt)) throw new OfflineApprovalError(STALE, "approval_invalid");
    if (!matches(approval.password, found)) throw new OfflineApprovalError("Usuário ou senha de autorização inválidos.", "approval_invalid");
    if (!found.codes.includes(code)) throw new OfflineApprovalError("O autorizador não tem permissão para esta ação.", "approval_invalid");
    if (code === "sales.discount" && percent !== undefined && percent > Number(found.maxDiscount) + 1e-9) {
      throw new OfflineApprovalError(`Desconto acima do limite de ${found.name} (${found.maxDiscount}%).`, "approval_invalid");
    }
    return {
      approver: { id: found.id ?? 0, username: found.username, name: found.name }, by: "approver", codes: found.codes,
      max_discount_percent: found.maxDiscount,
    };
  }
  throw new OfflineApprovalError("Peça a autorização do gerente.", code === "sales.discount" ? "discount_approval_required" : "approval_required");
}

/** Login com sucesso: guarda o resumo da senha do operador (desbloquear a tela offline). */
export function learnOperator(username: string, password: string) {
  const data = vault();
  data.operators[key(username)] = digest(password);
  writeSecret(VAULT, data);
}

/** Desbloqueio offline: a senha do próprio operador ou a de ações do caixa aprendida. */
export function verifyUnlock(username: string, password: string) {
  const target = `unlock:${key(username)}`;
  if (tooMany(target)) return false;
  const data = vault();
  const ok = matches(password, data.operators[key(username)]) || matches(password, data.cash);
  if (!ok) failed(target);
  return ok;
}

/* ── turno de caixa deste PC (o terminal manda no turno, como no mercado) ── */

/** O turno atual, os movimentos dele e os últimos fechados (reimprimir sem servidor). */
export type CashState = {
  session: Record<string, unknown> | null;
  movements: Record<string, unknown>[];
  closed: Record<string, unknown>[];
  /** Turnos fechados aqui cujo fechamento ainda está na fila (o bootstrap pode trazê-los abertos). */
  closing: string[];
};

export const cashState = () => readSecret<CashState>(file("cash"), { session: null, movements: [], closed: [], closing: [] });
export const saveCashState = (state: CashState) =>
  writeSecret(file("cash"), { ...state, closed: state.closed.slice(0, 30), closing: state.closing.slice(-30) });
