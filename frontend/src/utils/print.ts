/**
 * Abre um documento de impressão numa aba nova (a tela atual fica como está).
 * Ex.: openPrint("venda", id, { formato: "80mm", auto: "1" }) → recibo já pedindo para imprimir.
 * Sem `formato`: o último papel escolhido para o documento neste navegador (padrão A4).
 *
 * Monta o endereço sem o router: importá-lo aqui fecharia um ciclo
 * (recursos → print → router → layout → recursos).
 */
export function printHref(doc: string, id = "", query: Record<string, string | null | undefined> = {}) {
  const clean = Object.entries(query).filter(([, v]) => v !== null && v !== undefined && v !== "") as [string, string][];
  const search = new URLSearchParams(clean).toString();
  return `/imprimir/${doc}${id ? `/${encodeURIComponent(id)}` : ""}${search ? `?${search}` : ""}`;
}

export function openPrint(doc: string, id = "", query: Record<string, string | null | undefined> = {}) {
  window.open(printHref(doc, id, query), "_blank");
}
