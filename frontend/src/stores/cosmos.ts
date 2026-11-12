/**
 * Cosmos: estado do widget e a conexão WebSocket com o backend.
 *
 * - um socket por aba, aberto quando o usuário tem `cosmos.view`; cai → reconecta sozinho
 *   (credencial vencida → renova o login uma vez antes de tentar de novo);
 * - o backend manda tudo pelo socket: o texto chegando (`delta`), o que ela está fazendo
 *   (`status`), a mensagem pronta (`message`), o cartão de confirmação atualizado (`action`)
 *   e os alertas da supervisão (`alert`), que aparecem num balão mesmo com o widget fechado;
 * - anexos (planilha/CSV/texto) sobem antes pela API REST e vão na mensagem só pelos ids;
 * - o resumo diário da equipe chega como conversa nova (`digest`), com aviso no balão;
 * - listas, falas, renomear, apagar e alertas usam a API REST; o socket fica dedicado ao que é
 *   realmente em tempo real, sem duplicar mutações nem precisar de fallback por timeout.
 */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import {
  type CosmosAction, type CosmosAttachment, type CosmosConversation, type CosmosFinding, type CosmosMessage,
  type CosmosStatus, CONVERSATION_PAGE, cosmosApi, cosmosError, cosmosSocketUrl,
} from "@/api/cosmos";
import { http } from "@/api/http";

import { useSession } from "./session";

type View = "home" | "chat" | "alerts";
type ServerEvent =
  | { type: "ready"; enabled: boolean }
  | { type: "conversation"; conversation: CosmosConversation }
  | { type: "message"; conversation: string; message: CosmosMessage }
  | { type: "delta"; conversation: string; text: string }
  | { type: "status"; conversation: string; text: string }
  | { type: "typing"; conversation: string; on: boolean }
  | { type: "action"; conversation: string; action: CosmosAction }
  | { type: "alert"; finding: CosmosFinding }
  | { type: "digest"; conversation: CosmosConversation }
  | { type: "error"; conversation: string; message: string }
  | { type: "pong" };

const RETRY_MAX = 30_000;
const MAX_FILES = 5;

