/**
 * `@/utils/print` da retaguarda no celular: `openPrint("venda", id, { formato: "80mm" })` abre o painel de
 * impressão do app (`PrintHost`), com o MESMO documento da retaguarda (`src/print`) — PDF para compartilhar ou
 * a impressão do sistema.
 */
export { openPrint } from "@/print/bus";

export function printHref(doc: string, id = "", query: Record<string, string | null | undefined> = {}) {
  const clean = Object.entries(query).filter(([, v]) => v !== null && v !== undefined && v !== "") as [string, string][];
  const search = clean.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  return `/imprimir/${doc}${id ? `/${encodeURIComponent(id)}` : ""}${search ? `?${search}` : ""}`;
}
