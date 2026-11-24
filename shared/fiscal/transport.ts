/**
 * Como o PDV chega ao Comunicador Fiscal ACBr (https://github.com/Matheus-Matta/app-fiscal-acbr).
 * O comunicador roda em dois modos e cada PDV usa um:
 *
 * - **local** (PDV desktop): o Comunicador Fiscal desktop no PC do caixa (`http://127.0.0.1:8030`).
 *   JSON comum + `Authorization: Bearer <token>`; o emitente (A1, CSC, UF) fica guardado nele.
 *   Funciona sem internet (contingência offline no próprio PC).
 * - **nuvem** (PDV web): o Docker do comunicador, chamado SÓ PELO BACKEND (`POST /pdv/acbr/`).
 *   O backend guarda o token, a `ACBR_E2E_KEY`, o certificado e o CSC, cifra o envelope e manda
 *   o contexto inteiro; o navegador nunca vê segredo nenhum.
 *
 * `trusted=false`: não há decisão fiscal confiável (sem resposta, 401/403/404/413/429, envelope
 * que não abriu). Depois de um envio, isso é "incerto": nunca vira contingência às cegas.
 */
export type AcbrAnswer = { status: number; data: Record<string, unknown>; trusted: boolean };
export type AcbrHealth = { ok: boolean; message?: string; modo?: string; motor?: string; simulador?: boolean; lib?: boolean };

export interface AcbrTransport {
  /** "local": o emitente fica guardado no comunicador; "cloud": o backend manda o emitente. */
  readonly kind: "local" | "cloud";
  call(path: string, body: Record<string, unknown>): Promise<AcbrAnswer>;
  health(): Promise<AcbrHealth>;
}

export class CommunicatorUnavailable extends Error {}

/** Respostas sem corpo fiscal (API.md §8): tratar como "sem resposta". */
const UNTRUSTED = new Set([401, 403, 404, 413, 429]);

/** Comunicador local (Comunicador Fiscal desktop / serviço Windows), modo `local`: sem cifra. */
export function localTransport(access: () => { url: string; token?: string }, timeoutMs = 60_000): AcbrTransport {
  const base = () => access().url.replace(/\/+$/, "");
  return {
    kind: "local",
    async call(path, body) {
      const { token } = access();
      if (!token) throw new Error("Configure o token do Comunicador Fiscal (Configurações → Nota fiscal).");
      let response: Response;
      try {
        response = await fetch(`${base()}${path}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(timeoutMs),
        });
      } catch (error) {
        throw new CommunicatorUnavailable(`O Comunicador Fiscal não respondeu em ${base()} (${error instanceof Error ? error.message : error}).`);
      }
      const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      const fiscal = typeof data === "object" && data !== null && ("situacao" in data || "erro" in data || response.ok);
      const trusted = !UNTRUSTED.has(response.status) && fiscal && data.erro !== "sigilo";
      if (!trusted) {
        const message = data.mensagem ?? data.detail ?? `HTTP ${response.status}`;
        return { status: response.status, data: { erro: data.erro ?? "sem_resposta", motivo: data.motivo, mensagem: message }, trusted: false };
      }
      return { status: response.status, data, trusted: true };
    },
    async health() {
      try {
        const response = await fetch(`${base()}/health`, { signal: AbortSignal.timeout(5000) });
        const body = (await response.json().catch(() => ({}))) as AcbrHealth & { mensagem?: string };
        return { ...body, ok: response.ok && body.ok !== false, message: body.mensagem ?? (response.ok ? undefined : `Comunicador respondeu ${response.status}.`) };
      } catch (error) {
        return { ok: false, message: `O Comunicador Fiscal não respondeu em ${base()} (${error instanceof Error ? error.message : error}).` };
      }
    },
  };
}

/** O servidor Starrp como ponte para o comunicador em nuvem (o backend cifra e manda o emitente). */
export function cloudTransport(server: {
  get(path: string): Promise<{ ok: boolean; status: number; data: unknown }>;
  post(path: string, data: unknown): Promise<{ ok: boolean; status: number; data: unknown }>;
}): AcbrTransport {
  const errorOf = (r: { status: number; data: unknown }) => {
    const d = r.data as { error?: { message?: string }; detail?: string } | null;
    return d?.error?.message ?? d?.detail ?? (r.status === 0 ? "Servidor fora do ar." : `Erro ${r.status}`);
  };
  return {
    kind: "cloud",
    async call(path, body) {
      const response = await server.post("/pdv/acbr/", { path, body });
      if (response.status === 0) throw new CommunicatorUnavailable("Servidor fora do ar: a nota não foi enviada.");
      if (!response.ok) return { status: response.status, data: { erro: "configuracao", mensagem: errorOf(response) }, trusted: false };
      return response.data as AcbrAnswer;
    },
    async health() {
      const response = await server.get("/pdv/acbr/health/");
      if (!response.ok) return { ok: false, message: errorOf(response) };
      return response.data as AcbrHealth;
    },
  };
}
