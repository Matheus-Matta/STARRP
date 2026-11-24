/**
 * Contrato entre o renderer (React) e o processo principal (Electron).
 *
 * Os segredos NUNCA chegam ao renderer: o access e o refresh token, o token e a chave do
 * comunicador ACBr e o certificado A1 ficam no processo principal, criptografados com o cofre
 * do sistema. A tela pede as operações (API, impressão, nota fiscal) e recebe só o resultado.
 */
export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export type ApiRequest = {
  method: HttpMethod;
  /** Caminho sob /api/v1 (ex.: "/sales/"). */
  path: string;
  params?: Record<string, string | number | boolean | undefined | null>;
  data?: unknown;
  headers?: Record<string, string>;
};

/** Resposta crua: o renderer transforma `ok: false` em `ApiError` (o envelope do backend). */
export type ApiResponse<T = unknown> = { ok: boolean; status: number; data: T };

/* ── impressão ─────────────────────────────────────────────────────────────── */

/** Onde imprimir: impressora do Windows (pelo nome; vazio = a padrão) ou térmica na rede (ESC/POS, TCP). */
export type PrinterTarget = {
  kind: "system" | "network";
  /** Nome da impressora no Windows ("" = padrão). */
  name: string;
  host: string;
  port: number;
  /** Largura do papel em mm: 58 e 80 (bobina) ou 210 (A4). */
  paper: 58 | 80 | 210;
};

export type PrintingConfig = {
  /** "ask": pergunta antes de cada impressão (escolhe impressora e cópias); "direct": imprime direto. */
  mode: "ask" | "direct";
  /** Recibo sai sozinho ao concluir a venda. */
  autoReceipt: boolean;
  /** DANFE sai sozinho quando a nota é autorizada. */
  autoInvoice: boolean;
  copies: number;
  /** Abre a gaveta (pulso ESC/POS) ao receber em dinheiro — só impressora de rede. */
  openDrawer: boolean;
  /** Recibos, comprovantes do caixa. */
  receipt: PrinterTarget;
  /** DANFE da NFC-e / NF-e. */
  fiscal: PrinterTarget;
};

/* ── nota fiscal (comunicador ACBrLib local) ───────────────────────────────── */

export type FiscalSettings = {
  /** Emite NFC-e/NF-e por este computador. */
  enabled: boolean;
  /** Endereço do comunicador ACBrLib (ex.: http://127.0.0.1:8030). */
  acbrUrl: string;
  /** Modelo padrão: 65 = NFC-e (cupom), 55 = NF-e. */
  model: "65" | "55";
  /** Emite sozinho ao concluir a venda (senão, pelo botão no pedido). */
  autoEmit: boolean;
  /** Sem SEFAZ: assina em contingência offline (NFC-e) e transmite depois. */
  contingency: boolean;
};

export type AppConfig = {
  /** Endereço do servidor, sem /api/v1 (ex.: http://localhost:8001). */
  serverUrl: string;
  /** Loja ativa deste PDV (o terminal pertence a UMA loja). */
  storeId: string | null;
  /** Nome do terminal mostrado na retaguarda. */
  terminalName: string;
  /** installation_id por loja: o backend prende o terminal à loja em que nasceu. */
  installations: Record<string, string>;
  theme: "light" | "dark";
  printing: PrintingConfig;
  fiscal: FiscalSettings;
};

export type PrintJob = {
  html: string;
  /** Qual impressora configurada usar. */
  slot: "receipt" | "fiscal";
  /** Impressora escolhida na hora (ex.: "imprimir em outra"). */
  target?: PrinterTarget;
  /** true = imprime direto mesmo no modo "perguntar" (já perguntou na tela). */
  confirmed?: boolean;
  copies?: number;
  /** Pulso da gaveta junto (só rede). */
  drawer?: boolean;
  title?: string;
};
export type PrintResult = { ok: boolean; error?: string; cancelled?: boolean };
export type SystemPrinter = { name: string; displayName: string; isDefault: boolean };

/** Estado dos segredos do comunicador (só se existem, nunca o valor). */
export type FiscalSecrets = { token: boolean };

/* Nota fiscal: os tipos são do núcleo compartilhado com o PDV web (`shared/fiscal`). */
import type { EmitRequest, EmitResult, FiscalKitInfo, LocalInvoice } from "../../../shared/fiscal/types";
export type { EmitRequest, EmitResult, FiscalKitInfo, LocalInvoice };

/* ── offline ───────────────────────────────────────────────────────────────── */

export type NetStatus = {
  /** O servidor respondeu à última verificação. */
  online: boolean;
  /** Vendas/notas esperando o servidor. */
  pending: number;
  /** Itens que o servidor recusou (precisam de atenção). */
  failed: number;
  lastSync: string | null;
  snapshotAt: string | null;
  syncing: boolean;
};

export type OutboxEntry = {
  id: string;
  kind: "sale" | "invoice" | "cash";
  label: string;
  createdAt: string;
  attempts: number;
  status: "pending" | "failed" | "done";
  lastError: string;
  /** Venda offline: o corpo de /pdv/offline-sales/; nota: { saleId, invoiceKey }. */
  payload: Record<string, unknown>;
  /** Venda criada no servidor depois do envio. */
  serverId?: string;
  /** A venda como o servidor devolveu (número real). */
  serverSale?: Record<string, unknown>;
  /** Segurada até a nota sair (vai com a venda); passou do prazo, vai sozinha. */
  heldUntil?: string;
};

