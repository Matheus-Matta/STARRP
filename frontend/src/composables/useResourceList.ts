/**
 * Lista paginada no servidor de qualquer cadastro.
 *
 * A chave do cache inclui a loja ativa: trocar de loja recarrega a lista
 * sozinho, e uma loja nunca mostra o cache da outra. `listQuery` é exportado
 * para o pré-carregamento (passar o mouse no menu) usar a MESMA chave.
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import { computed, reactive, type Ref } from "vue";

import { resourceApi } from "@/api/resource";
import type { ResourceDef } from "@/resources/types";
import { useSession } from "@/stores/session";

export type ListState = { page: number; pageSize: number; search: string; ordering: string; filters: Record<string, unknown> };

const hasValues = (filters: Record<string, unknown>) =>
  Object.values(filters).some((v) => v !== null && v !== undefined && v !== "");

export const freshState = (): ListState => ({ page: 1, pageSize: 20, search: "", ordering: "", filters: {} });

export function listQuery(resource: ResourceDef, storeId: string | null, state: ListState) {
  const params = {
    page: state.page,
    page_size: state.pageSize,
    search: state.search,
    ordering: state.ordering || resource.ordering,
    ...resource.params,
    ...state.filters,
    // Árvore do próprio cadastro: a lista mostra o topo; os filhos vêm ao abrir a linha.
    ...(resource.tree?.parent && !state.search && !hasValues(state.filters) ? { root: "1" } : {}),
  };
  return {
    queryKey: ["resource", resource.endpoint, storeId, params] as const,
    queryFn: () => resourceApi.list(resource.endpoint, params as never),
  };
}

export function useResourceList(resource: Ref<ResourceDef>) {
  const session = useSession();
  const state = reactive<ListState>(freshState());
  const options = computed(() => listQuery(resource.value, session.activeStoreId, state));

  const query = useQuery({
    queryKey: computed(() => options.value.queryKey),
    queryFn: () => options.value.queryFn(),
    placeholderData: keepPreviousData,
  });

  function setFilter(name: string, value: unknown) {
    state.filters = { ...state.filters, [name]: value };
    state.page = 1;
  }

  return {
    state,
    rows: computed(() => query.data.value?.results ?? []),
    total: computed(() => query.data.value?.count ?? 0),
    loading: query.isFetching,
    /** Primeira carga sem nada em cache (é aí que entra o skeleton). */
    pending: query.isPending,
    error: query.error,
    refetch: query.refetch,
    setFilter,
  };
}
