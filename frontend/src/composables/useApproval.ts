/**
 * Autorização de um superior no meio da operação.
 *
 *   await withApproval((approval) => salesApi.discount(id, { percent: "10", approval }))
 *
 * Tenta sem autorização; se o backend responder `*approval_required`, abre o
 * diálogo, pede usuário/senha do gerente (ou a senha do caixa) e repete a MESMA
 * chamada com `approval`. Cancelar o diálogo cancela a operação.
 *
 * Com `{ reason: "Justificativa ..." }` o diálogo abre já de saída e pede também a
 * justificativa (ex.: aprovar fechamento com diferença), que chega como 2º argumento.
 */
import { ref } from "vue";

import { ApiError, toApiError } from "@/api/errors";
import type { Approval } from "@/api/types";

export type Answer = { approval: Approval; reason: string };
type Pending = { message: string; reasonLabel?: string; resolve: (value: Answer | null) => void };

const pending = ref<Pending | null>(null);

/** Estado do diálogo, lido pelo `ApprovalDialog` montado uma vez no App. */
export function useApprovalDialog() {
  return {
    pending,
    answer(value: Answer | null) {
      pending.value?.resolve(value);
      pending.value = null;
    },
  };
}

function ask(message: string, reasonLabel?: string) {
  return new Promise<Answer | null>((resolve) => {
    pending.value = { message, reasonLabel, resolve };
  });
}

export class ApprovalCancelled extends Error {}

export async function withApproval<T>(action: (approval?: Approval, reason?: string) => Promise<T>,
                                      options: { reason?: string; message?: string } = {}): Promise<T> {
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
