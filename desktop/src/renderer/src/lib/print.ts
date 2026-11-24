/**
 * Imprimir da tela: o processo principal escolhe a impressora configurada (recibo ou nota),
 * pergunta antes (modo "perguntar") ou imprime direto, e devolve o resultado.
 */
import { notify } from "@/state/toast";

import type { LocalInvoice, PrinterTarget, PrintJob } from "../../../shared/ipc";
import { danfeHtml, type DanfeData, fromLocal } from "./danfe";

export async function printHtml(job: PrintJob, failTitle = "Não impresso") {
  const result = await window.starrp.printers.print(job);
  if (!result.ok && !result.cancelled) notify.warn(failTitle, result.error ?? "A impressora recusou.");
  return result.ok;
}

export const printReceipt = (html: string, options: { drawer?: boolean; target?: PrinterTarget } = {}) =>
  printHtml({ html, slot: "receipt", title: "Recibo", ...options }, "Recibo não impresso");

export async function printDanfe(data: DanfeData | LocalInvoice, target?: PrinterTarget, drawer = false) {
  const danfe = "danfe" in data ? fromLocal(data) : data;
  return printHtml({ html: await danfeHtml(danfe), slot: "fiscal", target, drawer, title: `Nota ${danfe.number}` }, "Nota não impressa");
}
