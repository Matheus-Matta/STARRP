<script setup lang="ts">
/**
 * Tabela do relatório (a "visão em tabela" de todo gráfico): ordena por coluna, pagina
 * (25, 50 ou 100 por página) e exporta Excel ou CSV (gerados no servidor) com TODAS as linhas da aba.
 * `tabs` (ex.: Curva ABC por classe): abas Todas / A / B / C com a contagem e a soma de cada uma;
 * a tabela e a exportação levam só a aba aberta (arquivo "...-classe-a.csv").
 */
import Button from "primevue/button";
import Paginator, { type PageState } from "primevue/paginator";
import { computed, ref, watch } from "vue";

import { fmt, type Format } from "./chart";

type Column = { key: string; label: string; format?: Format };
/** `order`: a ordem (e portanto a cor) das abas, igual à do gráfico; sem ela, alfabética. */
type Tabs = { key: string; label: string; sum?: string; order?: string[] };
const props = defineProps<{ columns: Column[]; rows: Record<string, unknown>[]; title: string; tabs?: Tabs; empty?: string;
                            onExport?: (format: "xlsx" | "csv", tab: string | null) => Promise<void> }>();
const tab = ref<string | null>(null);
const sumColumn = computed(() => props.columns.find((c) => c.key === props.tabs?.sum));
const tabList = computed(() => {
  if (!props.tabs) return [];
  const key = props.tabs.key;
  const found = [...new Set(props.rows.map((r) => String(r[key] ?? "")))];
  const values = props.tabs.order ? [...props.tabs.order.filter((v) => found.includes(v)), ...found.filter((v) => !props.tabs!.order!.includes(v))]
    : found.sort((a, b) => a.localeCompare(b, "pt-BR"));
  const summary = (rows: Record<string, unknown>[]) => ({
    count: rows.length, sum: props.tabs?.sum ? rows.reduce((t, r) => t + Number(r[props.tabs!.sum!] ?? 0), 0) : null,
  });
  return [{ value: null, label: "Todas", ...summary(props.rows) },
          ...values.map((v) => ({ value: v, label: `${props.tabs!.label} ${v}`.trim(), ...summary(props.rows.filter((r) => String(r[key]) === v)) }))];
});
const base = computed(() => (props.tabs && tab.value !== null
  ? props.rows.filter((r) => String(r[props.tabs!.key]) === tab.value) : props.rows));
const sortKey = ref<string | null>(null);
const sortDir = ref<1 | -1>(-1);
const first = ref(0);
const perPage = ref(25);
const numeric = (c: Column) => ["money", "number", "decimal", "quantity", "percent"].includes(c.format ?? "");

const sorted = computed(() => {
  if (!sortKey.value) return base.value;
  const key = sortKey.value;
  const col = props.columns.find((c) => c.key === key);
  return [...base.value].sort((a, b) => {
    const [x, y] = [a[key], b[key]];
    const cmp = col && numeric(col) ? Number(x) - Number(y) : String(x ?? "").localeCompare(String(y ?? ""), "pt-BR");
    return cmp * sortDir.value;
  });
});
const shown = computed(() => sorted.value.slice(first.value, first.value + perPage.value));
function onPage(event: PageState) {
  first.value = event.first;
  perPage.value = event.rows;
}
watch([tab, () => props.rows], () => (first.value = 0));

function sortBy(col: Column) {
  first.value = 0;
  if (sortKey.value === col.key) sortDir.value = sortDir.value === 1 ? -1 : 1;
  else {
    sortKey.value = col.key;
    sortDir.value = numeric(col) ? -1 : 1;
  }
}

/** Exportar fica com a tela (sabe o relatório e os filtros): aqui só diz o formato e a aba aberta. */
const exporting = ref<"xlsx" | "csv" | null>(null);
async function exportAs(format: "xlsx" | "csv") {
  exporting.value = format;
  try {
    await props.onExport?.(format, tab.value);
  } finally {
    exporting.value = null;
  }
}
</script>

