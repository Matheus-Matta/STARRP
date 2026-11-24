/**
 * Deploy novo com a aba aberta: as telas são carregadas sob demanda e os arquivos da versão
 * anterior (nome com hash) não existem mais no servidor. Em vez de a tela não abrir, recarrega
 * a página UMA vez (o index.html nunca fica em cache) indo direto para onde a pessoa ia.
 */
import type { App } from "vue";
import type { Router } from "vue-router";

const KEY = "starrp.reloadedForBuild";
const WINDOW_MS = 60_000;

const CHUNK_ERROR = /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS/i;

export function isStaleChunkError(error: unknown) {
  return error instanceof Error && CHUNK_ERROR.test(error.message);
}

/** Recarrega se ainda não recarregou no último minuto (evita laço se o servidor estiver fora). */
export function reloadForNewBuild(target?: string) {
  try {
    const last = Number(sessionStorage.getItem(KEY) ?? 0);
    if (Date.now() - last < WINDOW_MS) return false;
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    // sem storage: recarrega mesmo assim (no pior caso, uma vez por erro)
  }
  if (target) window.location.assign(target);
  else window.location.reload();
  return true;
}

export function handleStaleBuilds(app: App, router: Router) {
  // Pré-carregamento do Vite falhou (CSS/JS de uma tela): recarrega em vez de mostrar erro.
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadForNewBuild()) event.preventDefault();
  });
  router.onError((error, to) => {
    if (isStaleChunkError(error)) reloadForNewBuild(to.fullPath);
  });
  // Diálogos e painéis carregados sob demanda (defineAsyncComponent) caem aqui, não no router.
  const previous = app.config.errorHandler;
  app.config.errorHandler = (error, instance, info) => {
    if (isStaleChunkError(error) && reloadForNewBuild()) return;
    if (previous) previous(error, instance, info);
    else console.error(error);
  };
}
