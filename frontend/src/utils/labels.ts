import { type LabelStage, stockApi } from "@/api/operations";

/**
 * O HTML das etiquetas não tem script (o CSP do app não deixa rodar script na página de impressão, S-23):
 * quem imprime é o app, chamando `print()` da janela/quadro onde o HTML foi escrito.
 */
function printWhenReady(target: Window) {
  const go = () => {
    target.focus();
    target.print();
  };
  if (target.document.readyState === "complete") setTimeout(go, 150);  // dá tempo às imagens dos códigos
  else target.addEventListener("load", go, { once: true });
}

/** Abre o HTML de etiquetas numa aba e pede a impressão. `win`: aba já aberta no clique (o navegador
 *  bloqueia aba aberta depois de uma chamada à API). */
export function openLabelsHtml(html: string, win?: Window | null) {
  const target = win ?? window.open("", "_blank");
  if (!target) return;
  target.document.open();
  target.document.write(html);
  target.document.close();
  printWhenReady(target);
}

/** Imprime o HTML num quadro escondido da própria página: sem aba nova (que o navegador bloqueia
 *  quando a impressão vem depois de uma chamada à API) e direto para a caixa de impressão. */
export function printLabelsHtml(html: string) {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  frame.addEventListener("load", () => frame.contentWindow && printWhenReady(frame.contentWindow), { once: true });
  frame.srcdoc = html;
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
