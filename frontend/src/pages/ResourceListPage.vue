<script setup lang="ts">
/**
 * Lista de QUALQUER cadastro declarado em `resources/`.
 *
 * Rápida de usar: "/" vai para a busca, "N" cria um novo, passar o mouse numa
 * linha já baixa o registro (o formulário abre sem esperar). Na primeira carga
 * aparece um skeleton com as MESMAS colunas da tabela.
 *
 * A tabela ocupa a largura toda e a altura da tela (o corpo rola por dentro,
 * cabeçalho e paginação ficam fixos), mesmo com poucos ou nenhum registro.
 *
 * Toda coluna ordena (1º clique A→Z, 2º Z→A, 3º volta ao padrão). A coluna de
 * checkbox marca itens para as ações em massa (ver `useBulkSelection`).
 *
 * No celular a tabela vira cartões (`MobileCards`), os filtros ficam atrás do botão
 * "Filtros" e a paginação mostra só anterior / próxima.
 */
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Column from "primevue/column";
import DatePicker from "primevue/datepicker";
import DataTable, { type DataTableSortEvent } from "primevue/datatable";
import IconField from "primevue/iconfield";
import InputIcon from "primevue/inputicon";
import InputText from "primevue/inputtext";
import Menu from "primevue/menu";
import Paginator, { type PageState } from "primevue/paginator";
import TreeTable from "primevue/treetable";
import type { TreeNode } from "primevue/treenode";
import { useConfirm } from "primevue/useconfirm";
import Select from "primevue/select";
import Skeleton from "primevue/skeleton";
import { computed, onBeforeUnmount, onMounted, ref, type Ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { resourceApi, type Row } from "@/api/resource";
import { useNotify } from "@/composables/useNotify";
import { listDrafts } from "@/utils/drafts";
import { dateTime } from "@/utils/format";
import { openPrint } from "@/utils/print";
import EmptyState from "@/components/common/EmptyState.vue";
import BulkBar from "@/components/list/BulkBar.vue";
import MobileCards from "@/components/list/MobileCards.vue";
import CellValue from "@/components/resource/CellValue.vue";
import FormActions from "@/components/resource/FormActions.vue";
import RelationSelect from "@/components/resource/RelationSelect.vue";
import { useBulkSelection } from "@/composables/useBulkSelection";
import { usePrefetch } from "@/composables/usePrefetch";
import { useResourceList } from "@/composables/useResourceList";
import { useViewport } from "@/composables/useViewport";
import { findResource } from "@/resources";
import { type ColumnDef, newLabel, type ResourceDef } from "@/resources/types";
import { useSession } from "@/stores/session";

const route = useRoute();
const router = useRouter();
const session = useSession();
const prefetch = usePrefetch();
const { isPhone } = useViewport();
const filtersOpen = ref(false);
const resource = computed(() => findResource(String(route.params.resource)) as ResourceDef);
const { state, rows, total, loading, pending, refetch, setFilter } = useResourceList(resource);
/** Rascunhos deste cadastro (alterações guardadas para terminar depois). */
const drafts = computed(() => listDrafts(`${session.me?.account?.id ?? "-"}:${session.me?.id ?? "-"}`, resource.value.name));
const draftMenu = ref<InstanceType<typeof Menu>>();
const draftItems = computed(() => [{
  label: "Continuar de onde parou",
  items: drafts.value.map((d) => ({
    label: `${d.title}${d.record === "novo" ? " (novo)" : ""} · ${dateTime(d.savedAt)}`, icon: "pi pi-file-edit",
    command: () => router.push(`/cadastros/${resource.value.name}/${d.record}`),
  })),
}]);
/** Ações do topo da lista não têm registro: só recarregam a lista ao terminar. */
const listCtx = { id: "", values: {}, reload: async () => void (await refetch()) };
const canWrite = computed(() => !resource.value.readOnly && session.can(`${resource.value.permission}.manage`));
/** Cadastro fixo do sistema: só o superusuário cria ou exclui (a loja só ajusta). */
const locked = computed(() => Boolean(resource.value.systemData) && !session.me?.is_superuser);
const canCreate = computed(() => canWrite.value && resource.value.creatable !== false && !locked.value);

/** Nome amigável dos filtros que chegam por link (o selo mostra "Filtrado: produto"). */
const FILTER_NAMES: Record<string, string> = {
  variant: "produto", product: "produto", financial_account: "conta", warehouse: "depósito", customer: "cliente",
  supplier: "fornecedor", title__kind: "tipo", status: "situação", due_date__gte: "vence a partir de",
  due_date__lte: "vence até", expires_at__lte: "vence até", category: "categoria",
};

/** Filtro vindo da URL (ex.: o saldo abre o kardex com `?variant=<id>`). */
for (const [key, value] of Object.entries(route.query)) {
  if (typeof value === "string" && value) state.filters[key] = value;
}
const declared = computed(() => new Set((resource.value.filters ?? []).flatMap((f) =>
  f.type === "daterange" ? [`${f.name}__gte`, `${f.name}__lte`] : [f.name])));
/** Filtros ativos que não têm campo na barra (vieram de um link): viram um selo com X. */
const hiddenFilters = computed(() => Object.entries(state.filters)
  .filter(([key, value]) => !declared.value.has(key) && value !== null && value !== undefined && value !== ""));
function dropFilter(key: string) {
  setFilter(key, null);
  void router.replace({ query: Object.fromEntries(Object.entries(route.query).filter(([k]) => k !== key)) });
}

/** Período (de/até) do filtro de datas, como `Date[]` para o DatePicker. */
function rangeOf(name: string) {
  const from = state.filters[`${name}__gte`] as string | undefined;
  const to = state.filters[`${name}__lte`] as string | undefined;
  return from ? [new Date(`${from}T00:00:00`), ...(to ? [new Date(`${to}T00:00:00`)] : [])] : null;
}
function setRange(name: string, value: (Date | null)[] | Date | null | undefined) {
  const [from, to] = Array.isArray(value) ? value : [];
  state.filters = { ...state.filters, [`${name}__gte`]: from?.toLocaleDateString("sv-SE") ?? null,
                    [`${name}__lte`]: to?.toLocaleDateString("sv-SE") ?? null };
  state.page = 1;
}
/** Filtros da barra com valor (o botão "Filtros" do celular mostra quantos). */
const activeFilters = computed(() => [...declared.value].filter((key) => {
  const value = state.filters[key];
  return value !== null && value !== undefined && value !== "";
}).length);
const hasFilters = computed(() => Boolean(state.search) || Object.values(state.filters).some((v) => v !== null && v !== undefined && v !== ""));
const searchBox = ref<{ $el: HTMLElement }>();
const selection = useBulkSelection(rows as Ref<{ id: string }[]>, total);
/** Os mesmos filtros da tela: "selecionar todos" vale para o que a lista mostra. */
const listFilters = computed(() => ({ search: state.search, ordering: state.ordering, ...state.filters }) as Record<string, string>);
watch(() => [state.search, state.filters, resource.value.endpoint], selection.clear, { deep: true });
const headerTitle = computed(() => ({
  none: "Marcar os itens desta página", partial: "Marcar os itens desta página",
  page: total.value > rows.value.length ? `Marcar todos os ${total.value}` : "Desmarcar", all: "Desmarcar todos",
})[selection.header.value]);
function afterBulk() {
  selection.clear();
  void refetch();
}

const searchText = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
watch(searchText, (value) => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    state.search = value;
    state.page = 1;
  }, 250);
});

