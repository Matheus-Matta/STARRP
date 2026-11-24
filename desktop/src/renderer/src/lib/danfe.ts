/**
 * DANFE da nota para imprimir — NFC-e na bobina (layout do DANFE NFC-e) e NF-e em A4 (resumido).
 *
 * Vem de dois lugares, no mesmo formato (`DanfeData`):
 * - a nota emitida por ESTE PDV (`LocalInvoice.danfe`): imprime sem o servidor, inclusive em
 *   contingência offline (com o aviso obrigatório);
 * - a nota de outro terminal: `GET /sales/{id}/invoices/{nota}/danfe/` (`fromServerDanfe`).
 * O QR Code é gerado aqui (biblioteca `qrcode`), então não depende de rede.
 */
import QRCode from "qrcode";

import type { LocalInvoice } from "../../../shared/ipc";
import { dateTime } from "./format";

const brl = (v: unknown) => Number(v ?? 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export type DanfeData = {
  model: "65" | "55";
  number: number | string;
  series: number | string;
  environment: string;
  contingency: boolean;
  issued_at: string;
  access_key: string;
  protocol: string;
  authorized_at: string | null;
  qrcode: string;
  consult_url: string;
  issuer: Record<string, string>;
  recipient: { document: string; name: string } | null;
  items: { code: string; description: string; quantity: string; unit: string; unit_price: string; total: string }[];
  totals: { products: number; discount: number; other: number; approx: number; total: number };
  payments: { name: string; amount: string }[];
  change: string;
  sale_number?: number | string;
};

const esc = (value: unknown) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const digits = (v: unknown) => String(v ?? "").replace(/\D/g, "");
const cnpj = (v: unknown) => digits(v).replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
const doc = (v: unknown) => {
  const d = digits(v);
  return d.length === 11 ? d.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, "$1.$2.$3-$4") : cnpj(d);
};
const keyBlocks = (key: string) => digits(key).replace(/(\d{4})(?=\d)/g, "$1 ");
const qty = (v: string) => Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 3 });

export function fromLocal(invoice: LocalInvoice): DanfeData {
  const d = invoice.danfe as Record<string, unknown>;
  return {
    model: invoice.document_model, number: invoice.number, series: invoice.series, environment: invoice.environment,
    contingency: invoice.emission_type === "9", issued_at: invoice.issued_at, access_key: invoice.access_key,
    protocol: invoice.protocol, authorized_at: invoice.status === "authorized" ? invoice.issued_at : null,
    qrcode: invoice.qrcode, consult_url: String(d.portal_url ?? ""), issuer: d.issuer as Record<string, string>,
    recipient: (d.recipient as DanfeData["recipient"]) ?? null, items: d.items as DanfeData["items"],
    totals: d.totals as DanfeData["totals"],
    payments: d.payments as DanfeData["payments"], change: String(d.change ?? "0"), sale_number: d.sale_number as number,
  };
}

/** A resposta de `/sales/{id}/invoices/{nota}/danfe/` no formato do DANFE daqui. */
export function fromServerDanfe(data: Record<string, unknown>): DanfeData {
  const issuer = (data.issuer ?? {}) as Record<string, string>;
  const recipient = data.recipient as { name?: string; document?: string } | null;
  const items = ((data.items ?? []) as Record<string, string | undefined>[]).map((i) => ({
    code: i.code ?? "", description: i.description ?? "", quantity: i.quantity ?? "0", unit: i.unit ?? "UN", unit_price: i.unit_price ?? "0",
    total: String(Number(i.quantity) * Number(i.unit_price)),
  }));
  const tax = (data.tax_totals ?? {}) as Record<string, string>;
  return {
    model: data.document_model === "55" ? "55" : "65", number: String(data.number ?? ""), series: String(data.series ?? ""),
    environment: String(data.environment ?? "2"), contingency: Boolean(data.contingency), issued_at: String(data.issued_at ?? ""),
    access_key: String(data.access_key ?? ""), protocol: String(data.protocol ?? ""), authorized_at: (data.authorized_at as string) ?? null,
    qrcode: String(data.qr_code_data || data.consult_url || ""), consult_url: String(issuer.portal_url ?? data.consult_url ?? ""),
    issuer: { ...issuer, address_full: issuer.address ?? "" },
    recipient: recipient?.document || recipient?.name ? { document: recipient.document ?? "", name: recipient.name ?? "" } : null,
    items,
    totals: {
      products: Number(data.products_total ?? 0), discount: Number(data.discount_total ?? 0),
      other: Number(tax.other_expenses ?? data.freight_total ?? 0), approx: Number(data.approx_tax_total ?? 0), total: Number(data.total ?? 0),
    },
    payments: ((data.payments ?? []) as Record<string, string>[]).map((p) => ({ name: p.method_name ?? "", amount: p.amount ?? "0" })),
    change: String(data.change_amount ?? "0"), sale_number: data.sale_number as number,
  };
}

