/**
 * Núcleo fiscal do PDV — o MESMO para o desktop (processo principal do Electron) e para a web
 * (navegador). Emite NFC-e/NF-e pelo Comunicador Fiscal ACBr (app-fiscal-acbr), por um dos
 * transportes de `transport.ts`:
 *
 * - desktop → comunicador LOCAL (o Comunicador Fiscal desktop no PC do caixa, só com o token);
 * - web → o backend, que chama o comunicador em NUVEM (Docker) cifrado e com o certificado.
 *
 *
 * - o kit do servidor (`/pdv/fiscal-kit/`) diz como MONTAR a nota (emitente, perfis, NCM, série
 *   do terminal) e fica guardado: a nota sai mesmo com o servidor fora;
 * - certificado A1 e CSC: no local, GUARDADOS NO COMUNICADOR (tela Emitente dele, ou
 *   `storeEmitter` por quem administra o fiscal); na nuvem, ficam no backend e vão em cada
 *   chamada dentro do envelope. O PDV manda só o documento, e nunca guarda o certificado;
 * - numeração: série própria do terminal; o número de uma venda é reservado uma vez e
 *   reaproveitado nas novas tentativas (rejeitada não consome número na SEFAZ);
 * - SEFAZ fora (e só ela: o comunicador respondeu de forma confiável): NFC-e em contingência offline
 *   (tpEmis 9), impressa, e transmitida depois (`transmitPending`);
 * - a nota vai ao servidor em `/sales/{id}/invoices/register/` (venda que já existe lá) ou junto
 *   com a venda pronta (`/pdv/offline-sales/`), e fica guardada aqui até ele saber.
 */
import { buildIni, cents, digits, fmt, lines, messageOf, num, payments, pickResult, recipientOf, statusOf, totals, tzOffset } from "./document";
import type { SaleLike } from "./document";
import { CommunicatorUnavailable } from "./transport";
import type { AcbrTransport } from "./transport";
import type { EmitOptions, EmitRequest, EmitResult, FiscalKitInfo, FiscalServer, FiscalStorage, Kit, LocalInvoice } from "./types";

export type FiscalDeps = {
  storage: FiscalStorage;
  server: FiscalServer;
  transport: AcbrTransport;
  storeId: () => string | null;
  installationId: () => string;
};

const KEEP_DAYS = 30;

