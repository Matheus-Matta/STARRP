<script setup lang="ts">
/**
 * Lista de outro cadastro filtrada pelo registro aberto (kardex do produto, compras
 * do cliente, turnos do caixa...). Ordena por coluna, pagina no servidor, busca e
 * exporta CSV com os mesmos filtros (a ação em massa "exportar" do backend).
 */
import { keepPreviousData, useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable, { type DataTableSortEvent } from "primevue/datatable";
import IconField from "primevue/iconfield";
import InputIcon from "primevue/inputicon";
import InputText from "primevue/inputtext";
import Paginator, { type PageState } from "primevue/paginator";
import Skeleton from "primevue/skeleton";
import { computed, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { bulkApi } from "@/api/bulk";
import { resourceApi, type Row } from "@/api/resource";
import EmptyState from "@/components/common/EmptyState.vue";
import { useNotify } from "@/composables/useNotify";
import type { ListViewDef } from "@/resources/types";
import { useSession } from "@/stores/session";
import { openPrint } from "@/utils/print";

import CellValue from "./CellValue.vue";

/**
 * `pick`: a linha clicada é ESCOLHIDA (evento `pick`), não aberta — o PDV usa assim para
 * cliente e pedidos. `compact`: sem imprimir/exportar. Slot `toolbar`: botões extras.
 */
const props = defineProps<{
  view: ListViewDef; id: string; values: Record<string, unknown>; title: string; resourceName?: string; viewName?: string;
  pick?: boolean; compact?: boolean; placeholder?: string;
}>();
const emit = defineEmits<{ pick: [row: Row] }>();
const router = useRouter();
const session = useSession();
const notify = useNotify();
const state = reactive({ page: 1, pageSize: 20, ordering: props.view.ordering ?? "", search: "" });
const searchText = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
watch(searchText, (v) => {
  clearTimeout(timer);
  timer = setTimeout(() => Object.assign(state, { search: v, page: 1 }), 250);
});

const fixed = computed(() => props.view.params(props.id, props.values));
const params = computed(() => ({ ...fixed.value, page: state.page, page_size: state.pageSize, ordering: state.ordering,
                                 search: state.search }));
const query = useQuery({
  queryKey: computed(() => ["embedded", props.view.endpoint, session.activeStoreId, params.value]),
  queryFn: () => resourceApi.list(props.view.endpoint, params.value),
  placeholderData: keepPreviousData,
});
const rows = computed(() => query.data.value?.results ?? []);
const total = computed(() => query.data.value?.count ?? 0);
const numeric = (type?: string) => ["money", "quantity", "percent"].includes(type ?? "");

const first = computed({
  get: () => (state.page - 1) * state.pageSize,
  set: (value: number) => (state.page = Math.floor(value / state.pageSize) + 1),
});
const onPage = (e: PageState) => Object.assign(state, { pageSize: e.rows, page: e.page + 1 });
function onSort(e: DataTableSortEvent) {
  state.ordering = e.sortField ? `${e.sortOrder === -1 ? "-" : ""}${String(e.sortField)}` : props.view.ordering ?? "";
  state.page = 1;
}
const sortField = computed(() => state.ordering.replace(/^-/, "") || undefined);
const sortOrder = computed(() => (state.ordering.startsWith("-") ? -1 : state.ordering ? 1 : 0));

const exporting = ref(false);
async function exportCsv() {
  exporting.value = true;
  try {
    await bulkApi.download(props.view.endpoint, { all: true, filters: { ...fixed.value, search: state.search, ordering: state.ordering } },
                           { columns: props.view.columns.map((c) => ({ key: c.key, label: c.label, map: c.map })) }, `${props.title}.csv`);
  } catch (error) {
    notify.error(error, "Não foi possível exportar");
  } finally {
    exporting.value = false;
  }
}
function open(row: Row) {
  if (props.pick) return emit("pick", row);
  if (props.view.rowLink) void router.push(props.view.rowLink(row));
}
defineExpose({ refetch: () => query.refetch() });
</script>

<template>
  <div class="embedded">
    <div class="toolbar">
      <IconField v-if="view.searchable !== false" class="search">
        <InputIcon class="pi pi-search" />
        <InputText v-model="searchText" :placeholder="placeholder ?? 'Buscar…'" size="small" fluid />
      </IconField>
      <slot name="toolbar" />
      <span class="count">{{ total.toLocaleString("pt-BR") }} {{ total === 1 ? "registro" : "registros" }}</span>
      <Button v-if="!compact" label="Imprimir" icon="pi pi-print" size="small" severity="secondary" text :disabled="!total"
              @click="openPrint('lista', resourceName, { view: viewName, registro: id, titulo: title, search: state.search, ordering: state.ordering })" />
      <Button v-if="!compact" label="Exportar CSV" icon="pi pi-file-export" size="small" severity="secondary" text :loading="exporting"
              :disabled="!total" @click="exportCsv" />
    </div>
    <div v-if="query.isPending.value" class="stack"><Skeleton v-for="n in 8" :key="n" height="2.2rem" /></div>
    <DataTable v-else :value="rows" lazy data-key="id" size="small" scrollable row-hover removable-sort
               :sort-field="sortField" :sort-order="sortOrder"
               :class="{ clickable: !!view.rowLink || pick, refreshing: query.isFetching.value }"
               @sort="onSort" @row-click="open($event.data)">
      <template #empty><EmptyState title="Nada por aqui" icon="pi pi-inbox" description="Nenhum registro ligado a este item." /></template>
      <Column v-for="column in view.columns" :key="column.key" :field="column.key" :header="column.label"
              :sortable="column.sortable !== false" :header-class="numeric(column.type) ? 'right' : ''"
              :body-class="numeric(column.type) ? 'right' : ''">
        <template #body="{ data }"><CellValue :column="column" :value="data[column.key]" /></template>
      </Column>
    </DataTable>
    <Paginator v-if="total > state.pageSize" v-model:first="first" v-model:rows="state.pageSize" :total-records="total"
               :rows-per-page-options="[10, 20, 50]" @page="onPage" />
  </div>
</template>

<style scoped>
.embedded { background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.toolbar { display: flex; align-items: center; gap: 0.75rem; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); }
.search { flex: 0 1 300px; }
.count { margin-left: auto; font-size: 12.5px; color: var(--text-muted); }
.stack { display: flex; flex-direction: column; gap: 8px; padding: 12px; }
.clickable :deep(.p-datatable-tbody > tr) { cursor: pointer; }
.refreshing :deep(.p-datatable-tbody) { opacity: 0.6; }
:deep(.right) { text-align: right; justify-content: flex-end; }
</style>