function clearFilters() {
  searchText.value = "";
  Object.assign(state, { search: "", filters: {}, page: 1 });
}

/** Paginador separado da tabela: trabalha com `first` (índice da 1ª linha) e `rows`. */
const first = computed({
  get: () => (state.page - 1) * state.pageSize,
  set: (value: number) => (state.page = Math.floor(value / state.pageSize) + 1),
});
function onPage(event: PageState) {
  state.pageSize = event.rows;
  state.page = event.page + 1;
}

/** Mesmo evento para a tabela e a árvore: só o campo e a direção importam. */
function onSort(event: { sortField?: DataTableSortEvent["sortField"] | ((item: unknown) => string); sortOrder?: number | null }) {
  state.ordering = event.sortField ? `${event.sortOrder === -1 ? "-" : ""}${String(event.sortField)}` : "";
  state.page = 1;
}
/** Ordem atual devolvida à tabela (mostra a seta certa no cabeçalho). */
const sortField = computed(() => state.ordering.replace(/^-/, "") || undefined);
const sortOrder = computed(() => (state.ordering.startsWith("-") ? -1 : state.ordering ? 1 : 0));

const numeric = (type?: string) => ["money", "quantity", "percent"].includes(type ?? "");
/** Largura mínima por tipo: no celular a tabela rola para o lado em vez de espremer. */
const minWidth = (type?: string) => (type === "image" ? "56px" : type === "boolean" || type === "tag" ? "110px"
  : numeric(type) ? "120px" : "160px");