export function createFiscal(deps: FiscalDeps) {
  const { storage, server } = deps;

  function kit(): Kit | null {
    const k = storage.kit();
    return k && k.storeId === deps.storeId() ? k : null;
  }

  function kitInfo(error?: string): FiscalKitInfo {
    const k = kit();
    if (!k) return { ready: false, error: error ?? "Kit fiscal ainda não baixado (precisa do servidor uma vez)." };
    const next = storage.numbers().next;
    return {
      ready: true, error, environment: k.environment, generatedAt: k.generated_at,
      issuer: { legal_name: k.issuer.legal_name ?? "", cnpj: k.issuer.cnpj ?? "", state: k.issuer.state ?? "" },
      series: Object.fromEntries(Object.entries(k.series).map(([m, s]) => [m, { series: s.series, next_number: next[m] ?? s.next_number }])),
      certificateValidUntil: k.certificate?.valid_until ?? null,
    };
  }

  /** Baixa o kit de novo (abertura do PDV, de tempos em tempos e pelo botão nas configurações). */
  async function refreshKit(): Promise<FiscalKitInfo> {
    const storeId = deps.storeId();
    if (!storeId) return kitInfo("Sem filial escolhida.");
    const response = await server.get("/pdv/fiscal-kit/", { installation_id: deps.installationId() }).catch(() => ({ ok: false, status: 0, data: null }));
    if (!response.ok) {
      const data = response.data as { error?: { message?: string }; detail?: string } | null;
      return kitInfo(response.status === 0 ? "Servidor fora do ar: usando o kit guardado." : data?.error?.message ?? data?.detail ?? `Erro ${response.status}`);
    }
    const fresh = { ...(response.data as Kit), storeId };
    storage.saveKit(fresh);
    // O número local nunca anda para trás; série nova (terminal recadastrado) recomeça pela do servidor.
    const state = storage.numbers();
    for (const [model, s] of Object.entries(fresh.series)) {
      if (state.series[model] !== s.series) {
        state.series[model] = s.series;
        state.next[model] = s.next_number;
      } else state.next[model] = Math.max(state.next[model] ?? 1, s.next_number);
    }
    storage.saveNumbers(state);
    return kitInfo();
  }

  function reserve(saleRef: string, model: string, k: Kit) {
    const state = storage.numbers();
    const key = `${model}:${saleRef}`;
    const series = state.series[model] ?? k.series[model]!.series;
    const kept = state.bySale[key];
    if (kept && kept.series === series) return kept;
    const number = Math.max(state.next[model] ?? 1, k.series[model]?.next_number ?? 1);
    state.series[model] = series;
    state.next[model] = number + 1;
    state.bySale[key] = { series, number };
    storage.saveNumbers(state);
    return state.bySale[key]!;
  }

  const localInvoices = () => storage.invoices();
  function saveInvoice(invoice: LocalInvoice) {
    const limit = Date.now() - KEEP_DAYS * 86_400_000;
    const others = storage.invoices().filter((i) => i.key !== invoice.key && (!i.synced || Date.parse(i.issued_at) > limit));
    storage.saveInvoices([invoice, ...others]);
  }
  const invoicesFor = (saleRef?: string) => localInvoices().filter((i) => !saleRef || i.saleRef === saleRef || i.saleId === saleRef);

  /** Contexto de cada chamada: os dados da emissão (UF, ambiente, modelo, CNPJ, fuso) vão SEMPRE na
   *  chamada — o comunicador local guarda só os segredos (A1 + CSC por CNPJ) e recusa a emissão sem eles
   *  (`dados_do_emitente_ausentes`). Sem certificado e CSC aqui (local: os guardados; nuvem: o backend
   *  troca o contexto inteiro pelo dos dados fiscais da filial). Conferido antes de sair: ambiente
   *  vazio no comunicador viraria homologação sem ninguém perceber. */
  function context(k: Kit, model: string, reference: string) {
    const uf = String(k.issuer.state ?? "").trim().toUpperCase();
    const ambiente = String(k.environment ?? "").trim();
    if (!/^[A-Z]{2}$/.test(uf)) throw new Error("O kit fiscal está sem a UF do emitente: confira os dados fiscais da filial e baixe o kit de novo.");
    if (ambiente !== "1" && ambiente !== "2") throw new Error("O kit fiscal está sem o ambiente (produção/homologação): baixe o kit de novo.");
    if (model !== "65" && model !== "55") throw new Error(`Modelo de nota inválido: ${model}.`);
    return { referencia: reference, modelo: model, ambiente, uf, cnpj: digits(k.issuer.cnpj), fuso: tzOffset() };
  }
  const transport = deps.transport;
  const acbr = (path: string, body: Record<string, unknown>) => transport.call(path, body);

  /** Comunicador local: o emitente desta filial está guardado nele? `undefined` = não dá para saber
   *  (o comunicador é de outro PC da loja: `/v1/config/*` só responde à própria máquina). */
  async function emitterStored(k: Kit) {
    const answer = await acbr("/v1/config/ler", {});
    if (answer.status === 403) return undefined;
    if (!answer.trusted) return null;
    const emitters = (answer.data.emitentes ?? []) as { cnpj?: string; certificado?: { vence_em?: string; vencido?: boolean } }[];
    return emitters.find((e) => digits(e.cnpj) === digits(k.issuer.cnpj)) ?? null;
  }

  async function health(): Promise<{ ok: boolean; message: string }> {
    try {
      const body = await transport.health();
      const where = transport.kind === "cloud" ? "Comunicador fiscal (nuvem)" : "Comunicador Fiscal";
      if (!body.ok) return { ok: false, message: body.message ?? `${where} fora do ar.` };
      if (transport.kind === "local" && body.modo === "nuvem") {
        return { ok: false, message: "Este endereço é um comunicador em modo NUVEM. O PDV desktop usa o Comunicador Fiscal desktop (modo local) deste PC." };
      }
      const k = kit();
      if (!k) return { ok: true, message: `${where} no ar (${body.motor ?? "?"}). Falta baixar o kit fiscal.` };
      if (transport.kind === "local") {
        const stored = await emitterStored(k);
        if (stored === null) {
          return { ok: false, message: `Comunicador no ar, mas sem o emitente ${k.issuer.legal_name || k.issuer.cnpj}. Cadastre-o na tela Emitente do Comunicador Fiscal (ou "Gravar certificado no comunicador").` };
        }
        if (stored?.certificado?.vencido) return { ok: false, message: "O certificado A1 guardado no comunicador está vencido." };
        // Trocaram o certificado no cadastro da filial: o comunicador ainda tem o antigo.
        const until = k.certificate?.valid_until ? new Date(k.certificate.valid_until) : null;
        const serverUntil = until && !Number.isNaN(until.getTime()) ? until.toISOString().slice(0, 10) : ""; // UTC, como o comunicador
        const storedUntil = String(stored?.certificado?.vence_em ?? "").slice(0, 10);
        if (serverUntil && storedUntil && serverUntil !== storedUntil) {
          return { ok: false, message: `O certificado da filial mudou (vence ${serverUntil.split("-").reverse().join("/")}), mas o comunicador tem o antigo: use "Gravar certificado no comunicador".` };
        }
      }
      const status = await acbr("/v1/status-servico", context(k, "65", "status"));
      if (!status.trusted || status.data.erro) return { ok: false, message: String(status.data.mensagem ?? status.data.erro) };
      return { ok: true, message: `${where} no ar${body.simulador ? " (SIMULADOR)" : ""}. SEFAZ: ${status.data.online ? "online" : "fora do ar"} — ${status.data.cstat ?? ""} ${status.data.motivo ?? ""}`.trim() };
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : String(error) };
    }
  }

  /** Comunicador local: grava nele o certificado A1 e o CSC da filial (só quem tem `fiscal.manage`,
   *  e só do próprio PC do comunicador). Na nuvem não há o que gravar: o backend manda a cada nota. */
  async function storeEmitter(): Promise<{ ok: boolean; message: string }> {
    if (transport.kind === "cloud") return { ok: true, message: "Na nuvem o certificado fica no servidor e vai em cada nota: nada a gravar." };
    const response = await server.get("/pdv/fiscal-emitter/");
    if (!response.ok) {
      const data = response.data as { error?: { message?: string }; detail?: string } | null;
      return { ok: false, message: data?.error?.message ?? data?.detail ?? `Erro ${response.status}` };
    }
    const emitter = response.data as Record<string, unknown>;
    // O comunicador guarda só os segredos, pelo CNPJ; UF, ambiente e modelo vão em cada emissão.
    const answer = await acbr("/v1/config/emitente", { cnpj: emitter.cnpj, certificado: emitter.certificado, csc: emitter.csc });
    if (answer.status === 403) return { ok: false, message: "O comunicador só aceita configuração do próprio computador dele: grave o emitente lá (tela Emitente)." };
    if (!answer.trusted || answer.data.erro) return { ok: false, message: String(answer.data.mensagem ?? answer.data.motivo ?? answer.data.erro) };
    return { ok: true, message: "Certificado e CSC gravados no comunicador (cifrados lá). Este PDV não guarda o certificado." };
  }

  async function emit(req: EmitRequest, options: EmitOptions): Promise<EmitResult> {
    const k = kit();
    if (!k) return { ok: false, error: "Kit fiscal não baixado: abra o PDV com o servidor no ar uma vez (Configurações → Nota fiscal)." };
    if (!k.series[req.model]) return { ok: false, error: `O kit não tem série para o modelo ${req.model}.` };
    const sale = req.sale as SaleLike;
    const done = invoicesFor(req.saleRef).find((i) => i.document_model === req.model && (i.status === "authorized" || i.status === "contingency"));
    if (done) return { ok: true, invoice: done };
    try {
      const rows = lines(sale, k);
      const t = totals(rows);
      if (Math.abs(t.total - num(sale.total)) > 0.009) throw new Error(`O total da nota (${fmt(t.total)}) não bate com o da venda (${sale.total}).`);
      const pays = payments(sale);
      const recipient = recipientOf(sale);
      if (req.model === "55" && !recipient) throw new Error("A NF-e precisa do CPF/CNPJ do cliente.");
      const { series, number } = reserve(req.saleRef, req.model, k);
      const previous = invoicesFor(req.saleRef).find((i) => i.document_model === req.model && i.number === number);
      const random = crypto.getRandomValues(new Uint32Array(1))[0]! % 100_000_000;
      const cNF = String((previous?.register.cNF as string) ?? String(random).padStart(8, "0"));
      const issuedAt = new Date();
      const change = num(sale.change_amount);
      const reference = `${req.saleRef}:${req.model}:${number}`;
      const ini = (tpEmis: "1" | "9") => buildIni({ k, model: req.model, series, number, cNF, issuedAt, tpEmis, rows, pays, change, recipient });

      let tpEmis: "1" | "9" = "1";
      let answer = await acbr("/v1/nfe/emitir", { ...context(k, req.model, reference), ini: ini("1"), tp_emis: "1" });
      if (answer.trusted && answer.data.erro === "sem_comunicacao" && req.model === "65" && options.contingency && k.offline_contingency) {
        tpEmis = "9";
        answer = await acbr("/v1/nfe/emitir", { ...context(k, req.model, reference), ini: ini("9"), tp_emis: "9" });
      }
      const result = answer.data;
      const local = req.saleRef.startsWith("off:");
      const invoice: LocalInvoice = {
        key: reference, saleRef: req.saleRef, saleId: local ? "" : req.saleRef,
        document_model: req.model, series, number, environment: k.environment, emission_type: tpEmis,
        status: statusOf(result), access_key: digits(result.chave), protocol: String(result.protocolo ?? ""),
        qrcode: String(result.qrcode ?? ""), message: messageOf(result), issued_at: issuedAt.toISOString(),
        xml: String(result.xml ?? ""), synced: false,
        register: {
          document_model: req.model, series, number, environment: k.environment, emission_type: tpEmis,
          issued_at: issuedAt.toISOString(), cNF, reference, recipient, issuer: k.issuer,
          totals: { products: fmt(t.products), discount: fmt(t.discount), other: fmt(t.other), approx: fmt(t.approx), total: fmt(t.total) },
          items: rows.map(({ v_prod: _p, v_desc: _d, v_outro: _o, base: _b, ...row }) => ({ ...row, approx: fmt(row.approx as number) })),
          result: pickResult(result),
        },
        danfe: {
          issuer: k.issuer, recipient, number, series, model: req.model, environment: k.environment, issued_at: issuedAt.toISOString(),
          items: rows.map((r) => ({ code: r.code, description: r.description, quantity: r.quantity, unit: r.unit, unit_price: r.unit_price, total: fmt(r.v_prod) })),
          totals: t, payments: pays.map((p) => ({ name: p.name, amount: fmt(p.amount) })), change: fmt(change),
          portal_url: k.portal_url, sale_number: local ? `OFF-${sale.number}` : sale.number,
        },
      };
      saveInvoice(invoice);
      const ok = invoice.status === "authorized" || invoice.status === "contingency";
      if (invoice.saleId) void registerInvoice(invoice); // servidor fora: tenta de novo depois
      return ok ? { ok, invoice } : { ok: false, invoice, error: invoice.message || "A nota não foi autorizada." };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  }

  /** Grava a nota no servidor (venda que já existe lá). false = tentar depois. */
  async function registerInvoice(invoice: LocalInvoice): Promise<boolean> {
    if (!invoice.saleId) return false;
    const response = await server.post(`/sales/${invoice.saleId}/invoices/register/`, invoice.register).catch(() => ({ ok: false, status: 0, data: null }));
    const final = response.status >= 400 && response.status < 500 && ![401, 408, 429].includes(response.status);
    if (response.ok || final) {
      // A resposta é a venda com as notas: guarda o id da nota no servidor (DANFE de lá).
      const rows = ((response.data as { invoices?: Record<string, unknown>[] } | null)?.invoices ?? []);
      const found = rows.find((r) => Number(r.number) === invoice.number && Number(r.series) === invoice.series
        && String(r.document_model ?? invoice.document_model) === invoice.document_model);
      saveInvoice({
        ...invoice, synced: true, server_invoice_id: found ? String(found.id) : invoice.server_invoice_id,
        message: response.ok ? invoice.message : `Servidor recusou: ${JSON.stringify(response.data).slice(0, 200)}`,
      });
      return response.ok;
    }
    return false;
  }

  /** Contingência: transmite à SEFAZ quando a internet volta; depois avisa o servidor. */
  async function transmitPending() {
    const k = kit();
    if (!k) return;
    for (const invoice of localInvoices().filter((i) => i.status === "contingency" && i.xml)) {
      try {
        const answer = await acbr("/v1/nfe/transmitir", { ...context(k, invoice.document_model, invoice.key), xml: invoice.xml });
        if (!answer.trusted || answer.data.erro === "sem_comunicacao") return; // SEFAZ ainda fora
        const status = statusOf(answer.data);
        if (status === "error") continue;
        const next: LocalInvoice = {
          ...invoice, status, protocol: String(answer.data.protocolo ?? invoice.protocol), message: messageOf(answer.data),
          xml: String(answer.data.xml ?? invoice.xml), synced: false,
          register: { ...invoice.register, result: { ...pickResult(answer.data), chave: answer.data.chave ?? invoice.access_key } },
        };
        saveInvoice(next);
        if (next.saleId) await registerInvoice(next);
      } catch (error) {
        if (error instanceof CommunicatorUnavailable) return; // comunicador fora: próximo ciclo
        return;
      }
    }
  }

  /** Nota de venda que ainda não estava no servidor: guarda o id dela e registra as pendentes. */
  async function syncPending() {
    for (const invoice of localInvoices().filter((i) => !i.synced && i.saleId)) await registerInvoice(invoice);
  }

  /** Venda local enviada: a nota dela passa a apontar para a venda do servidor. */
  function linkInvoices(saleRef: string, saleId: string) {
    for (const invoice of localInvoices().filter((i) => i.saleRef === saleRef)) saveInvoice({ ...invoice, saleId, synced: true });
  }

  return {
    kitInfo: () => kitInfo(), refreshKit, health, storeEmitter, emit, registerInvoice, transmitPending, syncPending, linkInvoices,
    invoicesFor, localInvoices, saveInvoice, cents,
  };
}

export type FiscalEngine = ReturnType<typeof createFiscal>;
