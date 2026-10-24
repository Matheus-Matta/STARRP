/**
 * Seleção da lista para as ações em massa.
 *
 * Checkbox do cabeçalho, em ciclo:
 *   1º clique → marca os itens DESTA página
 *   2º clique → marca TODOS os registros da lista (todas as páginas, com os filtros da tela)
 *   3º clique → desmarca tudo
 * Em lista que cabe numa página só, o 2º clique já desmarca.
 *
 * Os ids marcados à mão sobrevivem à troca de página; trocar busca/filtro limpa.
 */
import { computed, ref, type Ref } from "vue";

import type { BulkTarget } from "@/api/bulk";
import type { ListParams } from "@/api/http";

export function useBulkSelection(rows: Ref<{ id: string }[]>, total: Ref<number>) {
  const ids = ref(new Set<string>());
  const all = ref(false);

  const pageIds = computed(() => rows.value.map((r) => String(r.id)));
  const pageChecked = computed(() => pageIds.value.length > 0 && pageIds.value.every((id) => ids.value.has(id)));
  const count = computed(() => (all.value ? total.value : ids.value.size));
  const header = computed<"none" | "partial" | "page" | "all">(() => {
    if (all.value) return "all";
    if (pageChecked.value) return "page";
    return pageIds.value.some((id) => ids.value.has(id)) || ids.value.size ? "partial" : "none";
  });

  function clear() {
    ids.value = new Set();
    all.value = false;
  }

  function selectPage() {
    all.value = false;
    ids.value = new Set([...ids.value, ...pageIds.value]);
  }

  function selectAll() {
    all.value = true;
  }

  function cycleHeader() {
    if (all.value) return clear();
    if (pageChecked.value) return total.value > pageIds.value.length ? selectAll() : clear();
    selectPage();
  }

  /** Desmarcar uma linha com "todos" ativo volta para seleção explícita (a página menos ela). */
  function toggle(id: string) {
    const next = all.value ? new Set(pageIds.value) : new Set(ids.value);
    all.value = false;
    if (next.has(id)) next.delete(id);
    else next.add(id);
    ids.value = next;
  }

  const isSelected = (id: string) => all.value || ids.value.has(id);

  function target(filters: ListParams): BulkTarget {
    return all.value ? { all: true, filters } : { ids: [...ids.value] };
  }

  return { ids, all, count, header, pageChecked, clear, selectPage, selectAll, cycleHeader, toggle, isSelected, target };
}