const searchable = computed(() => resource.value.searchable !== false);
/** A coluna que dá nome à linha (ex.: "Nome") sai em negrito, como título. */
const titleKey = computed(() => {
  const columns = resource.value.columns;
  return (columns.find((c) => c.title) ?? columns.find((c) => c.key === "name") ?? columns[0])?.key;
});
const bodyClass = (column: ColumnDef) => [numeric(column.type) ? "right" : "", column.key === titleKey.value ? "cell-title" : ""].join(" ");
const headerClass = (column: ColumnDef) => (numeric(column.type) ? "right" : column.key === titleKey.value ? "cell-title" : "");
const open = (id?: string) => router.push(`/cadastros/${resource.value.name}/${id ?? "novo"}`);
/** Menu "⋯" da linha: abrir, as consultas do cadastro, ações extras e excluir. */
const notify = useNotify();
const confirmDialog = useConfirm();
const rowMenu = ref<InstanceType<typeof Menu>>();
const menuRow = ref<Row | null>(null);
const rowMenuItems = computed(() => {
  const row = menuRow.value;
  if (!row) return [];
  const base = `/cadastros/${resource.value.name}/${row.id}`;
  const items: Record<string, unknown>[] = [
    { label: canWrite.value && resource.value.editable !== false ? "Abrir / editar" : "Abrir", icon: "pi pi-external-link",
      command: () => openRow(row) },
  ];
  const views = (resource.value.views ?? []).filter((v) => session.can(v.permission) && session.hasModule(v.module));
  if (views.length) {
    items.push({ separator: true });
    views.forEach((v) => items.push({ label: v.label, icon: v.icon, command: () => router.push(`${base}/${v.name}`) }));
  }
  const extra = (resource.value.rowActions ?? []).filter((a) => session.can(a.permission) && (!a.visible || a.visible(row)));
  if (extra.length) {
    items.push({ separator: true });
    extra.forEach((a) => items.push({ label: a.label, icon: a.icon, class: a.danger ? "menu-danger" : undefined,
                                      command: () => runRowAction(a, row) }));
  }
  if (canWrite.value && resource.value.deletable !== false && !locked.value) {
    items.push({ separator: true }, { label: "Excluir", icon: "pi pi-trash", class: "menu-danger", command: () => removeRow(row) });
  }
  return items;
});
function toggleRowMenu(event: Event, row: Row) {
  menuRow.value = row;
  rowMenu.value?.toggle(event);
}
async function runRowAction(action: NonNullable<ResourceDef["rowActions"]>[number], row: Row) {
  if (action.to) return void router.push(action.to(row));
  const go = async () => {
    try {
      await action.run?.(row);
      if (action.success) notify.success(action.success);
      void refetch();
    } catch (error) {
      notify.error(error, `Não foi possível: ${action.label.toLowerCase()}`);
    }
  };
  if (!action.confirm) return void go();
  confirmDialog.require({ header: action.label, message: action.confirm, icon: "pi pi-exclamation-triangle",
                          acceptProps: { label: action.label, severity: action.danger ? "danger" : undefined },
                          rejectProps: { label: "Voltar", severity: "secondary", outlined: true }, accept: go });
}
function removeRow(row: Row) {
  confirmDialog.require({
    header: "Confirmar exclusão", icon: "pi pi-exclamation-triangle",
    message: `Excluir este ${resource.value.singular}? A ação fica registrada na auditoria.`,
    acceptProps: { label: "Excluir", severity: "danger" }, rejectProps: { label: "Cancelar", severity: "secondary", outlined: true },
    accept: async () => {
      try {
        await resourceApi.remove(resource.value.endpoint, String(row.id));
        notify.success("Excluído");
        void refetch();
      } catch (error) {
        notify.error(error, "Não foi possível excluir");
      }
    },
  });
}

/** Imprime a lista como está na tela (mesma busca, filtros e ordem). */
function printList() {
  const query = Object.fromEntries(Object.entries({ search: state.search, ordering: state.ordering, ...state.filters })
    .map(([k, v]) => [k, v === null || v === undefined ? "" : String(v)]));
  openPrint("lista", resource.value.name, query);
}

function openRow(row: Row) {
  const link = resource.value.rowLink?.(row);
  if (link) router.push(link);
  else open(String(row.id));
}
const warm = (row: Row) => prefetch.detail(resource.value, String(row.id));
/** Passar o mouse na linha baixa o registro antes do clique. */
const rowPt = ({ context }: { context: { index: number } }) => ({
  onMouseenter: () => {
    const row = rows.value[context.index];
    if (row) warm(row);
  },
});
const rowClass = (row: Row) => (selection.isSelected(String(row.id)) ? "row-selected" : "");

/*
 * Árvore (`resource.tree`): cada linha pode abrir e mostrar o que tem dentro.
 * Os filhos são buscados na 1ª vez que a linha abre e ficam guardados até a
 * lista mudar (página, busca, ordem). Linha filha não tem caixa de marcar nem "⋯".
 */
