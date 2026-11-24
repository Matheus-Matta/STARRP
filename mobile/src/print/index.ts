/**
 * Impressão no app = a página `/imprimir/<documento>/<id>` da retaguarda: carrega o documento (`docs.ts`), monta a
 * folha (`shell.ts`) no papel escolhido e gera o PDF (compartilhar) ou manda para a impressão do sistema.
 * `openPrint(doc, id, query)` — o mesmo que os cadastros da retaguarda chamam — abre o painel `PrintHost`.
 */
import type { Me } from "@/api/types";
import { fileName, printDocument, sharePdf } from "@/lib/share";

import type { PrintRequest } from "./bus";
import { DOCS, type LoadedDoc } from "./docs";
import { loadCompany, type PrintFormat, shell } from "./shell";

export type { PrintRequest } from "./bus";

export async function loadPrint(request: PrintRequest, storeName: string) {
  const loader = DOCS[request.doc];
  if (!loader) throw new Error("Documento de impressão desconhecido.");
  return loader(request.id, { query: request.query, storeName });
}

export async function renderPrint(doc: LoadedDoc, format: PrintFormat, me: Me | null, activeStore: string | null) {
  const company = await loadCompany(doc.storeId ?? activeStore, me);
  return shell({
    title: doc.title, subtitle: doc.subtitle, format, bare: doc.bare, company, logo: me?.account?.logo_url, user: me?.name,
    body: doc.body(format === "80mm"), extraCss: doc.css,
  });
}

export async function sharePrint(doc: LoadedDoc, format: PrintFormat, me: Me | null, activeStore: string | null) {
  await sharePdf(await renderPrint(doc, format, me, activeStore), fileName(doc.filename, "pdf"), doc.title);
}

export async function printNow(doc: LoadedDoc, format: PrintFormat, me: Me | null, activeStore: string | null) {
  await printDocument(await renderPrint(doc, format, me, activeStore));
}

export { onPrintRequest, openPrint, parsePrintHref } from "./bus";
