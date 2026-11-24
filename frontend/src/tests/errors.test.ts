import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { readBlobError, toApiError } from "@/api/errors";

function axiosError(data: unknown, status = 403, code?: string) {
  const config = { headers: new AxiosHeaders() };
  const response = status ? { data, status, statusText: "", headers: {}, config } : undefined;
  return new AxiosError("falhou", code, config, null, response as never);
}

describe("erros da API", () => {
  it("mostra a mensagem do backend em download (blob) que falhou", async () => {
    const body = JSON.stringify({ success: false, error: { code: "permission_denied", message: "Sem permissão para margem." } });
    const error = axiosError(new Blob([body], { type: "application/json" }));
    await readBlobError(error);
    const api = toApiError(error);
    expect(api.status).toBe(403);
    expect(api.message).toBe("Sem permissão para margem.");
  });

  it("tempo esgotado não vira 'sem conexão'", () => {
    expect(toApiError(axiosError(null, 0, "ECONNABORTED")).code).toBe("timeout");
    expect(toApiError(axiosError(null, 0, "ERR_NETWORK")).code).toBe("network");
  });
});
