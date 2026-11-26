/**
 * Tipos do núcleo fiscal compartilhado (PDV desktop e PDV web usam o MESMO código para montar,
 * numerar, emitir, guardar e transmitir NFC-e/NF-e pelo Comunicador Fiscal ACBr — app-fiscal-acbr).
 */

/** Kit do servidor (`GET /pdv/fiscal-kit/`): tudo para MONTAR a nota. Sem certificado nem CSC
 *  (local: guardados no comunicador; nuvem: no backend, que os manda em cada chamada). */
export type Kit = {
  config_id?: string;
  environment: string;
  issuer: Record<string, string>;
  simple: boolean;
  offline_contingency: boolean;
  certificate: { valid_until: string | null };
  portal_url: string;
  series: Record<string, { series: number; next_number: number }>;
  default_profile: string | null;
  profiles: Record<string, Record<string, string>>;
  variants: Record<string, { ncm: string; cest: string; origin: string; type: string; profile: string | null; barcode: string }>;
  generated_at: string;
  /** Filial do kit (o PDV troca de filial: o kit de outra não vale). */
  storeId: string;
};

/** Uma nota emitida por este terminal (fica guardada aqui até o servidor saber). */
export type LocalInvoice = {
  key: string;
  saleRef: string;
  /** id da venda no servidor (vazio enquanto a venda for só local). */
  saleId: string;
  document_model: "65" | "55";
  series: number;
  number: number;
  environment: string;
  emission_type: "1" | "9";
  status: "authorized" | "contingency" | "rejected" | "error" | "processing";
  access_key: string;
  protocol: string;
  qrcode: string;
  message: string;
  issued_at: string;
  xml: string;
  /** O que vai ao backend em `/sales/{id}/invoices/register/` (itens, totais, destinatário). */
  register: Record<string, unknown>;
  /** Dados para imprimir o DANFE sem o servidor. */
  danfe: Record<string, unknown>;
  synced: boolean;
  /** id da nota no servidor depois de registrada (para imprimir o DANFE de lá). */
  server_invoice_id?: string;
};

export type EmitRequest = {
  /** A venda como o servidor devolve (ou a venda local: mesmo formato). */
  sale: Record<string, unknown>;
  model: "65" | "55";
  /** Chave da venda: o número reservado é reaproveitado numa nova tentativa. */
  saleRef: string;
  /** A venda local já virou venda do servidor (nota emitida depois do envio): id de lá. */
  saleId?: string;
};
export type EmitResult = { ok: boolean; invoice?: LocalInvoice; error?: string };

/** O que a tela vê do kit (sem segredo). */
export type FiscalKitInfo = {
  ready: boolean;
  error?: string;
  environment?: string;
  issuer?: { legal_name: string; cnpj: string; state: string };
  series?: Record<string, { series: number; next_number: number }>;
  certificateValidUntil?: string | null;
  generatedAt?: string;
};

/** Numeração do terminal: a série dele e o número reservado de cada venda. */
export type Numbers = {
  series: Record<string, number>;
  next: Record<string, number>;
  bySale: Record<string, Reserved>;
};

/** O número reservado de uma venda. `cNF` fica com ele: a chave é a mesma em toda tentativa. */
export type Reserved = {
  series: number;
  number: number;
  cNF?: string;
  /** Envio sem resposta confiável: a nota PODE ter saído com esta data (a chave depende do mês dela). */
  uncertainAt?: string;
};

/** Onde cada PDV guarda (desktop: arquivos cifrados pelo Windows; web: armazenamento do navegador). */
export interface FiscalStorage {
  kit(): Kit | null;
  saveKit(kit: Kit): void;
  numbers(): Numbers;
  saveNumbers(numbers: Numbers): void;
  invoices(): LocalInvoice[];
  saveInvoices(invoices: LocalInvoice[]): void;
}

/** Como chegar ao Comunicador Fiscal local deste caixa (PDV desktop; a web vai pelo backend). */
export type CommunicatorAccess = { url: string; token?: string };

/** O servidor Starrp (o PDV passa o cliente dele: desktop pelo processo principal, web pelo http). */
export interface FiscalServer {
  get(path: string, params?: Record<string, string>): Promise<{ ok: boolean; status: number; data: unknown }>;
  post(path: string, data: unknown): Promise<{ ok: boolean; status: number; data: unknown }>;
}

/** Ajustes deste terminal que mudam a emissão. */
export type EmitOptions = { contingency: boolean };
