/**
 * Emitir a nota de uma venda por este PDV (comunicador ACBr local, no processo principal) e
 * avisar o operador. A venda pode ser a do servidor ou a offline: o formato é o mesmo.
 */
import type { Sale } from "@/api/types";
import { notify } from "@/state/toast";

import type { LocalInvoice, PrinterTarget } from "../../../shared/ipc";
import { printDanfe } from "./print";

const label = (model: string) => (model === "55" ? "NF-e" : "NFC-e");

export async function emitInvoice(sale: Sale, model: "65" | "55", options: { print?: boolean; target?: PrinterTarget; drawer?: boolean } = {}) {
  const result = await window.starrp.fiscal.emit({ sale: sale as unknown as Record<string, unknown>, model, saleRef: sale.id });
  const invoice: LocalInvoice | undefined = result.invoice;
  if (!result.ok) {
    notify.warn(`${label(model)} não emitida`, result.error ?? invoice?.message ?? "O comunicador recusou.");
    return invoice ?? null;
  }
  if (invoice!.status === "contingency") {
    notify.warn(`${label(model)} ${invoice!.number} em contingência`,
      "SEFAZ fora do ar: a nota foi assinada aqui e será transmitida quando a internet voltar.");
  } else notify.success(`${label(model)} ${invoice!.number} autorizada`, invoice!.environment === "2" ? "Homologação (sem valor fiscal)." : undefined);
  if (options.print !== false) await printDanfe(invoice!, options.target, options.drawer);
  return invoice!;
}
