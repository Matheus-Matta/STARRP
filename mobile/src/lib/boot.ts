/**
 * Diagnóstico da abertura do app, no terminal do Metro (`npm run mobile`), onde chegam os logs do celular:
 *  - etapas: "[starrp] +0.6s fontes carregadas", "[starrp] +2.1s sessão: signedOut"...;
 *  - QUALQUER erro de JavaScript (fatal ou não) e promessa rejeitada sem tratamento, com a pilha:
 *    "[starrp] ERRO FATAL ..." — quando a tela fica branca ou o app fecha, o motivo aparece aqui.
 * Importado na 1ª linha do layout raiz: os capturadores entram antes de qualquer tela.
 */
const started = Date.now();
const stamp = () => `+${((Date.now() - started) / 1000).toFixed(1)}s`;

export function boot(step: string) {
  console.log(`[starrp] ${stamp()} ${step}`);
}

function describe(error: unknown) {
  if (error instanceof Error) return `${error.name}: ${error.message}\n${error.stack ?? ""}`;
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

type ErrorUtilsShape = {
  getGlobalHandler: () => (error: unknown, isFatal?: boolean) => void;
  setGlobalHandler: (handler: (error: unknown, isFatal?: boolean) => void) => void;
};
type HermesShape = { enablePromiseRejectionTracker?: (options: {
  allRejections: boolean; onUnhandled: (id: number, error: unknown) => void; onHandled: () => void;
}) => void };

let installed = false;

/** Liga os capturadores (uma vez). */
export function installErrorLogging() {
  if (installed) return;
  installed = true;
  console.log(`[starrp] ${stamp()} diagnóstico ligado (${__DEV__ ? "desenvolvimento" : "produção"})`);

  const errorUtils = (globalThis as { ErrorUtils?: ErrorUtilsShape }).ErrorUtils;
  if (errorUtils?.getGlobalHandler) {
    const previous = errorUtils.getGlobalHandler();
    errorUtils.setGlobalHandler((error, isFatal) => {
      console.error(`[starrp] ${stamp()} ERRO ${isFatal ? "FATAL" : "(não fatal)"}: ${describe(error)}`);
      previous(error, isFatal);
    });
  }

  // Promessa rejeitada que ninguém tratou (no Hermes) — costuma ser a causa de tela branca sem erro na tela.
  const hermes = (globalThis as { HermesInternal?: HermesShape }).HermesInternal;
  hermes?.enablePromiseRejectionTracker?.({
    allRejections: true,
    onUnhandled: (id, error) => console.error(`[starrp] ${stamp()} PROMESSA REJEITADA #${id}: ${describe(error)}`),
    onHandled: () => undefined,
  });

  // No navegador (Expo web, para testes).
  const win = globalThis as { addEventListener?: (type: string, cb: (event: { reason?: unknown; error?: unknown }) => void) => void };
  if (typeof win.addEventListener === "function" && !errorUtils) {
    win.addEventListener("error", (event) => console.error(`[starrp] ${stamp()} ERRO: ${describe(event.error)}`));
    win.addEventListener("unhandledrejection", (event) => console.error(`[starrp] ${stamp()} PROMESSA REJEITADA: ${describe(event.reason)}`));
  }
}

installErrorLogging();
