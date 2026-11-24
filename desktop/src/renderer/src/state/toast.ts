/** Avisos padronizados: o erro da API vira mensagem legível, sempre igual. */
import { toApiError } from "@/api/errors";

import { createStore } from "./store";

export type Toast = { id: number; severity: "success" | "warn" | "error"; summary: string; detail?: string };

export const toasts = createStore<Toast[]>([]);
let seq = 0;

function push(severity: Toast["severity"], summary: string, detail: string | undefined, life: number) {
  const id = ++seq;
  toasts.set((list) => [...list.slice(-4), { id, severity, summary, detail }]);
  setTimeout(() => dismiss(id), life);
}

export const dismiss = (id: number) => toasts.set((list) => list.filter((t) => t.id !== id));

export const notify = {
  success: (summary: string, detail?: string) => push("success", summary, detail, 3500),
  warn: (summary: string, detail?: string) => push("warn", summary, detail, 6000),
  error: (error: unknown, summary = "Não foi possível concluir") => {
    const apiError = toApiError(error);
    push("error", summary, apiError.message, 7000);
    return apiError;
  },
};
