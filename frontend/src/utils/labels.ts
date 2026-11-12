import { type LabelStage, stockApi } from "@/api/operations";

/** Abre o HTML de etiquetas numa aba nova (a página já chama a impressão sozinha). */
export function openLabelsHtml(html: string) {
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Imprime o HTML num quadro escondido da própria página: sem aba nova (que o navegador bloqueia
 *  quando a impressão vem depois de uma chamada à API) e direto para a caixa de impressão. */
export function printLabelsHtml(html: string) {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  frame.srcdoc = html; // o HTML já chama window.print() ao carregar
  document.body.appendChild(frame);
  setTimeout(() => frame.remove(), 120_000);
}

/** Etiquetas da etapa conforme a regra de logística da filial. `true` = resolvido (imprimiu, não havia o
 *  que etiquetar ou a regra diz "não imprime"); `false` = a regra pede para perguntar o modelo. */
export async function autoPrintLabels(id: string, stage: LabelStage) {
  const options = await stockApi.labelOptions(id);
  const mode = options[stage].mode;
  if (mode === "ask") return false;
  if (mode === "auto") {
    const html = await stockApi.stageLabels(id, stage);
    if (html) printLabelsHtml(html);
  }
  return true;
}