export const useCosmos = defineStore("cosmos", () => {
  const session = useSession();
  const status = ref<CosmosStatus | null>(null);
  const open = ref(false);
  const view = ref<View>("home");
  const conversations = ref<CosmosConversation[]>([]);
  const conversationSearch = ref("");
  const conversationPage = ref(0);
  const conversationsEnd = ref(false);
  const conversationsLoading = ref(false);
  let conversationTicket = 0;
  const activeId = ref<string | null>(null);
  const messages = ref<Record<string, CosmosMessage[]>>({});
  const live = ref<Record<string, string>>({});
  const doing = ref<Record<string, string>>({});
  const busy = ref<Record<string, boolean>>({});
  const errors = ref<Record<string, string>>({});
  const alerts = ref<CosmosFinding[]>([]);
  const peek = ref<CosmosFinding | null>(null);
  const connection = ref<"off" | "connecting" | "on">("off");
  /** Primeira mensagem de uma conversa nova: a conversa só existe quando o servidor responde. */
  const pendingNew = ref(false);
  /** Última mensagem enviada em cada conversa: o "Tentar de novo" reenvia ela. */
  const lastAsked = ref<Record<string, string>>({});
  /** Anexos já enviados ao servidor, esperando a mensagem (por conversa; "new" = conversa nova). */
  const files = ref<Record<string, CosmosAttachment[]>>({});
  const uploading = ref(0);
  /** Resumo diário que acabou de chegar (balão sobre o botão, com o widget fechado). */
  const digestPeek = ref<CosmosConversation | null>(null);

  let socket: WebSocket | null = null;
  let retry = 1000;
  let retryTimer: number | undefined;
  let pingTimer: number | undefined;
  let refreshed = false;
  let stopped = true;

  const active = computed(() => conversations.value.find((c) => c.id === activeId.value) ?? null);
  const key = computed(() => activeId.value ?? "new");
  const thread = computed(() => messages.value[key.value] ?? []);
  const canUse = computed(() => session.can("cosmos.view"));

  function storeHeader() {
    return session.activeStoreId;
  }

  // ── conexão ────────────────────────────────────────────────────────────
  function connect() {
    if (socket || !canUse.value) return;
    stopped = false;
    connection.value = "connecting";
    const ws = new WebSocket(cosmosSocketUrl(storeHeader()));
    socket = ws;
    ws.onopen = () => {
      connection.value = "on";
      // Reconectou: o que chegou enquanto estava fora (o fim de uma resposta) vem do servidor.
      if (activeId.value) void loadMessages(activeId.value).catch(() => undefined);
      retry = 1000;
      refreshed = false;
      pingTimer = window.setInterval(() => send({ type: "ping" }), 25_000);
    };
    ws.onmessage = (event) => {
      try {
        handle(JSON.parse(event.data) as ServerEvent);
      } catch {
        // mensagem fora do formato: ignora
      }
    };
    ws.onclose = async (event) => {
      socket = null;
      connection.value = "off";
      window.clearInterval(pingTimer);
      // Caiu no meio de uma resposta: o aviso de "terminei" não vai chegar; não fica digitando para sempre.
      busy.value = {};
      doing.value = {};
      live.value = {};
      if (stopped || event.code === 4403) return;
      if (event.code === 4401 && !refreshed) {
        refreshed = true;
        const ok = await http.post("/auth/refresh/", {}).then(() => true).catch(() => false);
        if (!ok) return;
      }
      retryTimer = window.setTimeout(connect, retry);
      retry = Math.min(retry * 2, RETRY_MAX);
    };
  }

  function disconnect() {
    stopped = true;
    window.clearTimeout(retryTimer);
    window.clearInterval(pingTimer);
    socket?.close();
    socket = null;
  }

  function send(payload: Record<string, unknown>) {
    if (socket?.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(payload));
    return true;
  }

  watch(() => session.activeStoreId, (store) => send({ type: "store", store }));

  // ── acontecimentos do servidor ─────────────────────────────────────────
  function upsertMessage(message: CosmosMessage) {
    const list = messages.value[message.conversation] ?? [];
    let index = list.findIndex((m) => m.id === message.id);
    // A fala do usuário já está na tela (cópia local mostrada no envio): a do servidor ocupa o lugar dela.
    if (index < 0 && message.role === "user") {
      index = list.findIndex((m) => m.id.startsWith("local-") && m.content === message.content);
    }
    messages.value[message.conversation] = index >= 0
      ? list.map((m, i) => (i === index ? message : m))
      : [...list, message];
  }

  function handle(event: ServerEvent) {
    switch (event.type) {
      case "ready":
        if (status.value) status.value.enabled = event.enabled;
        break;
      case "conversation": {
        conversations.value = [event.conversation, ...conversations.value.filter((c) => c.id !== event.conversation.id)];
        // O resumo diário chega como conversa nova, mas não é a que o usuário acabou de começar.
        if (pendingNew.value && !event.conversation.digest_day) {
          pendingNew.value = false;
          messages.value[event.conversation.id] = messages.value.new ?? [];
          delete messages.value.new;
          delete busy.value.new; // o "digitando" passa para a conversa de verdade
          busy.value[event.conversation.id] = true;
          activeId.value = event.conversation.id;
        }
        break;
      }
      case "message": {
        upsertMessage(event.message);
        live.value[event.conversation] = "";
        if (event.message.role === "assistant") doing.value[event.conversation] = "";
        const conv = conversations.value.find((c) => c.id === event.conversation);
        if (conv) conv.last_message_at = event.message.created_at;
        break;
      }
      case "delta":
        live.value[event.conversation] = (live.value[event.conversation] ?? "") + event.text;
        doing.value[event.conversation] = "";
        break;
      case "status":
        doing.value[event.conversation] = event.text;
        break;
      case "typing":
        busy.value[event.conversation] = event.on;
        if (!event.on) {
          doing.value[event.conversation] = "";
          live.value[event.conversation] = "";
        }
        break;
      case "action":
        for (const message of messages.value[event.conversation] ?? []) {
          message.blocks = message.blocks.map((b) =>
            b.type === "action" && b.action.id === event.action.id ? { ...b, action: event.action } : b);
        }
        break;
      case "alert":
        alerts.value = [event.finding, ...alerts.value.filter((a) => a.id !== event.finding.id)];
        if (status.value) status.value.open_alerts += 1;
        if (!open.value || view.value !== "alerts") peek.value = event.finding;
        break;
      case "digest":
        if (!open.value) digestPeek.value = event.conversation;
        break;
      case "error": {
        const target = event.conversation || key.value;
        errors.value[target] = event.message;
        busy.value[target] = false;
        doing.value[target] = "";
        break;
      }
    }
  }

  // ── ações da tela ──────────────────────────────────────────────────────
  async function boot() {
    if (!canUse.value) return;
    status.value = await cosmosApi.status().catch(() => null);
    if (!status.value?.can_use) return;
    connect();
  }

  /** Primeira página da lista (com a busca atual). Rolar até o fim → `loadMoreConversations`. */
  async function loadConversations(search = conversationSearch.value) {
    conversationSearch.value = search;
    conversationPage.value = 0;
    conversationsEnd.value = false;
    await fetchConversationPage(true);
  }

  async function loadMoreConversations() {
    if (conversationsLoading.value || conversationsEnd.value) return;
    await fetchConversationPage(false);
  }

  async function fetchConversationPage(reset: boolean) {
    const page = conversationPage.value + 1;
    const q = conversationSearch.value.trim();
    const ticket = ++conversationTicket;
    conversationsLoading.value = true;
    try {
      const rows = await cosmosApi.conversations(page, q);
      if (ticket !== conversationTicket) return; // a busca mudou no meio: esta resposta é velha
      // Conversa nova entra no topo pelo socket e empurra a lista: a página seguinte pode repetir uma.
      const seen = new Set(reset ? [] : conversations.value.map((c) => c.id));
      conversations.value = [...(reset ? [] : conversations.value), ...rows.filter((c) => !seen.has(c.id))];
      conversationPage.value = page;
      conversationsEnd.value = rows.length < CONVERSATION_PAGE;
    } catch {
      // mantém o que já está na tela; rolar de novo tenta outra vez
    } finally {
      if (ticket === conversationTicket) conversationsLoading.value = false;
    }
  }

  async function loadMessages(id: string) {
    const data = await cosmosApi.messages(id);
    messages.value[data.conversation.id] = data.messages;
  }

  async function openConversation(id: string) {
    activeId.value = id;
    view.value = "chat";
    errors.value[id] = "";
    await loadMessages(id);
  }

  function newConversation() {
    activeId.value = null;
    messages.value.new = [];
    delete busy.value.new;
    view.value = "chat";
  }

  /** Sobe os arquivos escolhidos (ou arrastados); ficam no campo até a mensagem ser enviada. */
  async function attach(list: FileList | File[]) {
    const target = key.value;
    for (const file of Array.from(list)) {
      if ((files.value[target]?.length ?? 0) + uploading.value >= MAX_FILES) {
        errors.value[target] = `No máximo ${MAX_FILES} arquivos por mensagem.`;
        break;
      }
      uploading.value += 1;
      try {
        const item = await cosmosApi.upload(file);
        files.value[target] = [...(files.value[target] ?? []), item];
        errors.value[target] = "";
      } catch (error) {
        errors.value[target] = `${file.name}: ${cosmosError(error, "não consegui ler o arquivo.")}`;
      } finally {
        uploading.value -= 1;
      }
    }
  }

  function detach(id: string) {
    files.value[key.value] = (files.value[key.value] ?? []).filter((f) => f.id !== id);
  }

  function ask(text: string, finding?: string) {
    const target = key.value;
    const attached = files.value[target] ?? [];
    // Só o anexo, sem texto: o servidor grava esta mesma frase (a cópia local casa com a do servidor).
    const body = text.trim() || (attached.length ? (attached.length === 1 ? "Veja o anexo." : "Veja os anexos.") : "");
    if (!body) return false;
    const conversation = activeId.value;
    // A tela aberta vai junto: "corrige este produto" sabe qual é.
    const page = { path: window.location.pathname, title: document.title };
    const ok = send({ type: "message", conversation, text: body, store: storeHeader(), finding, page,
                      attachments: attached.map((f) => f.id) });
    lastAsked.value[target] = body;
    if (!ok) {
      errors.value[target] = "Sem conexão com a Cosmos. Tentando reconectar…";
      connect();
      return false;
    }
    errors.value[target] = "";
    // Mostra na hora o que o usuário escreveu; a fala de verdade chega pelo socket e substitui esta.
    const echo: CosmosMessage = { id: `local-${Date.now()}`, conversation: target, role: "user", content: body,
                                  blocks: attached.length ? [{ type: "attachments", items: attached }] : [],
                                  created_at: new Date().toISOString() };
    delete files.value[target];
    if (!conversation) pendingNew.value = true;
    messages.value[target] = [...(conversation ? messages.value[target] ?? [] : []), echo];
    busy.value[target] = true;
    return true;
  }

  /** Uma proposta ou várias de uma vez ("Confirmar todas"): uma resposta só da Cosmos no fim. */
  function decide(actions: CosmosAction | CosmosAction[], approve: boolean) {
    const ids = (Array.isArray(actions) ? actions : [actions]).map((a) => a.id);
    if (!send({ type: "decide", actions: ids, approve })) {
      errors.value[key.value] = "Sem conexão com a Cosmos. Tentando reconectar…";
      connect();
      return;
    }
    if (activeId.value) busy.value[activeId.value] = true;
  }

  /** Parar a resposta em andamento. */
  function stop() {
    if (activeId.value) send({ type: "stop", conversation: activeId.value });
  }

  /** Reenvia a última mensagem desta conversa (depois de um erro). */
  function retryLast() {
    const text = lastAsked.value[key.value];
    if (!text) return;
    // A fala já está na tela: tira a cópia local para não aparecer duas vezes.
    const list = messages.value[key.value] ?? [];
    const last = list[list.length - 1];
    if (last?.role === "user" && last.content === text) messages.value[key.value] = list.slice(0, -1);
    ask(text);
  }

  async function removeConversation(id: string) {
    await cosmosApi.remove(id);
    conversations.value = conversations.value.filter((c) => c.id !== id);
    if (activeId.value === id) {
      activeId.value = null;
      view.value = "home";
    }
  }

  async function renameConversation(id: string, title: string) {
    await cosmosApi.rename(id, title);
    const conv = conversations.value.find((c) => c.id === id);
    if (conv) conv.title = title;
  }

  async function loadAlerts() {
    if (!status.value?.can_supervise) return;
    alerts.value = await cosmosApi.findings().catch(() => alerts.value);
    if (status.value) status.value.open_alerts = alerts.value.length;
  }

  async function resolveAlert(finding: CosmosFinding, how: "resolved" | "dismissed") {
    await cosmosApi.resolveFinding(finding.id, how);
    alerts.value = alerts.value.filter((a) => a.id !== finding.id);
    if (status.value) status.value.open_alerts = Math.max(0, status.value.open_alerts - 1);
    if (peek.value?.id === finding.id) peek.value = null;
  }

  /** "Resolver com a Cosmos": conversa nova já com o alerta como assunto. */
  function fixWithCosmos(finding: CosmosFinding) {
    open.value = true;
    peek.value = null;
    newConversation();
    ask(`Me ajude a corrigir este alerta da supervisão: "${finding.title}". ${finding.detail} ` +
        `(registro: ${finding.entity} ${finding.object_id}). Quem fez: ${finding.actor ?? "não identificado"}.`, finding.id);
  }

  /** Abre o resumo diário que chegou (clique no balão). */
  function openDigest() {
    const conversation = digestPeek.value;
    digestPeek.value = null;
    if (!conversation) return;
    toggle(true);
    void openConversation(conversation.id);
  }

  function toggle(value = !open.value) {
    open.value = value;
    if (value) {
      peek.value = null;
      digestPeek.value = null;
      void loadConversations();
      void loadAlerts();
      if (!socket) connect();
    }
  }

  return {
    status, open, view, conversations, conversationSearch, conversationsEnd, conversationsLoading,
    loadMoreConversations, activeId, active, thread, messages, live, doing, busy, errors, alerts, peek,
    connection, key, canUse, files, uploading, digestPeek, attach, detach, openDigest, boot, connect, disconnect, loadConversations, openConversation, newConversation, ask,
    decide, stop, retryLast, lastAsked, removeConversation, renameConversation, loadAlerts, resolveAlert, fixWithCosmos, toggle,
  };
});
