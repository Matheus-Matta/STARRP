/**
 * Pré-carregamento: a tela abre "na hora" porque os dados já vieram quando o
 * mouse passou por cima do link (menu, linha da tabela, busca rápida).
 *
 * - `route("/cadastros/produtos")`: baixa o código da página e a 1ª página da lista;
 * - `detail(resource, id)`: baixa o registro que o formulário vai abrir.
 * Usa as MESMAS chaves de cache das telas; repetir é barato (fica 30 s fresco).
 */
import { useQueryClient } from "@tanstack/vue-query";

import { resourceApi } from "@/api/resource";
import { findResource } from "@/resources";
import type { ResourceDef } from "@/resources/types";
import { useSession } from "@/stores/session";

import { freshState, listQuery } from "./useResourceList";

const PAGES: Record<string, () => Promise<unknown>> = {
  list: () => import("@/pages/ResourceListPage.vue"),
  form: () => import("@/pages/ResourceFormPage.vue"),
  dashboard: () => import("@/pages/DashboardPage.vue"),
  pdv: () => import("@/pages/pdv/PdvPage.vue"),
};

export const detailKey = (endpoint: string, id: string) => ["resource-detail", endpoint, id] as const;

export function usePrefetch() {
  const queryClient = useQueryClient();
  const session = useSession();

  function route(to: string) {
    const match = to.match(/^\/cadastros\/([^/]+)$/);
    if (to === "/") return void PAGES.dashboard!();
    if (to === "/pdv") return void PAGES.pdv!();
    const resource = match ? findResource(match[1]!) : undefined;
    if (!resource) return;
    void PAGES.list!();
    void PAGES.form!();
    void queryClient.prefetchQuery({ ...listQuery(resource, session.activeStoreId, freshState()), staleTime: 30_000 });
  }

  function detail(resource: ResourceDef, id: string) {
    void queryClient.prefetchQuery({
      queryKey: detailKey(resource.endpoint, id),
      queryFn: () => resourceApi.get(resource.endpoint, id),
      staleTime: 15_000,
    });
  }

  /** Baixa o código das telas principais quando o navegador fica ocioso. */
  function warmPages() {
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void) => void }).requestIdleCallback
      ?? ((cb: () => void) => setTimeout(cb, 1500));
    idle(() => Object.values(PAGES).forEach((load) => void load()));
  }

  return { route, detail, warmPages };
}