<template>
  <div class="rtable">
    <div v-if="tabList.length" class="rtabs" role="tablist">
      <button v-for="(t, i) in tabList" :key="String(t.value)" type="button" role="tab" class="rtab"
              :class="{ active: tab === t.value }" :aria-selected="tab === t.value"
              :style="t.value !== null ? { '--tab': `var(--series-${i})` } : undefined" @click="tab = t.value">
        <span v-if="t.value !== null" class="rtab__dot" />
        <strong>{{ t.label }}</strong>
        <span class="rtab__meta">{{ t.count }} {{ t.count === 1 ? "item" : "itens" }}<template v-if="t.sum !== null && sumColumn">
          · {{ fmt(t.sum, sumColumn.format) }}</template></span>
      </button>
    </div>
    <div class="rtable__bar">
      <span class="muted">{{ base.length }} {{ base.length === 1 ? "linha" : "linhas" }}</span>
      <span class="rtable__export">
        <span class="muted">{{ tabs && tab !== null ? `Exportar ${tabs.label} ${tab}:` : "Exportar:" }}</span>
        <Button label="Excel" icon="pi pi-file-excel" text size="small" :disabled="!base.length || !onExport"
                :loading="exporting === 'xlsx'" @click="exportAs('xlsx')" />
        <Button label="CSV" icon="pi pi-file" text size="small" :disabled="!base.length || !onExport"
                :loading="exporting === 'csv'" @click="exportAs('csv')" />
      </span>
    </div>
    <p v-if="!base.length" class="empty">{{ empty ?? "Sem dados no período." }}</p>
    <div v-else class="rtable__scroll">
      <table>
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.key" :class="{ r: numeric(c) }" :aria-sort="sortKey === c.key ? (sortDir === 1 ? 'ascending' : 'descending') : 'none'">
              <button type="button" @click="sortBy(c)">
                {{ c.label }}
                <i :class="sortKey === c.key ? (sortDir === 1 ? 'pi pi-sort-up-fill' : 'pi pi-sort-down-fill') : 'pi pi-sort'" />
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in shown" :key="i" :class="{ strong: row.strong }">
            <td v-for="c in columns" :key="c.key" :class="{ r: numeric(c), neg: numeric(c) && Number(row[c.key]) < 0 }">
              {{ fmt(row[c.key], c.format ?? "text") }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="base.length > 25" class="pager">
      <Paginator :first="first" :rows="perPage" :total-records="base.length" :rows-per-page-options="[25, 50, 100]"
                 template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
                 current-page-report-template="{first}–{last} de {totalRecords}" @page="onPage" />
    </div>
  </div>
</template>

<style scoped>
.rtabs { display: flex; gap: 6px; flex-wrap: wrap; margin: -4px 0 12px; }
.rtab { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 8px 12px; min-width: 120px; cursor: pointer;
        border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); text-align: left;
        transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease; }
.rtab strong { display: flex; align-items: center; gap: 6px; font: 700 13px var(--font-sans); color: var(--text-strong); }
.rtab:hover { border-color: var(--border-strong, var(--text-subtle)); }
.rtab.active { border-color: var(--tab, var(--brand)); box-shadow: 0 0 0 1px var(--tab, var(--brand)); background: var(--surface-sunken); }
.rtab__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tab); display: inline-block; margin-right: -2px; }
.rtab { position: relative; padding-right: 26px; }
.rtab .rtab__dot { position: absolute; top: 12px; right: 10px; }
.rtab__meta { font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.rtable__export { display: inline-flex; align-items: center; gap: 2px; }
.rtable__bar { display: flex; justify-content: space-between; align-items: center; margin: -6px 0 6px; font-size: 12px; }
.rtable__scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 0; background: var(--surface-sunken); border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
th button { width: 100%; display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border: 0; background: transparent;
            font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); cursor: pointer; }
th.r button { flex-direction: row-reverse; justify-content: flex-start; } /* ícone antes: o título termina junto dos números */
th button i { font-size: 9px; opacity: 0.6; }
td { padding: 9px 12px; border-bottom: 1px solid var(--border-subtle); color: var(--text-body); }
td.r { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.neg { color: var(--danger-text); }
tr.strong td { font-weight: 700; color: var(--text-strong); background: var(--surface-sunken); }
tbody tr:hover td { background: var(--surface-hover); }
.pager { margin-top: 8px; border-top: 1px solid var(--border-subtle); }
.pager :deep(.p-paginator) { background: transparent; padding: 6px 0 0; flex-wrap: wrap; }
.pager :deep(.p-paginator-current) { font-size: 12px; color: var(--text-muted); }
.empty { margin: 0; color: var(--text-muted); font-size: 13px; }
</style>
