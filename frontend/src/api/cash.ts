import type { CashMovement, CashSession } from "./types";
import { http } from "./http";

export const cashApi = {
  current: () => http.get<CashSession | null>("/cash/sessions/current/").then((r) => r.data),
  open: (register: string, opening_amount: string, terminal?: string) =>
    http.post<CashSession>("/cash/sessions/", { register, opening_amount, terminal }).then((r) => r.data),
  close: (id: string, counted_amount: string, notes = "") =>
    http.post<CashSession>(`/cash/sessions/${id}/close/`, { counted_amount, notes }).then((r) => r.data),
  movement: (id: string, kind: "withdrawal" | "supply", amount: string, reason = "") =>
    http.post<CashMovement[]>(`/cash/sessions/${id}/movements/`, { kind, amount, reason }).then((r) => r.data),
};
