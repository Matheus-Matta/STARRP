import type { Approval, CashMovement, CashSession } from "./types";
import { http } from "./http";

export const cashApi = {
  current: () => http.get<CashSession | null>("/cash/sessions/current/").then((r) => r.data),
  /** Abertura com conferência cega: `opening_amount` = o que o operador CONTOU na gaveta. */
  open: (register: string, opening_amount: string, terminal?: string, notes = "") =>
    http.post<CashSession>("/cash/sessions/", { register, opening_amount, terminal, notes }).then((r) => r.data),
  /** Abertura que não bateu: o gerente confere (direto, ou `approval` com a senha dele/do caixa). */
  approveOpening: (id: string, approval?: Approval, reason = "") =>
    http.post<CashSession>(`/cash/sessions/${id}/approve-opening/`, { approval, reason }).then((r) => r.data),
  close: (id: string, counted_amount: string, notes = "") =>
    http.post<CashSession>(`/cash/sessions/${id}/close/`, { counted_amount, notes }).then((r) => r.data),
  /** Sangria/suprimento. Sem `cash.approve` volta `pending` (ou já aprovado, se veio `approval`). */
  movement: (id: string, kind: "withdrawal" | "supply", amount: string, reason = "", approval?: Approval) =>
    http.post<CashMovement>(`/cash/sessions/${id}/movements/`, { kind, amount, reason, approval }).then((r) => r.data),
  movements: (id: string) => http.get<CashMovement[]>(`/cash/sessions/${id}/movements/`).then((r) => r.data),
  approveMovement: (id: string, reason = "", approval?: Approval) =>
    http.post<CashMovement>(`/cash/movements/${id}/approve/`, { reason, approval }).then((r) => r.data),
  /** Gerente recusa, ou o operador desiste do que lançou. */
  rejectMovement: (id: string, reason = "") =>
    http.post<CashMovement>(`/cash/movements/${id}/reject/`, { reason }).then((r) => r.data),
  /** Fechamento com diferença: justificativa obrigatória; `approval` = gerente ou senha do caixa. */
  approveClosing: (id: string, reason: string, approval?: Approval) =>
    http.post<CashSession>(`/cash/sessions/${id}/approve/`, { reason, approval }).then((r) => r.data),
};
