/**
 * A venda vira a nota: linhas fiscais (perfil, NCM, rateio de desconto/frete, impostos), totais,
 * pagamentos (tPag) e o INI que a ACBrLib assina. Mesmo código no desktop e na web.
 */
import type { Kit, LocalInvoice } from "./types";

export const digits = (v: unknown) => String(v ?? "").replace(/\D/g, "");
export const cents = (v: number) => Math.round(v * 100) / 100;
export const num = (v: unknown) => Number(v ?? 0) || 0;
export const fmt = (v: number, places = 2) => v.toFixed(places);
/** Quantidade × preço em inteiros (quatro casas cada), metade para cima: o mesmo arredondamento do servidor. */
export const lineTotal = (quantity: number, price: number) =>
  Number((BigInt(Math.round(quantity * 10_000)) * BigInt(Math.round(price * 10_000)) + 500_000n) / 1_000_000n) / 100;
const clean = (v: unknown) => String(v).replace(/[\r\n]+/g, " ").trim();
const SEM_GTIN = "SEM GTIN";
const HOMOLOG_ITEM = "NOTA FISCAL EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL";
const HOMOLOG_RECIPIENT = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL";
/** tPag por forma de pagamento (o mesmo `PaymentMethod.FISCAL_CODES` do backend). */
export const TPAG: Record<string, string> = {
  cash: "01", credit_card: "03", debit_card: "04", store_credit: "05", voucher: "10", bank_slip: "15", pix: "17",
  installment_plan: "05", other: "99",
};

export type SaleLike = {
  id?: string; number?: number | string; items?: Record<string, unknown>[]; payments?: Record<string, unknown>[];
  discount?: string; coupon_discount?: string; freight?: string; total?: string; change_amount?: string;
  customer_document?: string; customer_name?: string;
};

export type Line = Record<string, string | number | null> & { n: number; base: number; v_prod: number; v_desc: number; v_outro: number; approx: number };

function allocate(total: number, weights: number[]) {
  const sum = weights.reduce((a, b) => a + b, 0) || 1;
  const parts = weights.map((w) => cents((total * w) / sum));
  if (parts.length) parts[parts.length - 1] = cents(parts[parts.length - 1]! + cents(total) - cents(parts.reduce((a, b) => a + b, 0)));
  return parts;
}

export function lines(sale: SaleLike, k: Kit): Line[] {
  const items = (sale.items ?? []).filter((i) => (i.status ?? "active") === "active");
  if (!items.length) throw new Error("A venda não tem itens para a nota.");
  const services = items.filter((i) => k.variants[String(i.variant)]?.type === "service").map((i) => i.description);
  if (services.length) throw new Error(`Serviço não entra na nota de mercadoria: ${services.join(", ")}.`);
  const weights = items.map((i) => num(i.total));
  const saleDiscount = allocate(num(sale.discount) + num(sale.coupon_discount), weights);
  const others = allocate(num(sale.freight), weights);
  const missing: string[] = [];
  const out = items.map((item, index) => {
    const fiscal = k.variants[String(item.variant)];
    const profile = k.profiles[fiscal?.profile ?? ""] ?? k.profiles[k.default_profile ?? ""];
    const ncm = fiscal?.ncm || profile?.ncm || "";
    if (!fiscal || !profile || !ncm) missing.push(String(item.description));
    const quantity = num(item.quantity);
    const unitPrice = num(item.unit_price);
    const vProd = lineTotal(quantity, unitPrice);
    const vDesc = cents(Math.max(vProd - num(item.total), 0) + saleDiscount[index]!);
    const vOutro = others[index]!;
    const base = cents(vProd - vDesc + vOutro);
    const rate = (key: string) => num(profile?.[key]);
    const icmsRate = k.simple ? 0 : rate("icms_rate");
    return {
      n: index + 1, sale_item: String(item.id ?? ""), variant: String(item.variant ?? ""),
      code: String(item.sku || item.variant || "").slice(0, 60), barcode: fiscal?.barcode ?? "",
      description: String(item.description ?? "").slice(0, 120), ncm, cest: fiscal?.cest || profile?.cest || "",
      cfop: profile?.cfop || "5102", csosn: k.simple ? profile?.csosn || "102" : "", cst_icms: k.simple ? "" : profile?.cst_icms || "00",
      origin: fiscal?.origin || "0", unit: String(item.unit || "UN").slice(0, 6), quantity: fmt(quantity, 4),
      unit_price: fmt(unitPrice, 4), v_prod: vProd, v_desc: vDesc, v_outro: vOutro, base, discount: fmt(vDesc), total: fmt(base),
      icms_rate: fmt(icmsRate), icms_base: fmt(icmsRate ? base : 0), icms_value: fmt(cents((base * icmsRate) / 100)),
      pis_cst: profile?.pis_cst || "49", pis_rate: fmt(rate("pis_rate")), pis_value: fmt(cents((base * rate("pis_rate")) / 100)),
      cofins_cst: profile?.cofins_cst || "49", cofins_rate: fmt(rate("cofins_rate")),
      cofins_value: fmt(cents((base * rate("cofins_rate")) / 100)), approx: cents((base * rate("approx_tax_rate")) / 100),
    } satisfies Line;
  });
  if (missing.length) throw new Error(`Sem perfil fiscal ou NCM: ${missing.join(", ")}. Ajuste o cadastro e baixe o kit de novo.`);
  return out;
}

