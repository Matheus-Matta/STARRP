/**
 * Pré-venda do vendedor SEM rede (como na loja/mercado): o pedido vira um QR Code (na tela e
 * no ticket impresso) que o caixa lê com o leitor. O caixa monta a venda com os itens, o
 * vendedor e o cliente do ticket — sem precisar do servidor nem da rede entre os PCs.
 *
 * O QR leva: "PV1" + base64url(deflate(JSON)). Só letras, números, "-" e "_": o leitor em modo
 * teclado digita sem trocar caractere em teclado ABNT2.
 *
 * O pedido do vendedor também vai pela fila dele ao servidor (pedido guardado). O caixa conclui
 * com `presale` = o id dele: chegue antes ou depois, o servidor junta os dois (não duplica).
 */
import QRCode from "qrcode";

import type { Sale } from "@/api/types";
import { money as brl } from "@/lib/format";

import { OFFLINE_PREFIX } from "./offline";

export const PRESALE_PREFIX = "PV1";

type Packed = {
  o: string; n: number; s: number | null; sn: string; c: string | null; cn: string; d: string; g: string;
  i: [string, string, string, string, string, number?][]; t: string; at: string;
};

export type Presale = {
  offlineId: string; number: number; seller: number | null; sellerName: string; customer: string | null; customerName: string;
  document: string; discount: string; total: string; createdAt: string;
  items: { variant: string; quantity: string; unit_price: string; discount: string; description: string; parent: number | null }[];
};

async function pipe(data: Uint8Array, stream: CompressionStream | DecompressionStream) {
  const writer = stream.writable.getWriter();
  void writer.write(data as unknown as BufferSource);
  void writer.close();
  return new Uint8Array(await new Response(stream.readable).arrayBuffer());
}

const toB64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const fromB64url = (text: string) => {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4)), (c) => c.charCodeAt(0));
};

export async function encodePresale(sale: Sale): Promise<string> {
  // O serviço (montagem, garantia) vai junto, apontando a posição do item dele: sem isso o caixa não o cobrava.
  const active = sale.items.filter((i) => i.status === "active");
  const items = [...active.filter((i) => !i.parent_item), ...active.filter((i) => i.parent_item)];
  const packed: Packed = {
    o: sale.id.slice(OFFLINE_PREFIX.length), n: sale.number, s: sale.seller, sn: sale.seller_name, c: sale.customer,
    cn: sale.customer_name, d: sale.customer_document ?? "", g: sale.discount, t: sale.total, at: sale.created_at,
    i: items.map((i) => {
      const row: Packed["i"][number] = [i.variant, i.quantity ?? "1", i.unit_price ?? "0", i.discount ?? "0", i.description.slice(0, 40)];
      const parent = i.parent_item ? items.findIndex((p) => p.id === i.parent_item) : -1;
      if (parent >= 0) row.push(parent);
      return row;
    }),
  };
  const bytes = await pipe(new TextEncoder().encode(JSON.stringify(packed)), new CompressionStream("deflate-raw"));
  return PRESALE_PREFIX + toB64url(bytes);
}

export const isPresaleCode = (raw: string) => raw.trim().startsWith(PRESALE_PREFIX) && raw.trim().length > 20;

export async function decodePresale(raw: string): Promise<Presale> {
  const bytes = await pipe(fromB64url(raw.trim().slice(PRESALE_PREFIX.length)), new DecompressionStream("deflate-raw"));
  const p = JSON.parse(new TextDecoder().decode(bytes)) as Packed;
  return {
    offlineId: p.o, number: p.n, seller: p.s, sellerName: p.sn, customer: p.c, customerName: p.cn, document: p.d,
    discount: p.g, total: p.t, createdAt: p.at,
    items: p.i.map(([variant, quantity, unit_price, discount, description, parent]) => ({
      variant, quantity, unit_price, discount, description, parent: parent ?? null,
    })),
  };
}

export const presaleQr = (code: string) => QRCode.toDataURL(code, { errorCorrectionLevel: "L", margin: 1, width: 320 });

/** Ticket de pré-venda (bobina 80 mm): itens, total e o QR para o caixa ler. */
export async function presaleTicket(sale: Sale, code: string, store: string) {
  const qr = await QRCode.toDataURL(code, { errorCorrectionLevel: "L", margin: 0, width: 260 });
  const rows = sale.items.filter((i) => i.status === "active")
    .map((i) => `<tr><td>${Number(i.quantity)} x ${esc(i.description)}</td><td class="r">${brl(i.total ?? "0")}</td></tr>`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font:12px/1.35 monospace;width:100%;max-width:80mm;margin:0;padding:2mm}
    h1{font-size:14px;text-align:center;margin:0}.c{text-align:center}.r{text-align:right}table{width:100%;border-collapse:collapse}
    hr{border:0;border-top:1px dashed #000}.b{font-weight:bold;font-size:15px}img{display:block;margin:2mm auto;width:52mm}
  </style></head><body>
    <h1>${esc(store)}</h1><hr><div class="c b">PRÉ-VENDA ${sale.number}</div>
    <div class="c">Vendedor: ${esc(sale.seller_name || "-")}</div>
    ${sale.customer_name ? `<div class="c">Cliente: ${esc(sale.customer_name)}</div>` : ""}<hr>
    <table>${rows}</table><hr>
    ${Number(sale.discount) ? `<table><tr><td>Desconto</td><td class="r">-${brl(sale.discount)}</td></tr></table>` : ""}
    <div class="b r">TOTAL ${brl(sale.total)}</div><hr>
    <img src="${qr}"><div class="c">Leve ao caixa: o caixa lê este código.</div>
    <div class="c">NÃO É DOCUMENTO FISCAL</div>
  </body></html>`;
}

const esc = (v: string) => v.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