const issuerAddress = (i: Record<string, string>) => i.address_full || [
  [i.street, i.number].filter(Boolean).join(", "), i.district, i.city && `${i.city}/${i.state}`, i.zip_code,
].filter(Boolean).join(" - ");

const NFCE_CSS = `@page { size: 80mm auto; margin: 0 } * { box-sizing: border-box }
body { width: 100%; max-width: 80mm; margin: 0; padding: 3mm 3mm 6mm; font: 10.5px/1.3 Consolas, "Courier New", monospace; color: #000 }
.c { text-align: center } .r { text-align: right } .b { font-weight: 700 } .s { font-size: 9.5px }
hr { border: 0; border-top: 1px dashed #000; margin: 5px 0 } table { width: 100%; border-collapse: collapse }
td, th { vertical-align: top; padding: 1px 0; text-align: left } th { font-size: 9.5px } .qr { display: flex; justify-content: center; margin: 4px 0 }
.qr svg { width: 34mm; height: 34mm } .warn { border: 1px solid #000; padding: 3px; margin: 4px 0; text-align: center; font-weight: 700 }`;

async function qrSvg(text: string) {
  return text ? QRCode.toString(text, { type: "svg", margin: 0, errorCorrectionLevel: "M" }) : "";
}

export async function danfeHtml(d: DanfeData): Promise<string> {
  return d.model === "55" ? danfeA4(d) : danfeNfce(d);
}

