/**
 * Rascunhos de formulário: alterações ainda não salvas, guardadas para terminar depois.
 *
 * Ficam NESTE navegador (por conta, usuário, cadastro e registro): não vão ao
 * servidor nem aparecem para outra pessoa. Ex.: começar um produto novo, sair
 * escolhendo "Guardar rascunho" e, na volta, "Continuar de onde parei".
 *
 *   saveDraft(scope, "produtos", "novo", values, "Camiseta")  → guarda
 *   loadDraft(scope, "produtos", "novo")                      → { values, savedAt, title }
 *   listDrafts(scope, "produtos")                             → os rascunhos deste cadastro
 */
export type Draft = { values: Record<string, unknown>; savedAt: string; title: string; record: string };

const PREFIX = "starrp.draft";
const key = (scope: string, resource: string, record: string) => `${PREFIX}:${scope}:${resource}:${record}`;

/** Storage pode falhar (aba anônima cheia, bloqueado): rascunho é conveniência, nunca quebra a tela. */
function safely<T>(run: () => T, fallback: T): T {
  try {
    return run();
  } catch {
    return fallback;
  }
}

export function saveDraft(scope: string, resource: string, record: string, values: Record<string, unknown>, title: string) {
  const draft: Draft = { values, savedAt: new Date().toISOString(), title, record };
  return safely(() => {
    localStorage.setItem(key(scope, resource, record), JSON.stringify(draft));
    return true;
  }, false);
}

export function loadDraft(scope: string, resource: string, record: string): Draft | null {
  return safely(() => {
    const raw = localStorage.getItem(key(scope, resource, record));
    return raw ? (JSON.parse(raw) as Draft) : null;
  }, null);
}

export function removeDraft(scope: string, resource: string, record: string) {
  safely(() => localStorage.removeItem(key(scope, resource, record)), undefined);
}

export function listDrafts(scope: string, resource: string): Draft[] {
  return safely(() => {
    const start = `${PREFIX}:${scope}:${resource}:`;
    const found: Draft[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const name = localStorage.key(i);
      if (!name?.startsWith(start)) continue;
      const draft = JSON.parse(localStorage.getItem(name) ?? "null") as Draft | null;
      if (draft) found.push(draft);
    }
    return found.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
  }, []);
}
