/**
 * Autorização de um superior no meio da operação.
 *
 *   await withApproval((approval) => salesApi.discount(id, { percent: "10", approval }))
 *
 * Tenta sem autorização; se o backend responder `*approval_required`, abre o diálogo, pede
 * usuário/senha do gerente (ou a senha do caixa) e repete a MESMA chamada com `approval`.
 * Cancelar o diálogo cancela a operação (`ApprovalCancelled`).
 * Com `{ reason }` o diálogo abre já de saída e pede também a justificativa.
 */
import { ApiError, toApiError } from "@/api/errors";
import type { Approval } from "@/api/types";

import { createStore } from "./store";

export type ApprovalAnswer = { approval: Approval; reason: string };
type Pending = { message: string; reasonLabel?: string; resolve: (value: ApprovalAnswer | null) => void };

export const approvalPending = createStore<Pending | null>(null);

export function answerApproval(value: ApprovalAnswer | null) {
  approvalPending.get()?.resolve(value);
  approvalPending.set(null);
}

const ask = (message: string, reasonLabel?: string) =>
  new Promise<ApprovalAnswer | null>((resolve) => approvalPending.set({ message, reasonLabel, resolve }));

export class ApprovalCancelled extends Error {}

export async function withApproval<T>(
  action: (approval?: Approval, reason?: string) => Promise<T>,
  options: { reason?: string; message?: string } = {},
): Promise<T> {
  let apiError: ApiError | null = null;
  if (!options.reason) {
    try {
      return await action();
    } catch (error) {
      apiError = toApiError(error);
      if (!apiError.needsApproval && apiError.code !== "approval_invalid") throw apiError;
    }
  }
  // Senha errada também volta como pedido de autorização: perguntamos de novo.
  for (;;) {
    const answer = await ask(apiError?.message ?? options.message ?? "Peça a autorização do gerente.", options.reason);
    if (!answer) throw new ApprovalCancelled("Operação cancelada.");
    try {
      return await action(answer.approval, answer.reason);
    } catch (retry) {
      apiError = toApiError(retry);
      if (!apiError.needsApproval && apiError.code !== "approval_invalid") throw apiError;
    }
  }
}
