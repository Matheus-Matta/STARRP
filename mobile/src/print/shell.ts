/**
 * Cópia de `frontend/src/print/PrintShell.vue` + `PrintTable.vue` + `PrintMeta.vue` em HTML puro: a MESMA folha
 * (A4 retrato, A4 deitado ou bobina 80 mm, com o `@page` de cada um), o cabeçalho com a filial (nome, razão social,
 * CNPJ, endereço, telefone) e o logo da conta, o rodapé "Emitido em … por … · Starrp" e "Página X de Y",
 * a grade de dados do topo e as tabelas (cabeçalho cinza, zebra, totais; na bobina vira lista).
 * O app transforma o HTML em PDF (compartilhar) ou manda para a impressão do sistema.
 */
import { date, dateTime, money, percent, quantity } from "@front/utils/format";

import { api, mediaUrl } from "@/api/client";
import type { Me } from "@/api/types";

import { STARRP_LOGO } from "./brandLogo";

export type PrintFormat = "a4" | "a4-landscape" | "80mm";
export const FORMAT_LABELS: Record<PrintFormat, string> = { a4: "Folha A4", "a4-landscape": "A4 deitado", "80mm": "Bobina 80 mm" };

export const esc = (v: unknown) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const PAGE: Record<PrintFormat, string> = {
  a4: "size: A4 portrait; margin: 14mm 12mm 16mm;",
  "a4-landscape": "size: A4 landscape; margin: 12mm 12mm 14mm;",
  "80mm": "size: 80mm auto; margin: 3mm 3mm 6mm;",
};

/** CSS da folha (PrintShell + PrintMeta), igual ao da retaguarda; o de cada documento vem junto (`extraCss`). */
const SHELL_CSS = `
* { box-sizing: border-box; }
html, body { margin: 0; background: #fff; color: #111; color-scheme: light; }
.print-root { font: 10pt/1.4 Arial, Helvetica, sans-serif; color: #111; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.print-root.fmt-80mm { font-size: 8.5pt; }
.doc-head { display: flex; justify-content: space-between; gap: 16px; padding-bottom: 8px; margin-bottom: 12px; border-bottom: 2px solid #111; align-items: flex-start; }
.doc-head .company { display: flex; flex-direction: column; font-size: 8.5pt; color: #444; }
.doc-head .company strong { font-size: 12pt; color: #111; }
.doc-head .doc-title { text-align: right; margin-left: auto; }
.doc-head h1 { margin: 0; font-size: 15pt; letter-spacing: -0.01em; color: #111; }
.doc-head p { margin: 2px 0 0; font-size: 9pt; color: #444; }
.doc-logo { width: 22mm; height: 22mm; object-fit: contain; flex-shrink: 0; }
.doc-head--thermal .doc-logo { order: -1; width: 16mm; height: 16mm; }
.doc-head--thermal .doc-title { margin-left: 0; }
.doc-head--thermal { flex-direction: column; align-items: center; text-align: center; gap: 4px; border-bottom: 1px dashed #111; }
.doc-head--thermal .company { align-items: center; }
.doc-head--thermal .company strong { font-size: 10.5pt; }
.doc-head--thermal .doc-title { text-align: center; }
.doc-head--thermal h1 { font-size: 10pt; text-transform: uppercase; }
.doc-body { display: flex; flex-direction: column; gap: 12px; }
.doc-foot { margin-top: 14px; padding-top: 6px; border-top: 1px solid #ccc; font-size: 7.5pt; color: #666; text-align: center; }
.doc-section h2 { margin: 0 0 6px; font-size: 10.5pt; text-transform: uppercase; letter-spacing: 0.04em; color: #111;
                  border-bottom: 1px solid #999; padding-bottom: 3px; }
.doc-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.doc-kpis > div { border: 1px solid #bbb; border-radius: 4px; padding: 6px 8px; }
.doc-kpis small { display: block; font-size: 7.5pt; color: #555; text-transform: uppercase; }
.doc-kpis b { font-size: 12pt; }
.doc-note { margin: 0; font-size: 8.5pt; color: #444; }
.doc-signatures { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr)); gap: 24px; margin-top: 28px; }
.doc-signatures div { border-top: 1px solid #111; padding-top: 4px; text-align: center; font-size: 8.5pt; }
.doc-total-box { margin-left: auto; min-width: 230px; border: 1.5px solid #111; border-radius: 4px; }
.doc-total-box div { display: flex; justify-content: space-between; padding: 4px 8px; border-bottom: 1px solid #ddd; }
.doc-total-box div:last-child { border-bottom: 0; font-size: 12pt; font-weight: 700; background: #f3f4f6; }
.neg { color: #b91c1c; }
.pt { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
.pt th { text-align: left; padding: 4px 6px; background: #f3f4f6; border-top: 1px solid #999; border-bottom: 1px solid #999;
         font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.03em; color: #333; }
.pt td { padding: 4px 6px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
.pt tbody tr:nth-child(even) td { background: #fafafa; }
.pt tfoot td { border-top: 1.5px solid #111; border-bottom: 0; font-weight: 700; background: #f3f4f6; }
.pt .r { text-align: right; white-space: nowrap; }
.pt-empty { margin: 0; padding: 8px; font-size: 8.5pt; color: #666; font-style: italic; }
.pt-thermal { list-style: none; margin: 0; padding: 0; }
.pt-thermal li { padding: 3px 0; border-bottom: 1px dotted #999; }
.pt-thermal__main { font-weight: 700; }
.pt-thermal__rest { display: flex; flex-wrap: wrap; gap: 0 8px; font-size: 7.5pt; }
.fmt-80mm .doc-kpis { grid-template-columns: 1fr 1fr; }
.fmt-80mm .doc-section h2 { font-size: 8.5pt; border-bottom: 1px dashed #111; }
.fmt-80mm .doc-total-box { min-width: 0; width: 100%; border: 0; border-radius: 0; border-top: 1px dashed #111; }
.fmt-80mm .doc-foot { border-top: 1px dashed #111; }
.pm { margin: 0; display: grid; border: 1px solid #bbb; border-radius: 4px; overflow: hidden; }
.pm > div { padding: 5px 8px; border-right: 1px solid #ddd; border-bottom: 1px solid #ddd; }
.pm dt { font-size: 7pt; text-transform: uppercase; letter-spacing: 0.04em; color: #555; }
.pm dd { margin: 1px 0 0; font-size: 9.5pt; font-weight: 600; color: #111; overflow-wrap: anywhere; }
.fmt-80mm .pm { grid-template-columns: 1fr !important; border: 0; }
.fmt-80mm .pm > div { display: flex; justify-content: space-between; gap: 6px; padding: 1px 0; border: 0; }
.fmt-80mm .pm dd { font-size: 8.5pt; text-align: right; }
.doc-section, .doc-kpis, .doc-total-box, .doc-signatures { break-inside: avoid; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
`;

