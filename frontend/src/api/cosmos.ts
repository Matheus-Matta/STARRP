/** Cosmos (assistente de IA): a conversa corre pelo WebSocket; aqui fica o que é REST. */
import { http, type Page } from "./http";
import type { BookReport } from "./reports";

export type CosmosStatus = { enabled: boolean; model: string | null; can_use: boolean; can_write: boolean;
                             can_supervise: boolean; open_alerts: number;
                             /** O que a pessoa mais faz (temas, do mais frequente): ordena os atalhos. */
                             habits?: string[] };

/** `digest_day`: resumo diário da equipe (a Cosmos manda de manhã para quem supervisiona). */
export type CosmosConversation = { id: string; title: string; last_message_at: string; created_at: string;
                                   digest_day?: string | null };

/** Planilha/CSV/texto mandado na conversa (já lido no servidor). */
export type CosmosAttachment = { id: string; name: string; kind: "sheet" | "text"; rows: number; columns: number };

export type CosmosButton = { label: string; kind: "reply" | "link"; value: string };
export type CosmosPreviewRow = { label: string; value: string; from?: string };
export type CosmosAction = {
  id: string; title: string; summary: string; method: string; path: string; preview: CosmosPreviewRow[];
  status: "pending" | "executed" | "failed" | "rejected" | "expired";
  result: { status: number; ok: boolean; id: string | null; endpoint: string; message: string } | null;
};
export type CosmosBlock =
  | { type: "report"; report: BookReport & { id: string } }
  | { type: "action"; action: CosmosAction }
  | { type: "buttons"; buttons: CosmosButton[] }
  | { type: "attachments"; items: CosmosAttachment[] };

export type CosmosMessage = { id: string; conversation: string; role: "user" | "assistant" | "event";
                              content: string; blocks: CosmosBlock[]; created_at: string };

export type CosmosFinding = { id: string; rule: string; severity: "info" | "warning" | "critical"; title: string;
                              detail: string; entity: string; object_id: string; endpoint: string; status: string;
                              actor: string | null; created_at: string; message?: string };

type FindingRow = Omit<CosmosFinding, "actor"> & { actor_name: string | null; store_name: string | null };

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Conversas por página (mesmo tamanho no socket: `CONVERSATION_PAGE` em services/cosmos/rpc.py). */
export const CONVERSATION_PAGE = 20;

export const cosmosApi = {
  status: () => http.get<CosmosStatus>("/cosmos/status/").then((r) => r.data),
  /** Uma página (20) da lista; depois da última o DRF dá 404 → lista vazia. */
  conversations: (page = 1, q = "") =>
    http.get<Page<CosmosConversation>>("/cosmos/conversations/",
                                       { params: { page, page_size: CONVERSATION_PAGE, ...(q ? { q } : {}) } })
      .then((r) => r.data.results)
      .catch((error) => {
        if (error?.response?.status === 404) return [] as CosmosConversation[];
        throw error;
      }),
  messages: (id: string) =>
    http.get<{ conversation: CosmosConversation; messages: CosmosMessage[] }>(`/cosmos/conversations/${id}/messages/`)
      .then((r) => r.data),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.post<CosmosAttachment>("/cosmos/attachments/", form, { timeout: 60_000 }).then((r) => r.data);
  },
  rename: (id: string, title: string) => http.patch(`/cosmos/conversations/${id}/`, { title }),
  remove: (id: string) => http.delete(`/cosmos/conversations/${id}/`),
  findings: () =>
    http.get<Page<FindingRow>>("/cosmos/findings/", { params: { status: "open", page_size: 50 } })
      .then((r) => r.data.results.map((f) => ({ ...f, actor: f.actor_name }))),
  resolveFinding: (id: string, status: "resolved" | "dismissed") =>
    http.post(`/cosmos/findings/${id}/resolve/`, { status }),
  async download(reportId: string, formato: "xlsx" | "csv") {
    const response = await http.get<Blob>(`/cosmos/reports/${reportId}/export/`, {
      params: { formato }, responseType: "blob", timeout: 120_000,
    });
    const name = /filename="([^"]+)"/.exec(String(response.headers["content-disposition"] ?? ""))?.[1] ?? `relatorio.${formato}`;
    save(response.data, name);
  },
};

/** Texto do erro da API (`{"error": {"message": "..." | {"campo": ["..."]}}}`). */
export function cosmosError(error: unknown, fallback: string) {
  const message = (error as { response?: { data?: { error?: { message?: unknown } } } }).response?.data?.error?.message;
  if (typeof message === "string") return message;
  if (message && typeof message === "object") return Object.values(message).flat().join(" ") || fallback;
  return fallback;
}

/** Endereço do WebSocket (mesma origem: os cookies de login vão junto). */
export function cosmosSocketUrl(storeId: string | null) {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const store = storeId ? `?store=${encodeURIComponent(storeId)}` : "";
  return `${scheme}://${window.location.host}/api/v1/ws/cosmos/${store}`;
}
