/** Papel do documento impresso e a memória do último escolhido (por tipo de documento). */
export type PrintFormat = "a4" | "a4-landscape" | "80mm";

const key = (doc: string) => `starrp.print.format.${doc}`;

/** Último papel escolhido para este tipo de documento neste navegador (ou nada). */
export function rememberedFormat(doc: string): PrintFormat | undefined {
  try {
    return (localStorage.getItem(key(doc)) as PrintFormat | null) ?? undefined;
  } catch {
    return undefined;
  }
}

export function rememberFormat(doc: string, format: PrintFormat) {
  try {
    localStorage.setItem(key(doc), format);
  } catch { /* navegador sem armazenamento: só não lembra */ }
}
