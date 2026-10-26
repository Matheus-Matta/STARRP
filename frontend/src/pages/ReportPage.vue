<script setup lang="ts">
/**
 * Um relatório do livro (Movimento, Mercadorias, Contábil, Relacionamento): filtros de período
 * numa linha só em cima, os indicadores com a variação contra o período anterior e os blocos
 * (gráficos e a tabela) em grade de duas colunas. Imprime em A4 do jeito que está na tela.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import DatePicker from "primevue/datepicker";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { type BookBlock, reportsApi } from "@/api/reports";
import EmptyState from "@/components/common/EmptyState.vue";
import BarsChart from "@/components/report/BarsChart.vue";
import CompareChart from "@/components/report/CompareChart.vue";
import InsightsBlock from "@/components/report/InsightsBlock.vue";
import type { Format } from "@/components/report/chart";
import HeatmapChart from "@/components/report/HeatmapChart.vue";
import KpiTile from "@/components/report/KpiTile.vue";
import LineChart from "@/components/report/LineChart.vue";
import RankingChart from "@/components/report/RankingChart.vue";
import ReportTable from "@/components/report/ReportTable.vue";
import ShareChart from "@/components/report/ShareChart.vue";
import WaterfallChart from "@/components/report/WaterfallChart.vue";
import { findReport, visibleGroups } from "@/reports/catalog";
import { useSession } from "@/stores/session";
import { useNotify } from "@/composables/useNotify";
import { date } from "@/utils/format";
import { openPrint } from "@/utils/print";

const route = useRoute();
const router = useRouter();
const session = useSession();
const notify = useNotify();
const slug = computed(() => String(route.params.slug));
const def = computed(() => findReport(slug.value));
const siblings = computed(() => visibleGroups(session.can, session.hasModule).find((g) => g.label === def.value?.group)?.reports ?? []);

const iso = (d: Date) => d.toLocaleDateString("sv-SE");
const today = () => new Date();
const back = (days: number) => {
  const d = today();
  d.setDate(d.getDate() - days + 1);
  return d;
};
const PRESETS = [
  { label: "7 dias", value: "7", range: () => [back(7), today()] },
  { label: "30 dias", value: "30", range: () => [back(30), today()] },
  { label: "90 dias", value: "90", range: () => [back(90), today()] },
  { label: "Este mês", value: "month", range: () => [new Date(today().getFullYear(), today().getMonth(), 1), today()] },
  { label: "Este ano", value: "year", range: () => [new Date(today().getFullYear(), 0, 1), today()] },
];
const preset = ref<string | null>(String(route.query.periodo ?? "30"));
const custom = ref<Date[] | null>(null);
const range = computed<Date[]>(() => {
  if (custom.value?.[0]) return [custom.value[0], custom.value[1] ?? custom.value[0]];
  return (PRESETS.find((p) => p.value === preset.value) ?? PRESETS[1]!).range();
});
watch(preset, (value) => {
  if (value) custom.value = null;
  void router.replace({ query: { ...route.query, periodo: value ?? undefined } });
});
watch(custom, (value) => {
  if (value?.[0]) preset.value = null;
});

/** Filtros próprios do relatório (vêm do backend com as opções): ficam no endereço, dá para mandar o link. */
const extra = computed(() => Object.fromEntries(Object.entries(route.query)
  .filter(([key, value]) => key !== "periodo" && typeof value === "string" && value)) as Record<string, string>);
function setFilter(name: string, value: unknown) {
  void router.replace({ query: { ...route.query, [name]: value ? String(value) : undefined } });
}
const clearFilters = () => router.replace({ query: { periodo: route.query.periodo } });
const params = computed(() => ({ ...extra.value, date_from: iso(range.value[0]!), date_to: iso(range.value[1]!) }));
const showAbout = ref(false);
const query = useQuery({
  queryKey: computed(() => ["report-book", slug.value, session.activeStoreId, params.value]),
  queryFn: () => reportsApi.book(slug.value, params.value),
  placeholderData: (previous) => previous,
});
const report = computed(() => query.data.value);
const scope = computed(() => (slug.value === "filiais" ? "Todas as filiais que você acessa"
  : session.activeStore?.name ?? "Todas as minhas filiais"));