type Kind = "same" | "child";
const tree = computed(() => resource.value.tree);
const childRows = ref<Record<string, Row[]>>({});
const expandedKeys = ref<Record<string, boolean>>({});
const loadingKeys = ref(new Set<string>());
const selectedKeys = ref<Record<string, boolean>>({});
// Só quando as linhas mudam de verdade (página, busca, ordem): atualizar em segundo plano não fecha nada.
watch(() => rows.value.map((row) => row.id).join(), () => {
  childRows.value = {};
  expandedKeys.value = {};
});
const kindOf = (row: Row) => row.__kind as Kind | undefined;
function expandable(row: Row) {
  if (kindOf(row) === "child") return false;
  return tree.value?.hasChildren ? tree.value.hasChildren(row) : Number(row.children_count ?? 0) > 0;
}
function build(row: Row, key: string): TreeNode {
  const kids = childRows.value[key];
  return { key, data: row, leaf: !expandable(row),
           children: kids?.map((child, index) => build(child, `${key}/${String(child.id ?? index)}`)) };
}
const nodes = computed(() => rows.value.map((row) => build(row, String(row.id))));
async function onExpand(node: TreeNode) {
  const key = String(node.key);
  if (childRows.value[key] || !tree.value) return;
  loadingKeys.value = new Set([...loadingKeys.value, key]);
  try {
    const parent = node.data as Row;
    const found = tree.value.parent
      ? (await resourceApi.list(resource.value.endpoint, { parent: String(parent.id), page_size: 200,
                                                          ordering: state.ordering || resource.value.ordering })).results
      : await tree.value.children!(parent);
    childRows.value = { ...childRows.value,
                        [key]: found.map((child) => ({ ...child, __kind: tree.value!.parent ? "same" : "child", __parent: parent }) as unknown as Row) };
  } catch (error) {
    notify.error(error, "Não foi possível abrir a linha");
    expandedKeys.value = { ...expandedKeys.value, [key]: false };
  } finally {
    loadingKeys.value = new Set([...loadingKeys.value].filter((k) => k !== key));
  }
}
/** Clique na linha: abre o registro (a linha filha leva ao `childLink` ou ao pai). */
function onNodeSelect(node: TreeNode) {
  selectedKeys.value = {};
  const row = node.data as Row;
  if (kindOf(row) !== "child") return openRow(row);
  const link = tree.value?.childLink?.(row, row.__parent as Row);
  if (link) router.push(link);
  else openRow(row.__parent as Row);
}
const childValue = (row: Row, column: ColumnDef) => (kindOf(row) === "child" && !(column.key in row) ? undefined : row[column.key]);

/** Larguras variadas no skeleton: parece a tabela de verdade, não uma lista de barras. */
const widths = ["70%", "85%", "55%", "40%", "65%", "50%"];

