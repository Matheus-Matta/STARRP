/**
 * Autorização de um superior no meio da operação.
 *
 *   await withApproval((approval) => salesApi.discount(id, { percent: "10", approval }))
 *
 * Tenta sem autorização; se o backend responder `*approval_required`, abre o
 * diálogo, pede usuário/senha do gerente (ou a senha do caixa) e repete a MESMA
 * chamada com `approval`. Cancelar o diálogo cancela a operação.
 */
import { ref } from "vue";

import { ApiError, toApiError } from "@/api/errors";
import type { Approval } from "@/api/types";

type Pending = { message: string; resolve: (value: Approval | null) => void };

const pending = ref<Pending | null>(null);

/** Estado do diálogo, lido pelo `ApprovalDialog` montado uma vez no App. */
export function useApprovalDialog() {
  return {
    pending,
    answer(value: Approval | null) {
      pending.value?.resolve(value);
      pending.value = null;
    },
  };
}

function ask(message: string) {
  return new Promise<Approval | null>((resolve) => {
    pending.value = { message, resolve };
  });
}

export class ApprovalCancelled extends Error {}

export async function withApproval<T>(action: (approval?: Approval) => Promise<T>): Promise<T> {
  try {
    return await action();
  } catch (error) {
    let apiError: ApiError = toApiError(error);
    // Senha errada também volta como pedido de autorização: perguntamos de novo.
    while (apiError.needsApproval || apiError.code === "approval_invalid") {
      const approval = await ask(apiError.message);
      if (!approval) throw new ApprovalCancelled("Operação cancelada.");
      try {
        return await action(approval);
      } catch (retry) {
        apiError = toApiError(retry);
      }
    }
    throw apiError;
  }
}