const f = (value: unknown) => (value ?? "number") as Format;
/** Mensagem de lista vazia que o relatório manda ("Nenhuma promoção deu prejuízo no período."). */
const emptyOf = (block: BookBlock) => (typeof block.empty === "string" ? block.empty : undefined);
/** Impressão própria (folha do relatório, não a tela), com os mesmos filtros e período. */
const print = () => openPrint("relatorio", slug.value, params.value);
const exporting = ref<"xlsx" | "csv" | null>(null);
async function exportReport(format: "xlsx" | "csv", extra: { bloco?: number; aba?: string | null } = {}) {
  if (extra.bloco === undefined) exporting.value = format;
  try {
    await reportsApi.export(slug.value, params.value, format, extra);
  } catch (error) {
    notify.error(error, "Não foi possível exportar");
  } finally {
    exporting.value = null;
  }
}
</script>

<template>
  <section class="page report">
    <header class="report__head">
      <div class="report__title">
        <span class="report__icon"><i :class="def?.icon ?? 'pi pi-chart-bar'" /></span>
        <div>
          <p class="report__crumb">Relatórios · {{ def?.group }}</p>
          <h1>{{ report?.title ?? def?.title }}</h1>
          <p class="report__sub">{{ report?.subtitle ?? def?.description }}</p>
        </div>
      </div>
      <div class="report__actions no-print">
        <Button icon="pi pi-refresh" text rounded severity="secondary" aria-label="Atualizar" :loading="query.isFetching.value"
                @click="query.refetch()" />
        <Button label="Excel" icon="pi pi-file-excel" severity="secondary" outlined size="small" :loading="exporting === 'xlsx'"
                title="Planilha com o resumo e uma aba para cada gráfico e tabela" @click="exportReport('xlsx')" />
        <Button label="CSV" icon="pi pi-file" severity="secondary" outlined size="small" :loading="exporting === 'csv'"
                title="A tabela principal do relatório" @click="exportReport('csv')" />
        <Button label="Imprimir" icon="pi pi-print" size="small" title="Folha própria do relatório (A4), com gráficos e tabelas completas"
                @click="print" />
      </div>
    </header>

    <!-- Filtros: uma linha só, acima de tudo -->
    <div class="filters no-print">
      <SelectButton v-model="preset" :options="PRESETS" option-label="label" option-value="value" size="small" />
      <DatePicker v-model="custom" selection-mode="range" :manual-input="false" date-format="dd/mm/yy" show-icon
                  placeholder="Outro período" size="small" class="filters__date" :max-date="today()" />
      <span class="filters__scope"><i class="pi pi-building" /> {{ scope }}</span>
    </div>
    <div v-if="report?.filters?.length" class="filters filters--own no-print">
      <i class="pi pi-filter filters__icon" />
      <Select v-for="flt in report.filters" :key="flt.name" :model-value="extra[flt.name] ?? null" :options="flt.options"
              option-label="label" option-value="value" :placeholder="flt.label" show-clear size="small"
              :filter="flt.options.length > 8" filter-placeholder="Procurar…" class="filters__select"
              :class="{ 'filters__select--on': extra[flt.name] }" :aria-label="flt.label"
              @update:model-value="setFilter(flt.name, $event)" />
      <Button v-if="Object.keys(extra).length" label="Limpar filtros" icon="pi pi-filter-slash" text size="small"
              severity="secondary" @click="clearFilters" />
    </div>

    <!-- Para que serve: sempre à vista; como ler e o que decidir, ao abrir. -->
    <aside v-if="def?.about" class="about no-print">
      <p class="about__purpose"><i class="pi pi-info-circle" /> <span><b>Para que serve.</b> {{ def.about.purpose }}</span></p>
      <button type="button" class="about__toggle" :aria-expanded="showAbout" @click="showAbout = !showAbout">
        {{ showAbout ? "Esconder" : "Como ler e o que decidir" }}
        <i :class="showAbout ? 'pi pi-chevron-up' : 'pi pi-chevron-down'" />
      </button>
      <div v-if="showAbout" class="about__more">
        <div><h3><i class="pi pi-eye" /> Como ler</h3><ul><li v-for="t in def.about.read" :key="t">{{ t }}</li></ul></div>
        <div><h3><i class="pi pi-compass" /> Ajuda a decidir</h3><ul><li v-for="t in def.about.decide" :key="t">{{ t }}</li></ul></div>
      </div>
    </aside>
    <p class="report__period">{{ date(params.date_from) }} a {{ date(params.date_to) }} · {{ scope }}</p>

    <nav v-if="siblings.length > 1" class="tabs no-print" aria-label="Outros relatórios do grupo">
      <RouterLink v-for="r in siblings" :key="r.slug" :to="{ path: `/relatorios/${r.slug}`, query: { periodo: route.query.periodo } }"
                  class="tab" :class="{ active: r.slug === slug }"><i :class="r.icon" /> {{ r.title }}</RouterLink>
    </nav>

    <EmptyState v-if="query.isError.value" title="Não foi possível abrir o relatório" icon="pi pi-exclamation-circle"
                description="Confira se você tem acesso a ele e tente de novo." />
    <template v-else-if="!report">
      <div class="kpis"><Skeleton v-for="n in 4" :key="n" height="96px" border-radius="12px" /></div>
      <div class="blocks"><Skeleton v-for="n in 3" :key="n" height="280px" border-radius="12px" class="block--half" /></div>
    </template>
    <template v-else>
      <div class="kpis" :class="{ refreshing: query.isFetching.value }">
        <KpiTile v-for="(k, i) in report.kpis" :key="k.label" :label="k.label" :value="k.value" :format="f(k.format)"
                 :delta="k.delta" :good="k.good" :hint="k.hint" :accent="i" />
      </div>
      <div class="blocks" :class="{ refreshing: query.isFetching.value }">
        <section v-for="(block, i) in report.blocks" :key="`${block.title}-${i}`" class="block"
                 :class="block.span === 'half' ? 'block--half' : 'block--full'">
          <header class="block__head">
            <h2>{{ block.title }}</h2>
            <p v-if="block.description">{{ block.description }}</p>
          </header>
          <LineChart v-if="block.type === 'line'" :x="block.x as string[]" :series="block.series as never" :format="f(block.format)"
                     :zero="block.zero !== false" :grain="block.grain as never" />
          <BarsChart v-else-if="block.type === 'bars'" :x="block.x as string[]" :series="block.series as never"
                     :format="f(block.format)" :stacked="block.stacked" :grain="block.grain as never" />
          <RankingChart v-else-if="block.type === 'ranking'" :rows="block.rows as never" :format="f(block.format)"
                        :limit="(block.limit as number | undefined) ?? (block.span === 'half' ? 8 : 12)"
                        :ordered="block.ordered !== false" :empty="emptyOf(block)" />
          <ShareChart v-else-if="block.type === 'share'" :rows="block.rows as never" :format="f(block.format)" />
          <HeatmapChart v-else-if="block.type === 'heatmap'" :rows="block.rows as string[]" :cols="block.cols as string[]"
                        :values="block.values as never" :format="f(block.format)" />
          <WaterfallChart v-else-if="block.type === 'waterfall'" :steps="block.steps as never" :format="f(block.format)" />
          <CompareChart v-else-if="block.type === 'compare'" :metrics="block.metrics as never" :rows="block.rows as never" />
          <InsightsBlock v-else-if="block.type === 'insights'" :items="block.items as never" />
          <ReportTable v-else-if="block.type === 'table'" :columns="block.columns as never" :rows="block.rows as never"
                       :title="`${report.title} ${block.title}`" :tabs="block.tabs as never" :empty="emptyOf(block)"
                       :on-export="(format, aba) => exportReport(format, { bloco: i, aba })" />
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.report { max-width: 1320px; }
.report__head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
.report__title { display: flex; gap: 14px; align-items: flex-start; min-width: 0; }
.report__icon { width: 44px; height: 44px; flex: none; display: grid; place-items: center; border-radius: 12px;
                background: var(--brand-subtle); color: var(--text-brand); font-size: 18px; }
