/**
 * Erro da API já traduzido do envelope do backend:
 *   {"success": false, "status_code": 409, "error": {"code": "...", "message": ...}}
 *
 * `message` pode ser texto ou um objeto {campo: [erros]} (validação).
 */
import { isAxiosError } from "axios";

export type FieldErrors = Record<string, string>;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: FieldErrors = {},
  ) {
    super(message);
  }

  /** O backend pede autorização de um superior (desconto, cancelamento...). */
  get needsApproval() {
    return this.status === 403 && this.code.endsWith("approval_required");
  }
}

function firstText(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return firstText(value[0]);
  if (value && typeof value === "object") return firstText(Object.values(value)[0]);
  return "";
}

function flatten(value: unknown, prefix = ""): FieldErrors {
  const out: FieldErrors = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [key, inner] of Object.entries(value)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (inner && typeof inner === "object" && !Array.isArray(inner)) Object.assign(out, flatten(inner, name));
    else out[name] = firstText(inner);
  }
  return out;
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (!isAxiosError(error) || !error.response) {
    return new ApiError(0, "network", "Sem conexão com o servidor. Verifique a internet e tente novamente.");
  }
  const { status, data } = error.response;
  const envelope = (data as { error?: { code?: string; message?: unknown } })?.error;
  const raw = envelope?.message ?? (data as { detail?: unknown })?.detail ?? data;
  const fields = typeof raw === "object" ? flatten(raw) : {};
  const message = typeof raw === "string" ? raw : firstText(raw) || "Não foi possível concluir a operação.";
  return new ApiError(status, envelope?.code ?? "error", message, fields);
}
