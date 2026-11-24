/**
 * Pedido de impressão, sem dependências: os cadastros da retaguarda chamam `openPrint()` (via o substituto de
 * `@/utils/print`) e o painel `PrintHost` escuta. Fica separado de `print/index.ts` para não formar o ciclo
 * cadastros → impressão → documentos → cadastros na abertura do app.
 */
export type PrintRequest = { doc: string; id: string; query: Record<string, string> };
type Listener = (request: PrintRequest) => void;

const listeners = new Set<Listener>();

export function onPrintRequest(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function openPrint(doc: string, id = "", query: Record<string, string | null | undefined> = {}) {
  const clean = Object.fromEntries(Object.entries(query).filter(([, v]) => v !== null && v !== undefined && v !== "")) as Record<string, string>;
  listeners.forEach((l) => l({ doc, id, query: clean }));
}

/** "/imprimir/venda/12?formato=80mm" → pedido de impressão. */
export function parsePrintHref(href: string): PrintRequest | null {
  const [path, search = ""] = href.split("?");
  const m = /^\/imprimir\/([^/]+)(?:\/([^/]+))?$/.exec(path ?? "");
  if (!m) return null;
  const query = Object.fromEntries(search.split("&").filter(Boolean).map((pair) => {
    const [k = "", v = ""] = pair.split("=");
    return [decodeURIComponent(k), decodeURIComponent(v.replace(/\+/g, " "))];
  }));
  return { doc: m[1]!, id: decodeURIComponent(m[2] ?? ""), query };
}