.report__crumb { margin: 0; font-size: 11.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-subtle); }
h1 { margin: 2px 0 0; font: 800 22px/1.2 var(--font-sans); letter-spacing: -0.02em; color: var(--text-strong); }
.report__sub { margin: 4px 0 0; font-size: 13.5px; color: var(--text-muted); }
.report__actions { display: flex; gap: 6px; align-items: center; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.filters__date { width: 230px; }
.filters--own { padding: 8px 10px; border: 1px dashed var(--border); border-radius: 10px; background: var(--surface-card); }
.filters__icon { color: var(--text-muted); font-size: 12px; }
.filters__select { min-width: 170px; max-width: 240px; }
.filters__select--on { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand); }
.about { padding: 12px 14px; border-radius: 10px; background: var(--brand-subtle); border: 1px solid var(--brand-border); }
.about__purpose { margin: 0; display: flex; gap: 8px; font-size: 13.5px; line-height: 1.5; color: var(--text-body); }
.about__purpose i { color: var(--text-brand); margin-top: 3px; }
.about__purpose b { color: var(--text-strong); }
.about__toggle { margin: 6px 0 0 22px; padding: 0; border: 0; background: transparent; color: var(--text-brand);
                 font: 600 12.5px var(--font-sans); cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
.about__toggle i { font-size: 10px; }
.about__more { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 10px 0 0 22px; }
.about__more h3 { margin: 0 0 4px; font: 700 12.5px var(--font-sans); color: var(--text-strong); display: flex; gap: 6px; align-items: center; }
.about__more ul { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.55; color: var(--text-body); }
.filters__scope { margin-left: auto; display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--text-muted); }
.report__period { display: none; }
.tabs { display: flex; gap: 2px; overflow-x: auto; border-bottom: 1px solid var(--border); scrollbar-width: none; }
.tab { display: inline-flex; align-items: center; gap: 7px; padding: 9px 12px; margin-bottom: -1px; white-space: nowrap;
       border-bottom: 2px solid transparent; color: var(--text-muted); font: 600 13px/1 var(--font-sans); }
