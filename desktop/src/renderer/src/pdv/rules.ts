/**
 * As MESMAS regras do backend, conferidas no PC ANTES de fazer a operação local — o que vai
 * pela fila não volta recusado. Cada recusa usa o MESMO código de erro do backend, e o caderno
 * `shared/pdv-rules.cases.json` roda os mesmos casos nos dois lados (pytest e
 * `npm run test:rules` no desktop): mudou uma regra só de um lado, o teste quebra.
 *
 * Espelha:
 * - `services/cash.py`      open_session, add_movement, close_session
 * - `services/checkout.py`  _session_for, _check_method, complete
 * - `services/sales.py`     add_item (quantidade)
 *
 * Os dados (limites, tolerância, caixas, formas de pagamento) vêm SEMPRE do servidor (bootstrap
 * e catálogo guardados), nunca de valor fixo aqui. O que só o servidor sabe na hora (outro PC
 * abriu o mesmo caixa, o gerente fechou o turno pela web) ainda pode ser recusado: fica em
 * Pedidos/Config. → Offline. O que já ACONTECEU (cliente levou, dinheiro saiu) o servidor
 * aceita como fato (`offline_sales.py` / `offline_cash.py`).
 */
import type { PaymentInput } from "@/api/pdv";
import type { CashMovement, CashSession, PdvBootstrap, Sale } from "@/api/types";

import type { CashState } from "../../../shared/ipc";
import { OfflineRefused, SERVER_METHODS } from "./offline";

const brl = (v: number) => `R$ ${v.toFixed(2).replace(".", ",")}`;
const fail = (code: string, message: string): never => {
  throw new OfflineRefused(message, code);
};

/* ── gaveta pelo que o PC registrou ─────────────────────────────────────── */

type HistorySale = { cash_session?: string; completed_at?: string; payments: { method_kind?: string; amount: string }[] };

/** Troco (ou o último "esperado" lido do servidor) + vendas em dinheiro + suprimentos − sangrias. */
export function drawerOf(session: CashSession, state: CashState, history: Record<string, unknown>[]) {
  const since = (state.session as { id?: string; expected_at?: string } | null)?.id === session.id
    ? (state.session as { expected_at?: string }).expected_at : undefined;
  const after = (at?: string | null) => !since || (at ?? "") > since;
  const base = since ? Number(session.expected_now || session.opening_amount) : Number(session.opening_amount);
  const sales = (history as unknown as HistorySale[]).filter((s) => s.cash_session === session.id && after(s.completed_at));
  const cash = sales.reduce((sum, s) => sum + s.payments.filter((p) => p.method_kind === "cash").reduce((t, p) => t + Number(p.amount), 0), 0);
  const movements = (state.movements as unknown as (CashMovement & { session?: string })[]).filter((m) => m.session === session.id);
  const moved = movements.filter((m) => m.status === "approved" && after(m.created_at))
    .reduce((sum, m) => sum + (m.kind === "withdrawal" ? -1 : 1) * Number(m.amount), 0);
  const pending = movements.filter((m) => m.status === "pending").length;
  return { sales: sales.length, expected: Math.round((base + cash + moved) * 100) / 100, movements, pending };
}

/* ── caixa ──────────────────────────────────────────────────────────────── */

type Register = PdvBootstrap["cash_registers"][number] & { is_active?: boolean };

/** cash.open_session — mesma ordem: caixa ativo → vínculo → turno do operador → caixa livre → valor. */
export function checkOpen(registers: Register[], current: Pick<CashSession, "status"> | null, register: string, amount: string) {
  const found = registers.find((r) => r.id === register);
  if (found?.is_active === false) fail("register_inactive", "Caixa inativo.");
  if (!found) fail("permission_denied", "Você não está vinculado a este caixa. Peça ao gerente para vincular em Financeiro → Caixas.");
  const value = Number(amount);
  if (!Number.isFinite(value) || value < 0) fail("amount_invalid", "Informe o troco contado (zero ou mais).");
  if (current && current.status !== "closed") fail("operator_busy", "Você já está com um turno em andamento: feche-o antes de abrir outro.");
  if (found!.in_use_by) fail("register_busy", `${found!.name} já está com um turno aberto por ${found!.in_use_by}. Escolha outro caixa.`);
}

