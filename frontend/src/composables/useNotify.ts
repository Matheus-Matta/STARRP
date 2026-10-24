import { useToast } from "primevue/usetoast";

import { toApiError } from "@/api/errors";

/** Avisos padronizados: o erro da API vira mensagem legível, sempre igual. */
export function useNotify() {
  const toast = useToast();
  return {
    success: (summary: string, detail?: string) => toast.add({ severity: "success", summary, detail, life: 3000 }),
    warn: (summary: string, detail?: string) => toast.add({ severity: "warn", summary, detail, life: 5000 }),
    error: (error: unknown, summary = "Não foi possível concluir") => {
      const apiError = toApiError(error);
      toast.add({ severity: "error", summary, detail: apiError.message, life: 6000 });
      return apiError;
    },
  };
}