async function danfeNfce(d: DanfeData) {
  const homolog = d.environment === "2";
  const rows = d.items.map((i, n) => `<tr><td colspan="4">${String(n + 1).padStart(3, "0")} ${esc(i.code)} ${esc(i.description)}</td></tr>
    <tr><td></td><td>${qty(i.quantity)} ${esc(i.unit)} x ${brl(i.unit_price)}</td><td></td><td class="r">${brl(i.total)}</td></tr>`).join("");
  const pays = d.payments.map((p) => `<tr><td>${esc(p.name)}</td><td class="r">${brl(p.amount)}</td></tr>`).join("");
  const qr = await qrSvg(d.qrcode);
  const body = `
    <div class="c b">${esc(d.issuer.legal_name)}</div>
    <div class="c s">CNPJ ${cnpj(d.issuer.cnpj)} &nbsp; IE ${esc(d.issuer.state_registration)}</div>
    <div class="c s">${esc(issuerAddress(d.issuer))}</div><hr>
    <div class="c b">DANFE NFC-e - Documento Auxiliar da Nota Fiscal de Consumidor Eletrônica</div>
    ${homolog ? `<div class="warn">EMITIDA EM AMBIENTE DE HOMOLOGAÇÃO - SEM VALOR FISCAL</div>` : ""}
    ${d.contingency ? `<div class="warn">EMITIDA EM CONTINGÊNCIA<br>Pendente de autorização</div>` : ""}
    <hr><table><tr><th>#</th><th>Descrição / Qtde x Unit.</th><th></th><th class="r">Total</th></tr>${rows}</table><hr>
    <table>
      <tr><td>Qtde. total de itens</td><td class="r">${d.items.length}</td></tr>
      <tr><td>Valor total R$</td><td class="r">${brl(d.totals.products)}</td></tr>
      ${d.totals.discount ? `<tr><td>Desconto R$</td><td class="r">- ${brl(d.totals.discount)}</td></tr>` : ""}
      ${d.totals.other ? `<tr><td>Outras despesas R$</td><td class="r">${brl(d.totals.other)}</td></tr>` : ""}
      <tr class="b"><td>Valor a pagar R$</td><td class="r">${brl(d.totals.total)}</td></tr>
      <tr><td class="b">FORMA DE PAGAMENTO</td><td class="r b">VALOR PAGO R$</td></tr>${pays}
      ${Number(d.change) ? `<tr><td>Troco R$</td><td class="r">${brl(d.change)}</td></tr>` : ""}
    </table><hr>
    <div class="c s">Consulte pela Chave de Acesso em<br>${esc(d.consult_url || "o portal da SEFAZ do seu estado")}</div>
    <div class="c b s">${keyBlocks(d.access_key)}</div><hr>
    <div class="c s">${d.recipient ? `CONSUMIDOR - ${d.recipient.document.length === 14 ? "CNPJ" : "CPF"} ${doc(d.recipient.document)}<br>${esc(d.recipient.name)}` : "CONSUMIDOR NÃO IDENTIFICADO"}</div><hr>
    <div class="c s b">NFC-e nº ${esc(d.number)} Série ${esc(d.series)} ${dateTime(d.issued_at)}</div>
    ${d.protocol ? `<div class="c s">Protocolo de autorização: ${esc(d.protocol)}<br>Data de autorização: ${dateTime(d.authorized_at ?? d.issued_at)}</div>` : ""}
    ${qr ? `<div class="qr">${qr}</div>` : ""}
    ${d.totals.approx ? `<div class="c s">Tributos totais incidentes (Lei Federal 12.741/2012): R$ ${brl(d.totals.approx)}</div>` : ""}
    ${d.sale_number ? `<div class="c s">Pedido ${esc(d.sale_number)}</div>` : ""}`;
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>NFC-e ${esc(d.number)}</title><style>${NFCE_CSS}</style></head><body>${body}</body></html>`;
}

async function danfeA4(d: DanfeData) {
  const homolog = d.environment === "2";
  const rows = d.items.map((i) => `<tr><td>${esc(i.code)}</td><td>${esc(i.description)}</td><td class="r">${qty(i.quantity)}</td>
    <td>${esc(i.unit)}</td><td class="r">${brl(i.unit_price)}</td><td class="r">${brl(i.total)}</td></tr>`).join("");
  const box = (label: string, value: string) => `<div class="box"><small>${label}</small><div>${value || "&nbsp;"}</div></div>`;
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>NF-e ${esc(d.number)}</title><style>
@page { size: A4; margin: 8mm } body { font: 10px/1.3 Arial, sans-serif; color: #000; margin: 0 }
.row { display: flex; gap: 0 } .box { border: 1px solid #000; padding: 2px 4px; flex: 1; margin: -1px 0 0 -1px }
.box small { display: block; font-size: 7px; text-transform: uppercase } h1 { font-size: 13px; margin: 0 }
table { width: 100%; border-collapse: collapse; margin-top: 4px } th, td { border: 1px solid #000; padding: 2px 3px; text-align: left }
th { font-size: 8px } .r { text-align: right } .warn { border: 2px solid #000; text-align: center; font-weight: 700; padding: 4px; margin: 4px 0 }
</style></head><body>
  <div class="row"><div class="box" style="flex:2"><h1>${esc(d.issuer.legal_name)}</h1>${esc(issuerAddress(d.issuer))}</div>
    <div class="box" style="text-align:center"><b>DANFE</b><br>Documento Auxiliar da Nota Fiscal Eletrônica<br>1 - SAÍDA<br>
      <b>Nº ${esc(d.number)} Série ${esc(d.series)}</b></div>
    <div class="box" style="flex:2"><small>Chave de acesso</small><b>${keyBlocks(d.access_key)}</b><br>
      Consulta em ${esc(d.consult_url || "www.nfe.fazenda.gov.br/portal")}</div></div>
  ${homolog ? `<div class="warn">EMITIDA EM AMBIENTE DE HOMOLOGAÇÃO - SEM VALOR FISCAL</div>` : ""}
  <div class="row">${box("Natureza da operação", "VENDA DE MERCADORIA")}${box("Protocolo de autorização", `${esc(d.protocol)} ${d.authorized_at ? dateTime(d.authorized_at) : ""}`)}</div>
  <div class="row">${box("Inscrição estadual", esc(d.issuer.state_registration))}${box("CNPJ", cnpj(d.issuer.cnpj))}</div>
  <div class="row">${box("Destinatário", esc(d.recipient?.name ?? ""))}${box("CNPJ/CPF", doc(d.recipient?.document ?? ""))}${box("Data de emissão", dateTime(d.issued_at))}</div>
  <div class="row">${box("Valor dos produtos", brl(d.totals.products))}${box("Desconto", brl(d.totals.discount))}${box("Outras despesas", brl(d.totals.other))}${box("Tributos aprox.", brl(d.totals.approx))}${box("Valor total da nota", `<b>${brl(d.totals.total)}</b>`)}</div>
  <table><tr><th>Código</th><th>Descrição</th><th class="r">Qtde</th><th>Un</th><th class="r">Unit.</th><th class="r">Total</th></tr>${rows}</table>
  <div class="row" style="margin-top:6px">${box("Pagamento", d.payments.map((p) => `${esc(p.name)} ${brl(p.amount)}`).join(" · "))}</div>
</body></html>`;
}