.tab i { font-size: 12px; }
.tab:hover { color: var(--text-strong); }
.tab.active { color: var(--text-brand); border-bottom-color: var(--brand); }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr)); gap: 12px; }
.blocks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.block { min-width: 0; padding: 16px 18px 18px; border: 1px solid var(--border); border-radius: var(--radius-lg);
         background: var(--surface-card); box-shadow: var(--shadow-xs); }
.block--full { grid-column: 1 / -1; }
.block__head { margin-bottom: 14px; }
.block__head h2 { margin: 0; font: 700 14.5px/1.3 var(--font-sans); color: var(--text-strong); }
.block__head p { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); }
.refreshing { opacity: 0.6; transition: opacity var(--dur-base) ease; }
@media (max-width: 900px) { .blocks { grid-template-columns: 1fr; } .filters__scope { margin-left: 0; } .about__more { grid-template-columns: 1fr; } }
@media (max-width: 640px) {
  .kpis { grid-template-columns: 1fr 1fr; gap: 8px; }
  .block { padding: 14px; }
  .filters__date { width: 100%; }
  .filters__select { flex: 1 1 140px; max-width: none; min-width: 0; }
  .about__more { margin-left: 0; }
  .filters :deep(.p-selectbutton) { width: 100%; overflow-x: auto; flex-wrap: nowrap; scrollbar-width: none; }
  .filters :deep(.p-togglebutton) { flex: none; white-space: nowrap; }
}
@media print {
  .no-print { display: none !important; }
  .report__period { display: block; margin: 0; font-size: 12px; color: var(--text-muted); }
  .blocks { grid-template-columns: 1fr 1fr; }
  .block { break-inside: avoid; box-shadow: none; }
}
</style>