/** cash.add_movement — tipo → valor → turno aberto → sangria até o dinheiro em gaveta. */
export function checkMovement(session: Pick<CashSession, "status"> | null, kind: string, amount: string, drawer: number | null) {
  if (kind !== "withdrawal" && kind !== "supply") fail("movement_kind_invalid", "Tipo de movimento manual inválido.");
  const value = Number(amount);
  if (!(value > 0)) fail("amount_invalid", "Informe um valor maior que zero.");
  if (!session || session.status !== "open") fail("session_not_open", "O turno de caixa não está aberto.");
  if (kind === "withdrawal" && drawer !== null && value > drawer + 0.001) {
    fail("withdrawal_exceeds_drawer", `Sangria maior que o dinheiro em gaveta (${brl(drawer)}).`);
  }
}

/** cash.close_session — turno aberto → contado → sem sangria/suprimento esperando o gerente. */
export function checkClose(session: Pick<CashSession, "status" | "pending_movements"> | null, counted: string, localPending: number) {
  if (!session || session.status !== "open") fail("session_not_open", "O turno de caixa não está aberto.");
  const value = Number(counted);
  if (!Number.isFinite(value) || value < 0) fail("amount_invalid", "Informe o valor contado na gaveta (zero ou mais).");
  if (localPending + (session!.pending_movements ?? 0) > 0) {
    fail("movements_pending", "Há sangria ou suprimento aguardando aprovação neste turno: aprove ou recuse antes de fechar.");
  }
}

/* ── venda ──────────────────────────────────────────────────────────────── */

type SaleLike = Pick<Sale, "items" | "seller" | "customer" | "total">;
type BootLike = {
  rules: Pick<PdvBootstrap["rules"], "require_open_cash_session" | "require_seller" | "require_payment_reference">;
  payment_methods: PdvBootstrap["payment_methods"];
};
const cents = (v: number) => Math.round(v * 100) / 100;

/**
 * checkout.checkout — a MESMA sequência do backend:
 *   add_item: quantidade
 *   add_payment (cada um): valor > 0 → troco só em dinheiro (senão ≤ saldo) → _check_method
 *     (parcelas, cliente do vale/crediário) → NSU (regra da filial) → _session_for (caixa aberto)
 *   complete: itens → pago ≥ total → vendedor (regra da filial)
 * `needs_server` é só do PC: crediário/vale-troca sem servidor (limite e saldo moram lá).
 */
export function checkSale(sale: SaleLike, payments: PaymentInput[], boot: BootLike | null, session: Pick<CashSession, "status"> | null, online: boolean) {
  const rules = boot?.rules;
  if (sale.items.some((i) => i.status === "active" && !(Number(i.quantity) > 0))) fail("quantity_invalid", "Quantidade precisa ser maior que zero.");
  let balance = cents(Number(sale.total));
  for (const p of payments) {
    const method = boot?.payment_methods.find((m) => m.id === p.method);
    if (!method) fail("payment_method_unknown", "Forma de pagamento desconhecida (atualize o PDV com o servidor).");
    let amount = cents(Number(p.amount));
    if (!(amount > 0)) fail("amount_invalid", "Valor do pagamento precisa ser maior que zero.");
    if (method!.kind === "cash") amount = Math.min(cents(Number(p.tendered ?? p.amount)), balance);
    else if (amount > balance + 0.001) fail("payment_exceeds_balance", "Pagamento maior que o saldo da venda (troco só em dinheiro).");
    if ((p.installments ?? 1) > (method!.max_installments ?? 1)) {
      fail("installments_exceeded", `${method!.name} aceita no máximo ${method!.max_installments ?? 1} parcelas.`);
    }
    if (SERVER_METHODS.has(method!.kind)) {
      if (!sale.customer) fail("customer_required", `${method!.name} exige o cliente na venda.`);
      if (!online) fail("needs_server", `${method!.name} precisa do servidor (limite/saldo do cliente). Use outra forma.`);
    }
    if (method!.requires_reference && rules?.require_payment_reference && !p.nsu?.trim()) {
      fail("reference_required", `${method!.name}: informe o NSU/autorização do comprovante.`);
    }
    if (rules?.require_open_cash_session && session?.status !== "open") {
      fail("cash_session_required", "Abra o caixa antes de receber (o turno também pode estar esperando o gerente conferir a abertura).");
    }
    balance = cents(balance - amount);
  }
  if (!sale.items.some((i) => i.status === "active")) fail("sale_empty", "A venda não tem itens.");
  if (balance > 0.001) fail("payment_pending", `Falta receber ${brl(balance)}.`);
  if (rules?.require_seller && !sale.seller) fail("seller_required", "Informe o vendedor da venda.");
}