export type CashState = {
  session: Record<string, unknown> | null;
  movements: Record<string, unknown>[];
  closed: Record<string, unknown>[];
  closing: string[];
};

export type FlushResult = { status: "done" | "queued" | "failed"; sale?: Record<string, unknown>; error?: string };

export type AuthorizeRequest = {
  code: "sales.discount" | "sales.price_override" | "sales.cancel_item" | "sales.cancel" | "cash.approve";
  percent?: number;
  approval?: { username?: string; password?: string; cash_password?: string };
};
/** `ok: false` traz o mesmo erro que a API daria (`*approval_required`, `approval_invalid`). */
export type AuthorizeResult =
  | { ok: true; offline: boolean; approver: { id: number; username: string; name: string } | null; by: "self" | "approver" | "cash_password" }
  | { ok: false; status: number; code: string; message: string };

export type Snapshot = {
  generated_at: string;
  products: Record<string, unknown>[];
  categories: { id: string; name: string; parent: string | null }[];
  customers: { id: string; name: string; document: string; phone: string; email: string; credit_balance?: string }[];
};

/** O que o PDV guarda para abrir sem o servidor (último /me/ e bootstrap). */
export type OfflineCache = { me?: unknown; boot?: unknown; savedAt?: string };

export type StarrpBridge = {
  api: (request: ApiRequest) => Promise<ApiResponse>;
  auth: {
    login: (username: string, password: string) => Promise<ApiResponse>;
    logout: () => Promise<void>;
    hasSession: () => Promise<boolean>;
    /** A sessão expirou (refresh recusado): a tela volta ao login. */
    onExpired: (listener: () => void) => () => void;
  };
  config: {
    get: () => Promise<AppConfig>;
    set: (patch: Partial<AppConfig>) => Promise<AppConfig>;
    installationId: (storeId: string) => Promise<string>;
  };
  printers: {
    list: () => Promise<SystemPrinter[]>;
    print: (job: PrintJob) => Promise<PrintResult>;
    test: (slot: "receipt" | "fiscal", target?: PrinterTarget) => Promise<PrintResult>;
  };
  fiscal: {
    secrets: () => Promise<FiscalSecrets>;
    setSecrets: (values: { token?: string }) => Promise<FiscalSecrets>;
    health: () => Promise<{ ok: boolean; message: string }>;
    /** Grava o certificado A1 e o CSC da filial NO comunicador (só quem tem `fiscal.manage`). */
    storeEmitter: () => Promise<{ ok: boolean; message: string }>;
    kit: () => Promise<FiscalKitInfo>;
    refreshKit: () => Promise<FiscalKitInfo>;
    emit: (request: EmitRequest) => Promise<EmitResult>;
    invoices: (saleRef?: string) => Promise<LocalInvoice[]>;
  };
  /** Dados do PDV local-first neste PC (criptografados): venda em andamento, pedidos guardados,
   *  histórico e as autorizações (online confere no servidor e aprende; offline confere aqui). */
  local: {
    currentSale: (userId: number) => Promise<Record<string, unknown> | null>;
    saveCurrentSale: (userId: number, sale: Record<string, unknown> | null) => Promise<void>;
    parked: () => Promise<Record<string, unknown>[]>;
    park: (sale: Record<string, unknown>) => Promise<void>;
    unpark: (id: string) => Promise<Record<string, unknown> | null>;
    history: () => Promise<Record<string, unknown>[]>;
    remember: (sale: Record<string, unknown>) => Promise<void>;
    authorize: (body: AuthorizeRequest) => Promise<AuthorizeResult>;
    unlock: (username: string, password: string) => Promise<boolean>;
    cash: () => Promise<CashState>;
    saveCash: (state: CashState) => Promise<void>;
  };
  offline: {
    status: () => Promise<NetStatus>;
    onStatus: (listener: (status: NetStatus) => void) => () => void;
    snapshot: () => Promise<Snapshot | null>;
    refreshSnapshot: () => Promise<NetStatus>;
    cache: () => Promise<OfflineCache>;
    saveCache: (cache: OfflineCache) => Promise<void>;
    /** `hold`: segura até `flush` (a nota sai antes e vai junto com a venda). */
    enqueueSale: (payload: Record<string, unknown>, label: string, hold?: boolean) => Promise<OutboxEntry>;
    /** Envia já (servidor no ar) e devolve a venda do servidor; sem ele, fica na fila. */
    flush: (id: string) => Promise<FlushResult>;
    /** Evento do turno de caixa feito neste PC (abertura, sangria/suprimento, fechamento). */
    enqueueCash: (payload: Record<string, unknown>, label: string) => Promise<OutboxEntry>;
    nextLocalNumber: () => Promise<number>;
    outbox: () => Promise<OutboxEntry[]>;
    retry: (id?: string) => Promise<NetStatus>;
    discard: (id: string) => Promise<void>;
    syncNow: () => Promise<NetStatus>;
  };
  app: { version: () => Promise<string>; toggleFullscreen: () => Promise<void>; quit: () => Promise<void> };
};
