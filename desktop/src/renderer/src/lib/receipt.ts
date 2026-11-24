/**
 * Comprovantes em bobina 80 mm, montados aqui e impressos pelo processo principal (janela
 * invisível → impressora padrão). Não são documento fiscal: a NFC-e sai pelo módulo fiscal.
 */
import type { CashSession, PdvBootstrap, Sale } from "@/api/types";

import { dateTime, money, quantity } from "./format";

const esc = (value: unknown) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const shell = (title: string, body: string) => `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>${esc(title)}</title><style>
@page { size: 80mm auto; margin: 0; }
* { box-sizing: border-box; }
body { width: 100%; max-width: 80mm; margin: 0; padding: 4mm 4mm 8mm; font: 11px/1.35 "Consolas", "Courier New", monospace; color: #000; }
h1 { font-size: 13px; margin: 0; text-align: center; }
.c { text-align: center; } .r { text-align: right; } .b { font-weight: 700; }
hr { border: 0; border-top: 1px dashed #000; margin: 6px 0; }
table { width: 100%; border-collapse: collapse; } td { vertical-align: top; padding: 1px 0; }
.big { font-size: 15px; font-weight: 700; }
.sub { padding-left: 10px; }
</style></head><body>${body}</body></html>`;

const row = (left: string, right: string, cls = "") => `<tr class="${cls}"><td>${left}</td><td class="r">${right}</td></tr>`;

export function saleReceipt(sale: Sale, boot: PdvBootstrap | null, operator: string) {
  const items = sale.items.filter((i) => i.status === "active");
  const store = boot?.store;
  const lines = items.map((i) => `<tr><td colspan="2" class="${i.parent_item ? "sub" : ""}">${esc(i.description)}</td></tr>
    ${row(`<span class="${i.parent_item ? "sub" : ""}">${quantity(i.quantity)} ${esc((i.unit ?? "UN").toLowerCase())} × ${money(i.unit_price)}</span>`, money(i.total))}`).join("");
  const payments = (sale.payments ?? []).filter((p) => !p.status || p.status === "approved")
    .map((p) => row(`${esc(p.method_name)}${(p.installments ?? 1) > 1 ? ` ${p.installments}x` : ""}`, money(p.amount))).join("");
  const body = `
    <h1>${esc(store?.legal_name || store?.name || "Starrp")}</h1>
    ${store?.document ? `<div class="c">CNPJ ${esc(store.document)}</div>` : ""}
    <hr><div class="c b">COMPROVANTE DE VENDA Nº ${esc(sale.number)}</div>
    <div class="c">${dateTime(sale.completed_at ?? sale.created_at)}</div>
    <div class="c">NÃO É DOCUMENTO FISCAL</div><hr>
    ${sale.customer_name || sale.customer_document ? `<div>Cliente: ${esc(sale.customer_name || sale.customer_document)}</div>` : ""}
    ${sale.seller_name ? `<div>Vendedor: ${esc(sale.seller_name)}</div>` : ""}
    <div>Operador: ${esc(operator)}</div><hr>
    <table>${lines}</table><hr>
    <table>
      ${row("Subtotal", money(sale.subtotal))}
      ${Number(sale.discount) ? row("Desconto", `- ${money(sale.discount)}`) : ""}
      ${sale.coupon_code ? row(`Cupom ${esc(sale.coupon_code)}`, `- ${money(sale.coupon_discount)}`) : ""}
      ${Number(sale.freight) ? row("Frete", money(sale.freight)) : ""}
      ${row("TOTAL", money(sale.total), "big")}
    </table><hr>
    <table>${payments}${Number(sale.change_amount) ? row("Troco", money(sale.change_amount), "b") : ""}</table>
    <hr><div class="c">Obrigado pela preferência!</div>`;
  return shell(`Venda ${sale.number}`, body);
}

export function shiftReceipt(session: CashSession, boot: PdvBootstrap | null, title = "ABERTURA DE CAIXA") {
  const body = `
    <h1>${esc(boot?.store?.name ?? "Starrp")}</h1><hr>
    <div class="c b">${esc(title)}</div><hr>
    <table>
      ${row("Caixa", esc(session.register_name))}
      ${row("Operador", esc(session.opened_by_name))}
      ${row("Aberto em", dateTime(session.opened_at))}
      ${row("Troco inicial", money(session.opening_amount))}
      ${session.closed_at ? row("Fechado em", dateTime(session.closed_at)) : ""}
      ${session.counted_amount != null ? row("Contado", money(session.counted_amount)) : ""}
    </table>
    <hr><div class="c">Impresso em ${dateTime(new Date().toISOString())}</div>
    <br><br><div class="c">______________________________</div><div class="c">Assinatura</div>`;
  return shell(title, body);
}