function onKey(event: KeyboardEvent) {
  const typing = (event.target as HTMLElement).closest("input, textarea, [contenteditable], .p-select, .p-dialog");
  if (typing || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "/") {
    event.preventDefault();
    searchBox.value?.$el.querySelector("input")?.focus();
  } else if (event.key.toLowerCase() === "n" && canCreate.value) {
    event.preventDefault();
    open();
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <section class="page page--list">
    <header class="head">
      <div>
        <h1>{{ resource.title }}</h1>
        <p>
          <Skeleton v-if="pending" width="5rem" height="0.75rem" class="inline" />
          <template v-else>{{ total }} {{ total === 1 ? "registro" : "registros" }}</template>
        </p>
      </div>
      <FormActions v-if="resource.listActions?.length" :actions="resource.listActions" :ctx="listCtx" class="head__actions" />
      <Button v-if="drafts.length" :label="drafts.length === 1 ? '1 rascunho' : `${drafts.length} rascunhos`" icon="pi pi-bookmark"
              severity="warn" outlined size="small" :class="{ head__actions: !resource.listActions?.length }"
              aria-haspopup="true" @click="draftMenu?.toggle($event)" />
      <Menu ref="draftMenu" :model="draftItems" popup />
      <Button v-if="canCreate" icon="pi pi-plus" :label="newLabel(resource)" size="small" title="Atalho: N" @click="open()" />
    </header>

    <p v-if="locked" class="system-note">
      <i class="pi pi-lock" /> {{ resource.systemNote ?? "Cadastro do sistema: já vem pronto com a conta. Você pode ajustar "
        + "(ativar, taxa, prazo), mas criar ou excluir é feito pelo suporte." }}
    </p>

    <div class="table-card">
      <BulkBar v-if="selection.count.value > 0" :resource="resource" :count="selection.count.value" :total="total"
               :all="selection.all.value" :target="selection.target"
               :filters="listFilters" @select-all="selection.selectAll" @clear="selection.clear" @done="afterBulk" />
      <div v-else class="toolbar">
        <IconField v-if="searchable" ref="searchBox" class="search">
          <InputIcon class="pi pi-search" />
          <InputText v-model="searchText" placeholder="Buscar…  ( / )" size="small" fluid />
        </IconField>
        <Button v-if="isPhone && resource.filters?.length" :label="activeFilters ? `Filtros (${activeFilters})` : 'Filtros'"
                icon="pi pi-sliders-h" size="small" :severity="activeFilters ? undefined : 'secondary'" outlined
                class="filters-toggle" :aria-expanded="filtersOpen" @click="filtersOpen = !filtersOpen" />
        <template v-for="filter in !isPhone || filtersOpen ? resource.filters ?? [] : []" :key="filter.name">
          <DatePicker v-if="filter.type === 'daterange'" :model-value="rangeOf(filter.name)" selection-mode="range"
                      :manual-input="false" date-format="dd/mm/yy" :placeholder="filter.label" show-icon show-button-bar
                      size="small" class="filter filter--date" @update:model-value="setRange(filter.name, $event)" />
          <RelationSelect v-else-if="filter.type === 'relation'" :model-value="state.filters[filter.name]"
                          :relation="filter.relation!" :placeholder="filter.label" class="filter" size="small"
                          @update:model-value="setFilter(filter.name, $event)" />
          <Select v-else :model-value="state.filters[filter.name]" :options="filter.options" option-label="label"
                  option-value="value" :placeholder="filter.label" show-clear class="filter" size="small"
                  @update:model-value="setFilter(filter.name, $event)" />
        </template>
        <span v-for="[key] in hiddenFilters" :key="key" class="chip">
          <i class="pi pi-filter" /> Filtrado: {{ FILTER_NAMES[key] ?? key.replace(/__/g, " ").replace(/_/g, " ") }}
          <button type="button" aria-label="Tirar filtro" @click="dropFilter(key)"><i class="pi pi-times" /></button>
        </span>
        <div class="toolbar__end">
          <Button icon="pi pi-print" text rounded size="small" severity="secondary" aria-label="Imprimir lista" title="Imprimir lista"
                  @click="printList" />
          <Button v-if="hasFilters" label="Limpar" icon="pi pi-filter-slash" text size="small" severity="secondary" @click="clearFilters" />
          <Button icon="pi pi-refresh" text rounded size="small" severity="secondary" aria-label="Atualizar" :loading="loading && !pending"
                  @click="refetch()" />
        </div>
      </div>

      <div v-if="pending && isPhone" class="body">
        <div v-for="n in 6" :key="n" class="ghost-card">
          <Skeleton width="60%" height="1rem" /><Skeleton width="35%" height="0.8rem" />
          <div class="ghost-card__grid"><Skeleton height="0.8rem" /><Skeleton height="0.8rem" /></div>
        </div>
      </div>
      <div v-else-if="isPhone" :class="['body', { refreshing: loading }]">
        <MobileCards v-if="rows.length" :rows="rows" :columns="resource.columns" :title-key="titleKey"
                     :selected="(id) => selection.isSelected(id)" :selecting="selection.count.value > 0"
                     @open="openRow" @toggle="selection.toggle" @menu="toggleRowMenu" @warm="warm" />
        <EmptyState v-else :title="hasFilters ? 'Nada encontrado com esses filtros' : `Nenhum ${resource.singular} ainda`"
                    :description="hasFilters ? 'Tente outra busca ou limpe os filtros.' : 'Os registros aparecem aqui assim que forem criados.'"
                    :icon="hasFilters ? 'pi pi-search' : resource.icon">
          <Button v-if="!hasFilters && canCreate" :label="newLabel(resource)" icon="pi pi-plus" size="small" @click="open()" />
        </EmptyState>
      </div>
      <div v-else-if="pending" class="body">
      <table class="ghost" aria-busy="true" aria-label="Carregando">
        <thead><tr><th class="check" /><th v-for="column in resource.columns" :key="column.key">{{ column.label }}</th></tr></thead>
        <tbody>
          <tr v-for="n in 12" :key="n">
            <td class="check"><Skeleton width="16px" height="16px" border-radius="4px" /></td>
            <td v-for="(column, index) in resource.columns" :key="column.key" :class="{ right: numeric(column.type) }">
              <Skeleton :width="widths[(n + index) % widths.length]" height="0.8rem" />
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <TreeTable v-else-if="tree" v-model:expanded-keys="expandedKeys" v-model:selection-keys="selectedKeys" :value="nodes" lazy
                 selection-mode="single" :class="['body', 'tree', { refreshing: loading }]" row-hover removable-sort scrollable
                 scroll-height="flex" size="small" :sort-field="sortField" :sort-order="sortOrder" @sort="onSort"
                 @node-expand="onExpand" @node-select="onNodeSelect">
        <template #empty>
          <EmptyState :title="hasFilters ? 'Nada encontrado com esses filtros' : `Nenhum ${resource.singular} ainda`"
                      :description="hasFilters ? 'Tente outra busca ou limpe os filtros.' : 'Os registros aparecem aqui assim que forem criados.'"
                      :icon="hasFilters ? 'pi pi-search' : resource.icon">
            <Button v-if="!hasFilters && canCreate" :label="newLabel(resource)" icon="pi pi-plus" size="small" @click="open()" />
          </EmptyState>
        </template>
        <Column header-class="check" body-class="check">
          <template #header>
            <button type="button" class="check-all" :class="`check-all--${selection.header.value}`" :title="headerTitle"
                    :aria-label="headerTitle" @click.stop="selection.cycleHeader">
              <Checkbox :model-value="['page', 'all'].includes(selection.header.value)" binary :tabindex="-1"
                        :indeterminate="selection.header.value === 'partial'" />
            </button>
          </template>
          <template #body="{ node }">
            <span v-if="!kindOf(node.data)" class="check-cell" @click.stop>
              <Checkbox :model-value="selection.isSelected(String(node.data.id))" binary :aria-label="`Marcar ${node.data.name ?? ''}`"
                        @update:model-value="selection.toggle(String(node.data.id))" />
            </span>
          </template>
        </Column>
        <Column v-for="column in resource.columns" :key="column.key" :field="column.key" :header="column.label"
                :expander="column.key === titleKey" :sortable="column.sortable !== false" :sort-field="column.key"
                :header-class="headerClass(column)" :body-class="bodyClass(column)"
                :style="{ minWidth: column.width ?? (column.key === titleKey ? '240px' : minWidth(column.type)) }">
          <template #body="{ node }">
            <span :class="{ 'tree-child': kindOf(node.data) === 'child' }">
              <i v-if="column.key === titleKey && loadingKeys.has(String(node.key))" class="pi pi-spin pi-spinner tree-loading" />
              <CellValue v-if="childValue(node.data, column) !== undefined" :column="column" :value="childValue(node.data, column)" />
            </span>
          </template>
        </Column>
        <Column header-style="width: 3rem" body-class="row-menu-cell">
          <template #body="{ node }">
            <button v-if="kindOf(node.data) !== 'child'" type="button" class="row-menu" aria-label="Ações da linha" aria-haspopup="true"
                    @click.stop="toggleRowMenu($event, node.data)"><i class="pi pi-ellipsis-h" /></button>
          </template>
        </Column>
      </TreeTable>
      <DataTable v-else :value="rows" :loading="false" lazy :rows="state.pageSize" :class="['body', { refreshing: loading }]"
                 data-key="id" row-hover removable-sort scrollable scroll-height="flex" size="small"
                 :sort-field="sortField" :sort-order="sortOrder" :row-class="rowClass"
                 :pt="{ bodyRow: rowPt }" @sort="onSort" @row-click="openRow($event.data)">
        <template #empty>
          <EmptyState :title="hasFilters ? 'Nada encontrado com esses filtros' : `Nenhum ${resource.singular} ainda`"
                      :description="hasFilters ? 'Tente outra busca ou limpe os filtros.' : 'Os registros aparecem aqui assim que forem criados.'"
                      :icon="hasFilters ? 'pi pi-search' : resource.icon">
            <Button v-if="!hasFilters && canCreate" :label="newLabel(resource)" icon="pi pi-plus" size="small"
                    @click="open()" />
          </EmptyState>
        </template>
        <Column header-class="check" body-class="check">
          <template #header>
            <button type="button" class="check-all" :class="`check-all--${selection.header.value}`" :title="headerTitle"
                    :aria-label="headerTitle" @click="selection.cycleHeader">
              <Checkbox :model-value="['page', 'all'].includes(selection.header.value)" binary :tabindex="-1"
                        :indeterminate="selection.header.value === 'partial'" />
            </button>
          </template>
          <template #body="{ data }">
            <span class="check-cell" @click.stop>
              <Checkbox :model-value="selection.isSelected(String(data.id))" binary :aria-label="`Marcar ${data.name ?? ''}`"
                        @update:model-value="selection.toggle(String(data.id))" />
            </span>
          </template>
        </Column>
        <Column v-for="column in resource.columns" :key="column.key" :field="column.key" :header="column.label"
                :sortable="column.sortable !== false" :sort-field="column.key" :header-class="numeric(column.type) ? 'right' : ''"
                :body-class="bodyClass(column)" :style="{ minWidth: minWidth(column.type) }">
          <template #body="{ data }"><CellValue :column="column" :value="data[column.key]" /></template>
        </Column>
        <Column header-style="width: 3rem" body-class="row-menu-cell">
          <template #body="{ data }">
            <button type="button" class="row-menu" aria-label="Ações da linha" aria-haspopup="true"
                    @click.stop="toggleRowMenu($event, data)"><i class="pi pi-ellipsis-h" /></button>
          </template>
        </Column>
      </DataTable>

      <Menu ref="rowMenu" :model="rowMenuItems" popup />

      <div class="pager">
        <Paginator v-if="isPhone" v-model:first="first" v-model:rows="state.pageSize" :total-records="total"
                   template="FirstPageLink PrevPageLink CurrentPageReport NextPageLink LastPageLink"
                   current-page-report-template="{first}–{last} de {totalRecords}" @page="onPage" />
        <Paginator v-else v-model:first="first" v-model:rows="state.pageSize" :total-records="total"
                   :rows-per-page-options="[10, 20, 30]" @page="onPage" />
        <span v-if="total" class="pager__info">{{ first + 1 }}–{{ Math.min(first + state.pageSize, total) }} de {{ total }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; }
.head__actions { margin-left: auto; }
.system-note {
  margin: 0; display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px; font-size: 13px;
  background: var(--info-subtle); color: var(--info-text);
}
h1 { font: 700 19px/1.2 var(--font-sans); letter-spacing: -0.01em; }
.head p { margin-top: 2px; font-size: 12.5px; color: var(--text-muted); min-height: 1.1rem; }
.inline { display: inline-block; vertical-align: middle; }
/* Lista ocupa a largura toda e a altura da tela (menos a barra de cima). */
.page--list { max-width: none; width: 100%; height: calc(100dvh - var(--topbar-h)); min-height: 480px; }
.table-card {
  flex: 1; min-height: 0; display: flex; flex-direction: column;
  background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow-xs); overflow: hidden;
}
/* O corpo estica e rola por dentro; cabeçalho da tabela e paginação ficam no lugar. */
.body { flex: 1; min-height: 0; overflow: auto; }
.body:deep(.p-datatable-table-container) { height: 100%; }
/* Árvore: mesmo visual da tabela; filho com fundo leve e recuado pelo próprio TreeTable. */
.tree:deep(.p-treetable-table-container) { height: 100%; }
.tree :deep(.p-treetable-thead > tr > th) {
  position: sticky; top: 0; z-index: 1; height: 46px; background: var(--surface-sunken); color: var(--text-muted);
  font: 650 12px/1.3 var(--font-sans); letter-spacing: 0.04em; text-transform: uppercase; white-space: nowrap; border-color: var(--border);
}
.tree :deep(.p-treetable-tbody > tr) { cursor: pointer; }
.tree :deep(.p-treetable-tbody > tr > td) { padding-block: 0.7rem; border-color: var(--border-subtle); color: var(--text-body); font-size: 14px; }
.tree :deep(.p-treetable-tbody > tr[aria-level="2"]),
.tree :deep(.p-treetable-tbody > tr[aria-level="3"]) { background: color-mix(in srgb, var(--surface-sunken) 60%, var(--surface-card)); }
.tree :deep(.p-treetable-tbody > tr[aria-level="2"] > td),
.tree :deep(.p-treetable-tbody > tr[aria-level="3"] > td) { padding-block: 0.5rem; font-size: 13.5px; }
.tree :deep(.p-treetable-column-sorted) { color: var(--text-brand); background: var(--brand-subtle); }
.tree :deep(.p-treetable-sort-icon) { width: 11px; height: 11px; margin-left: 6px; color: var(--text-subtle); }
.tree :deep(.p-treetable-node-toggle-button) { width: 1.6rem; height: 1.6rem; margin-right: 0.35rem; }
/* O título da coluna principal recua o espaço da seta de expandir (+ o gap do PrimeVue), para alinhar com o texto das linhas. */
.tree :deep(th.cell-title .p-treetable-column-header-content) { padding-left: calc(1.6rem + 0.35rem + 0.5rem); }
.tree :deep(.p-treetable-body-cell-content) { display: flex; align-items: center; }
.tree-child :deep(.cell) { color: var(--text-body); font-weight: 500; }
.tree-loading { font-size: 12px; margin-right: 6px; color: var(--text-muted); }
.body :deep(.p-datatable-thead > tr > th) { position: sticky; top: 0; z-index: 1; }
.pager { position: relative; display: flex; justify-content: center; align-items: center; border-top: 1px solid var(--border-subtle); }
.pager :deep(.p-paginator) { background: transparent; padding: 6px 8px; }
.pager__info { position: absolute; right: 14px; font-size: 12px; color: var(--text-muted); }
.toolbar { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); }
.search { flex: 1 1 220px; max-width: 320px; }
.filter { min-width: 160px; }
.filter--date { width: 230px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 4px 0 10px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface-sunken); font-size: 12.5px; color: var(--text-strong);
}
.chip i { font-size: 11px; color: var(--text-muted); }
.chip button { display: grid; place-items: center; width: 22px; height: 22px; border: 0; border-radius: 50%; background: transparent; cursor: pointer; }
.chip button:hover { background: var(--surface-hover); }
.toolbar__end { margin-left: auto; display: flex; gap: 2px; }
.ghost { width: 100%; border-collapse: collapse; font-size: 13px; }
.ghost th { position: sticky; top: 0; text-align: left; padding: 0.55rem 0.9rem; background: var(--surface-sunken); color: var(--text-subtle); font: 700 11px/1.2 var(--font-sans); letter-spacing: 0.06em; text-transform: uppercase; border-bottom: 1px solid var(--border); }
.ghost td { padding: 0.75rem 0.9rem; border-bottom: 1px solid var(--border-subtle); }
.ghost td.right :deep(.p-skeleton) { margin-left: auto; }
/* Recarregando com dados na tela: só esmaece, sem trocar por spinner. */
.refreshing :deep(.p-datatable-tbody) { opacity: 0.55; transition: opacity var(--dur-base) ease; }
:deep(.p-datatable-tbody > tr) { cursor: pointer; }
:deep(.p-datatable-tbody > tr > td) { padding-block: 0.7rem; }
:deep(.cell-title) { font-weight: 600; color: var(--text-strong); }
/* Coluna de seleção */
:deep(.check) { width: 3rem; min-width: 3rem; padding-inline: 0.9rem 0.25rem; }
.check-all { position: relative; display: inline-flex; align-items: center; border: 0; padding: 0; background: transparent; cursor: pointer; }
.check-all :deep(.p-checkbox) { pointer-events: none; }
/* "Todos os registros" (não só a página): anel em volta do checkbox; a barra diz quantos. */
.check-all--all :deep(.p-checkbox-box) { box-shadow: 0 0 0 3px var(--brand-subtle-2); }
.check-cell { display: inline-flex; padding: 4px; margin: -4px; cursor: default; }
:deep(.p-datatable-tbody > tr.row-selected) { background: var(--brand-subtle); }
:deep(.p-datatable-tbody > tr.row-selected > td) { border-color: var(--brand-border); }
.ghost td { padding-block: 0.85rem; }
:deep(.right) { text-align: right; justify-content: flex-end; }
.row-arrow { color: var(--text-subtle); font-size: 11px; opacity: 0; transition: opacity var(--dur-fast) ease; }
:deep(.p-datatable-tbody > tr:hover) .row-arrow { opacity: 1; color: var(--brand); }
.row-menu {
  width: 30px; height: 30px; display: grid; place-items: center; border: 1px solid transparent; border-radius: 7px;
  background: transparent; color: var(--text-muted); cursor: pointer; transition: background-color var(--dur-fast) ease, color var(--dur-fast) ease;
}
.row-menu:hover { background: var(--surface-active); color: var(--text-strong); border-color: var(--border); }
:deep(.p-datatable-tbody > tr:hover) .row-menu { color: var(--text-strong); }
.ghost-card { display: flex; flex-direction: column; gap: 8px; margin: 8px; padding: 14px 12px; border: 1px solid var(--border);
              border-radius: 12px; }
.ghost-card__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 4px; }
@media (max-width: 760px) {
  .search { max-width: none; flex-basis: 100%; }
  .filter { flex: 1 1 140px; min-width: 0; }
  .pager__info { display: none; }
  .page--list { height: calc(100dvh - var(--topbar-h)); }
}
@media (max-width: 640px) {
  /* Celular: a lista encosta nas bordas e o cabeçalho fica compacto. */
  .page--list { gap: 10px; }
  .head { align-items: center; }
  .head h1 { font-size: 18px; }
  .table-card { border-radius: 12px; }
  .toolbar { padding: 8px; gap: 6px; }
  .search { flex: 1 1 0; min-width: 0; }
  .filter, .filter--date { flex: 1 1 100%; width: 100%; }
  .toolbar__end { margin-left: 0; }
  .body { background: var(--surface-sunken); }
  .pager :deep(.p-paginator) { padding: 4px; }
  .pager :deep(.p-paginator-current) { font-size: 12.5px; }
}
</style>