export function totals(rows: Line[]) {
  const sum = (key: "v_prod" | "v_desc" | "v_outro" | "approx") => cents(rows.reduce((a, r) => a + r[key], 0));
  const products = sum("v_prod"), discount = sum("v_desc"), other = sum("v_outro");
  return { products, discount, other, approx: sum("approx"), total: cents(products - discount + other) };
}

export function payments(sale: SaleLike) {
  const rows = (sale.payments ?? []).filter((p) => (p.status ?? "approved") === "approved").map((p) => {
    const kind = String(p.method_kind ?? "other");
    const amount = cents(num(p.amount) + (kind === "cash" ? num(p.change_amount) : 0));
    const code = TPAG[kind] ?? "99";
    return { tPag: code, vPag: fmt(amount), ...(code === "03" || code === "04" ? { tpIntegra: "2" } : {}),
             ...(code === "99" ? { xPag: String(p.method_name ?? "Outros").slice(0, 60) } : {}), name: String(p.method_name ?? ""), amount };
  });
  if (!rows.length) throw new Error("A venda não tem pagamento aprovado para a nota.");
  return rows;
}

const dateIni = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

export function tzOffset() {
  const minutes = -new Date().getTimezoneOffset();
  const sign = minutes >= 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  return `${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

export function buildIni(o: {
  k: Kit; model: string; series: number; number: number; cNF: string; issuedAt: Date; tpEmis: "1" | "9";
  rows: Line[]; pays: ReturnType<typeof payments>; change: number; recipient: { document: string; name: string } | null;
}) {
  const out: string[] = [];
  const section = (name: string, fields: Record<string, unknown>) => {
    out.push(`[${name}]`);
    for (const [key, value] of Object.entries(fields)) if (value !== undefined && value !== null && value !== "") out.push(`${key}=${clean(value)}`);
    out.push("");
  };
  const nfce = o.model === "65";
  const homolog = o.k.environment === "2";
  const issuer = o.k.issuer;
  section("infNFe", { versao: "4.00" });
  section("Identificacao", {
    cNF: o.cNF, natOp: "VENDA DE MERCADORIA", mod: o.model, serie: o.series, nNF: o.number, dhEmi: dateIni(o.issuedAt),
    tpNF: "1", idDest: "1", tpImp: nfce ? "4" : "1", tpEmis: o.tpEmis, tpAmb: o.k.environment, finNFe: "1", indFinal: "1",
    indPres: "1", procEmi: "0", verProc: "Starrp PDV",
    ...(o.tpEmis === "9" ? { dhCont: dateIni(new Date()), xJust: "Sem comunicacao com a SEFAZ no momento da venda" } : {}),
  });
  section("Emitente", {
    CNPJCPF: digits(issuer.cnpj), xNome: issuer.legal_name, xFant: issuer.trade_name, IE: digits(issuer.state_registration),
    CRT: issuer.crt, xLgr: issuer.street, nro: issuer.number || "SN", xBairro: issuer.district, cMun: issuer.city_ibge,
    xMun: issuer.city, UF: issuer.state, CEP: digits(issuer.zip_code),
  });
  if (o.recipient) section("Destinatario", { CNPJCPF: o.recipient.document, xNome: homolog ? HOMOLOG_RECIPIENT : o.recipient.name, indIEDest: "9" });
  for (const r of o.rows) {
    const n = String(r.n).padStart(3, "0");
    section(`Produto${n}`, {
      cProd: r.code, cEAN: r.barcode || SEM_GTIN, xProd: homolog && nfce && r.n === 1 ? HOMOLOG_ITEM : r.description,
      NCM: r.ncm, CEST: r.cest, CFOP: r.cfop, uCom: r.unit, qCom: r.quantity, vUnCom: r.unit_price, vProd: fmt(r.v_prod),
      cEANTrib: r.barcode || SEM_GTIN, uTrib: r.unit, qTrib: r.quantity, vUnTrib: r.unit_price,
      vDesc: r.v_desc ? fmt(r.v_desc) : "", vOutro: r.v_outro ? fmt(r.v_outro) : "", indTot: "1", vTotTrib: fmt(r.approx),
    });
    const icms: Record<string, unknown> = { orig: r.origin, ...(o.k.simple ? { CSOSN: r.csosn } : { CST: r.cst_icms }) };
    if (num(r.icms_rate)) Object.assign(icms, { vBC: fmt(r.base), pICMS: r.icms_rate, vICMS: r.icms_value });
    section(`ICMS${n}`, icms);
    for (const [tax, rateKey, valueKey] of [["pis", "pPIS", "vPIS"], ["cofins", "pCOFINS", "vCOFINS"]] as const) {
      const fields: Record<string, unknown> = { CST: r[`${tax}_cst`], [valueKey]: r[`${tax}_value`] };
      if (num(r[`${tax}_rate`])) Object.assign(fields, { vBC: fmt(r.base), [rateKey]: r[`${tax}_rate`] });
      section(`${tax.toUpperCase()}${n}`, fields);
    }
  }
  const t = totals(o.rows);
  section("Total", { vProd: fmt(t.products), vDesc: fmt(t.discount), vOutro: fmt(t.other), vNF: fmt(t.total), vTotTrib: fmt(t.approx) });
  section("Transportador", { modFrete: "9" });
  o.pays.forEach((p, index) => {
    const { name: _n, amount: _a, ...fields } = p;
    section(`pag${String(index + 1).padStart(3, "0")}`, { ...fields, ...(index === o.pays.length - 1 && o.change ? { vTroco: fmt(o.change) } : {}) });
  });
  if (o.change) section("pag", { vTroco: fmt(o.change) });
  return out.join("\n");
}

/** Chave de acesso (44 dígitos) da nota em emissão NORMAL: para consultar na SEFAZ uma nota de resposta perdida. */
export function accessKey(o: { issuer: Record<string, string>; model: string; series: number; number: number; cNF: string; issuedAt: Date }) {
  const pad = (v: string | number, size: number) => String(v).padStart(size, "0");
  const uf = digits(o.issuer.city_ibge).slice(0, 2);
  const month = `${pad(o.issuedAt.getFullYear() % 100, 2)}${pad(o.issuedAt.getMonth() + 1, 2)}`;
  const body = uf + month + pad(digits(o.issuer.cnpj), 14) + o.model + pad(o.series, 3) + pad(o.number, 9) + "1" + pad(o.cNF, 8);
  if (body.length !== 43) return null; // cadastro sem o IBGE da cidade: não dá para montar
  const sum = [...body].reverse().reduce((total, digit, index) => total + Number(digit) * (2 + (index % 8)), 0);
  const rest = 11 - (sum % 11);
  return body + (rest >= 10 ? 0 : rest);
}

export function recipientOf(sale: SaleLike) {
  const document = digits(sale.customer_document);
  if (document.length !== 11 && document.length !== 14) return null;
  return { document, name: String(sale.customer_name || "CONSUMIDOR").slice(0, 60) };
}

export function statusOf(result: Record<string, unknown>): LocalInvoice["status"] {
  const s = String(result.situacao ?? "");
  if (s === "autorizada") return "authorized";
  if (s === "contingencia") return "contingency";
  if (s === "processando") return "processing";
  if (s === "rejeitada" || s === "denegada") return "rejected";
  return "error";
}

export const messageOf = (r: Record<string, unknown>) => [r.cstat, r.motivo ?? r.mensagem].filter(Boolean).join(" ").trim();

export const pickResult = (r: Record<string, unknown>) =>
  Object.fromEntries(["situacao", "cstat", "motivo", "erro", "mensagem", "chave", "protocolo", "qrcode", "digest_value", "recebido_em", "xml"]
    .filter((k) => r[k] !== undefined).map((k) => [k, r[k]]));
