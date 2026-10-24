<script setup lang="ts">
/**
 * Qualquer lista impressa (`/imprimir/lista/<cadastro>?filtros...`): as mesmas colunas,
 * filtros e ordem da tela, até 2.000 linhas, com os filtros usados no subtítulo.
 * Também serve para as consultas do registro (`?view=<consulta>&registro=<id>`).
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

import { resourceApi, type Row } from "@/api/resource";
import { findResource } from "@/resources";
import type { ColumnDef } from "@/resources/types";

import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const route = useRoute();
const resource = findResource(props.id);
const view = resource?.views?.find((v) => v.name === route.query.view);
const format = ref<PrintFormat>(props.initialFormat ?? ((view?.list?.columns ?? resource?.columns ?? []).length > 5 ? "a4-landscape" : "a4"));

const RESERVED = new Set(["auto", "view", "registro", "titulo", "formato"]);
const filters = computed(() => Object.fromEntries(Object.entries(route.query)
  .filter(([k, v]) => !RESERVED.has(k) && typeof v === "string" && v !== "") as [string, string][]));
const endpoint = view?.list?.endpoint ?? resource?.endpoint ?? "";
const columns: ColumnDef[] = view?.list?.columns ?? resource?.columns ?? [];
const fixed = view?.list ? view.list.params(String(route.query.registro), {}) : { ...resource?.params };

async function loadAll() {
  const rows: Row[] = [];
  for (let page = 1; rows.length < 2000; page++) {
    const chunk = await resourceApi.list(endpoint, { ...fixed, ...filters.value, page, page_size: 200 });
    rows.push(...chunk.results);
    if (!chunk.next) break;
  }
  return rows;
}
const query = useQuery({ queryKey: ["print-list", endpoint, fixed, filters.value], queryFn: loadAll, enabled: Boolean(endpoint) });
const rows = computed(() => query.data.value ?? []);

const title = computed(() => String(route.query.titulo ?? (view ? `${resource?.title} · ${view.label}` : resource?.title ?? "Lista")));
const NAMES: Record<string, string> = { search: "busca", ordering: "ordem" };
const subtitle = computed(() => {
  const used = Object.entries(filters.value).filter(([k]) => k !== "ordering");
  const text = used.map(([k, v]) => `${NAMES[k] ?? k.replace(/__/g, " ").replace(/_/g, " ")}: ${v}`).join(" · ");
  return `${rows.value.length} registro(s)${text ? ` · ${text}` : ""}${rows.value.length >= 2000 ? " · limitado a 2.000" : ""}`;
});
/** Soma só as colunas marcadas como totalizáveis (`total: true`): preço unitário não se soma. */
const totals = computed(() => {
  const sums = columns.filter((c) => c.total);
  if (!sums.length || !rows.value.length) return undefined;
  return Object.fromEntries([[columns[0]!.key, "Total"], ...sums.map((c) => [c.key,
    rows.value.reduce((t, r) => t + Number(r[c.key] ?? 0), 0).toFixed(c.type === "money" ? 2 : 3)])]);
});
</script>

<template>
  <PrintShell v-model:format="format" :title="title" :subtitle="subtitle" :formats="['a4', 'a4-landscape']"
              :ready="query.isSuccess.value" :filename="title.toLowerCase().replace(/[^a-z0-9à-ú]+/gi, '-')">
    <p v-if="!resource" class="doc-note">Lista desconhecida.</p>
    <PrintTable v-else :columns="columns" :rows="rows" :totals="totals" />
  </PrintShell>
</template>