/** Dados da filial do cabeçalho (o mesmo `/stores/<id>/` do PrintShell). */
export type Company = { name: string; legal: string; cnpj: string; address: string; phone: string };

export async function loadCompany(storeId: string | null | undefined, me: Me | null): Promise<Company> {
  let s: Record<string, string> = {};
  if (storeId && storeId !== "*") {
    try {
      s = await api.get<Record<string, string>>(`/stores/${storeId}/`);
    } catch { /* sem a filial: fica o nome da conta */ }
  }
  const cnpj = String(s.cnpj ?? "").replace(/\D/g, "");
  return {
    name: s.name || me?.account?.name || "Starrp",
    legal: s.legal_name && s.legal_name !== s.name ? s.legal_name : "",
    cnpj: cnpj.length === 14 ? cnpj.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5") : "",
    address: [[s.street, s.number].filter(Boolean).join(", "), s.district, [s.city, s.state].filter(Boolean).join(" - ")]
      .filter(Boolean).join(" · "),
    phone: s.phone || "",
  };
}

export type ShellInput = {
  title: string; subtitle?: string; format: PrintFormat; bare?: boolean; company: Company; logo?: string | null;
  user?: string; body: string; extraCss?: string;
};

/** A folha inteira (o que o PrintShell desenha), pronta para virar PDF ou ir para a impressora. */
export function shell({ title, subtitle, format, bare, company, logo, user, body, extraCss }: ShellInput) {
  const thermal = format === "80mm";
  const issued = new Date().toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  const page = `@page { ${PAGE[format]} ${thermal || bare ? "" : `
    @bottom-left { content: "${company.name.replace(/"/g, "")} · ${title.replace(/"/g, "")}"; font: 8pt Arial; color: #777; }
    @bottom-right { content: "Página " counter(page) " de " counter(pages); font: 8pt Arial; color: #777; }`} }`;
  // Logo da conta (Configurações da conta); sem ele, o do Starrp — igual ao PrintShell.
  const logoUrl = mediaUrl(logo) ?? STARRP_LOGO;
  const head = bare ? "" : `<header class="doc-head${thermal ? " doc-head--thermal" : ""}">
  <div class="company"><strong>${esc(company.name)}</strong>${company.legal ? `<span>${esc(company.legal)}</span>` : ""}${
    company.cnpj ? `<span>CNPJ ${esc(company.cnpj)}</span>` : ""}${company.address ? `<span>${esc(company.address)}</span>` : ""}${
    company.phone ? `<span>Tel. ${esc(company.phone)}</span>` : ""}</div>
  <div class="doc-title"><h1>${esc(title)}</h1>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>
  ${logoUrl ? `<img class="doc-logo" src="${esc(logoUrl)}" alt="">` : ""}
</header>`;
  // No A4 o rodapé vai na margem da página (com o número); este aparece na bobina e onde a margem não sai.
  const foot = bare ? "" : `<footer class="doc-foot">Emitido em ${esc(issued)} por ${esc(user ?? "—")} · Starrp</footer>`;
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>${page}${SHELL_CSS}${extraCss ?? ""}</style></head>
<body><div class="print-root fmt-${format}">${head}<main class="doc-body">${body}</main>${foot}</div></body></html>`;
}

/* ── PrintTable ────────────────────────────────────────────────────────── */

export type PCol = { key: string; label: string; type?: string; map?: Record<string, string> };
type PRow = Record<string, unknown>;

const numeric = (c: PCol) => ["money", "quantity", "percent"].includes(c.type ?? "");

export function show(c: PCol, v: unknown) {
  if (v === null || v === undefined || v === "") return "—";
  switch (c.type) {
    case "money": return money(v);
    case "quantity": return quantity(v);
    case "percent": return percent(v);
    case "date": return date(v);
    case "datetime": return dateTime(v);
    case "boolean": return v ? "Sim" : "Não";
    case "tag": return c.map?.[String(v)] ?? String(v);
    default: return String(v);
  }
}

export function printTable(columns: PCol[], rows: PRow[], opts: { totals?: PRow; empty?: string; thermal?: boolean } = {}) {
  if (!rows.length) return `<p class="pt-empty">${esc(opts.empty ?? "Nenhum registro.")}</p>`;
  const first = columns.find((c) => !numeric(c));
  if (opts.thermal && first) {
    return `<ul class="pt-thermal">${rows.map((row) => `<li><div class="pt-thermal__main">${esc(show(first, row[first.key]))}</div>
      <div class="pt-thermal__rest">${columns.filter((c) => c.key !== first.key)
        .map((c) => `<span>${esc(c.label)}: <b>${esc(show(c, row[c.key]))}</b></span>`).join("")}</div></li>`).join("")}</ul>`;
  }
  const cls = (c: PCol) => (numeric(c) ? ' class="r"' : "");
  const head = columns.map((c) => `<th${cls(c)}>${esc(c.label)}</th>`).join("");
  const body = rows.map((row) => `<tr>${columns.map((c) => `<td${cls(c)}>${esc(show(c, row[c.key]))}</td>`).join("")}</tr>`).join("");
  const totals = opts.totals
    ? `<tfoot><tr>${columns.map((c) => `<td${cls(c)}>${c.key in opts.totals! ? esc(show(c, opts.totals![c.key])) : ""}</td>`).join("")}</tr></tfoot>`
    : "";
  return `<table class="pt"><thead><tr>${head}</tr></thead><tbody>${body}</tbody>${totals}</table>`;
}

/* ── PrintMeta ─────────────────────────────────────────────────────────── */

export function printMeta(items: [string, unknown][], columns = 3) {
  return `<dl class="pm" style="grid-template-columns: repeat(${columns}, minmax(0, 1fr))">${items.map(([label, value]) =>
    `<div><dt>${esc(label)}</dt><dd>${esc(value === null || value === undefined || value === "" ? "—" : value)}</dd></div>`).join("")}</dl>`;
}

export const section = (title: string, inner: string, cls = "") => `<section class="doc-section ${cls}"><h2>${esc(title)}</h2>${inner}</section>`;
export const signatures = (labels: string[]) => `<div class="doc-signatures">${labels.map((l) => `<div>${esc(l)}</div>`).join("")}</div>`;
