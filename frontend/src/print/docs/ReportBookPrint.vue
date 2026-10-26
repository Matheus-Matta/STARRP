<script setup lang="ts">
/**
 * Impressão de um relatório do livro (`/imprimir/relatorio/<slug>?date_from=&date_to=&<filtros>`):
 * folha própria (não a tela) com cabeçalho da empresa, período, filial, filtros aplicados,
 * indicadores com a variação, gráficos e as tabelas COMPLETAS. Na barra de cima (que não sai no
 * papel) escolhe-se o que imprimir: indicadores, gráficos, tabelas e o "para que serve".
 * Os gráficos usam sempre as cores de papel (claras), mesmo com o sistema no tema escuro.
 */
import { useQuery } from "@tanstack/vue-query";
import Checkbox from "primevue/checkbox";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

import { type BookBlock, reportsApi } from "@/api/reports";
import BarsChart from "@/components/report/BarsChart.vue";
import CompareChart from "@/components/report/CompareChart.vue";
import InsightsBlock from "@/components/report/InsightsBlock.vue";
import { fmt, type Format } from "@/components/report/chart";
import HeatmapChart from "@/components/report/HeatmapChart.vue";
import LineChart from "@/components/report/LineChart.vue";
import WaterfallChart from "@/components/report/WaterfallChart.vue";
import { findReport } from "@/reports/catalog";
import { useSession } from "@/stores/session";
import { date } from "@/utils/format";

import PrintShell, { type PrintFormat } from "../PrintShell.vue";

const props = defineProps<{ id?: string; initialFormat?: PrintFormat }>();
const route = useRoute();
const session = useSession();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const slug = String(props.id ?? "");
const def = findReport(slug);
const params = Object.fromEntries(Object.entries(route.query).filter(([k, v]) => typeof v === "string" && v
  && !["formato", "auto"].includes(k))) as Record<string, string>;
const query = useQuery({ queryKey: ["print-report", slug, params], queryFn: () => reportsApi.book(slug, params) });
const report = computed(() => query.data.value);

const show = ref({ kpis: true, charts: true, tables: true, about: false });
const f = (v: unknown) => (v ?? "number") as Format;

const filters = computed(() => (report.value?.filters ?? []).filter((flt) => params[flt.name]).map((flt) =>
  `${flt.label}: ${flt.options.find((o) => o.value === params[flt.name])?.label ?? params[flt.name]}`));
const scope = slug === "filiais" ? "Todas as filiais que você acessa" : session.activeStore?.name ?? "Todas as minhas filiais";
const subtitle = computed(() => (report.value
  ? `${date(report.value.period.from)} a ${date(report.value.period.to)} · ${scope}` : ""));
const isChart = (b: BookBlock) => ["line", "bars", "heatmap", "waterfall"].includes(b.type);
const deltaText = (d: string | null, good: string) => {
  if (d === null || d === undefined) return "";
  const n = Number(d);
  const better = (n > 0 && good !== "down") || (n < 0 && good === "down");
  return `${n > 0 ? "▲" : n < 0 ? "▼" : "="} ${Math.abs(n).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% ${n === 0 ? "" : better ? "(melhor)" : "(pior)"} vs. anterior`;
};
/** Ranking e participação viram tabela no papel (valor, %, detalhe), sem o "Ver todos" da tela. */
function asRows(b: BookBlock) {
  const rows = (b.rows as { label: string; value: string | number; sub?: string; group?: string }[]) ?? [];
  const total = rows.reduce((t, r) => t + Number(r.value || 0), 0);
  const max = Math.max(1, ...rows.map((r) => Math.abs(Number(r.value || 0))));
  return rows.map((r, i) => ({ ...r, pos: i + 1, pct: total ? (Number(r.value) / total) * 100 : 0,
                               bar: (Math.abs(Number(r.value || 0)) / max) * 100 }));
}
type Col = { key: string; label: string; format?: string };
const cols = (b: BookBlock) => (b.columns ?? []) as Col[];
const tableRows = (b: BookBlock) => (b.rows ?? []) as Record<string, unknown>[];
const numeric = (c: { format?: string }) => ["money", "number", "decimal", "quantity", "percent"].includes(c.format ?? "");
</script>

<template>
  <PrintShell v-model:format="format" :title="report?.title ?? def?.title ?? 'Relatório'" :subtitle="subtitle"
              :formats="['a4', 'a4-landscape']" :ready="!!report"
              :filename="`${slug}-${report?.period.from ?? ''}-a-${report?.period.to ?? ''}`">
    <div class="rp-options no-print">
      <span>Imprimir:</span>
      <label><Checkbox v-model="show.kpis" binary /> Indicadores</label>
      <label><Checkbox v-model="show.charts" binary /> Gráficos</label>
      <label><Checkbox v-model="show.tables" binary /> Tabelas</label>
      <label><Checkbox v-model="show.about" binary /> Para que serve</label>
    </div>

    <template v-if="report">
      <p class="rp-filters"><b>Filtros:</b> {{ filters.length ? filters.join(" · ") : "nenhum (tudo do período)" }}</p>
      <p v-if="show.about && def?.about" class="rp-about"><b>Para que serve.</b> {{ def.about.purpose }}</p>

      <div v-if="show.kpis" class="rp-kpis">
        <div v-for="k in report.kpis" :key="k.label">
          <small>{{ k.label }}</small>
          <b>{{ fmt(k.value, f(k.format)) }}</b>
          <span v-if="k.delta !== null">{{ deltaText(k.delta, k.good) }}</span>
          <em v-if="k.hint">{{ k.hint }}</em>
        </div>
      </div>

      <template v-for="(block, i) in report.blocks" :key="i">
        <section v-if="isChart(block) ? show.charts : show.tables" class="doc-section rp-block"
                 :class="{ 'rp-block--half': block.span === 'half' && block.type !== 'table' }">
          <h2>{{ block.title }}</h2>
          <p v-if="block.description" class="rp-desc">{{ block.description }}</p>
          <div v-if="isChart(block)" class="rp-chart">
            <LineChart v-if="block.type === 'line'" :x="block.x as string[]" :series="block.series as never" :format="f(block.format)"
                       :zero="block.zero !== false" :grain="block.grain as never" />
            <BarsChart v-else-if="block.type === 'bars'" :x="block.x as string[]" :series="block.series as never"
                       :format="f(block.format)" :stacked="block.stacked" :grain="block.grain as never" />
            <HeatmapChart v-else-if="block.type === 'heatmap'" :rows="block.rows as string[]" :cols="block.cols as string[]"
                          :values="block.values as never" :format="f(block.format)" />
            <WaterfallChart v-else-if="block.type === 'waterfall'" :steps="block.steps as never" :format="f(block.format)" />
          </div>
          <CompareChart v-else-if="block.type === 'compare'" class="rp-chart" :metrics="block.metrics as never"
                        :rows="block.rows as never" />
          <InsightsBlock v-else-if="block.type === 'insights'" :items="block.items as never" />
          <p v-else-if="(block.type === 'ranking' || block.type === 'table') && !(block.rows as unknown[])?.length" class="rp-empty">
            {{ block.empty ?? "Sem dados no período." }}</p>
          <table v-else-if="block.type === 'ranking' || block.type === 'share'" class="pt rp-rank">
            <thead><tr><th v-if="block.type === 'ranking'">#</th><th>Item</th><th class="r">Valor</th><th v-if="block.type === 'share'" class="r">%</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in asRows(block)" :key="`${r.label}-${r.pos}`">
                <td v-if="block.type === 'ranking'" class="n">{{ r.pos }}</td>
                <td>{{ r.label }}<small v-if="r.sub || r.group"> · {{ [r.group, r.sub].filter(Boolean).join(" · ") }}</small></td>
                <td class="r">{{ fmt(r.value, f(block.format)) }}</td>
                <td v-if="block.type === 'share'" class="r">{{ `${r.pct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%` }}</td>
                <td class="bar"><i :style="{ width: `${r.bar}%` }" /></td>
              </tr>
            </tbody>
          </table>
          <table v-else-if="block.type === 'table'" class="pt rp-table">
            <thead><tr><th v-for="c in cols(block)" :key="c.key" :class="{ r: numeric(c) }">{{ c.label }}</th></tr></thead>
            <tbody>
              <tr v-for="(row, r) in tableRows(block)" :key="r" :class="{ strong: row.strong }">
                <td v-for="c in cols(block)" :key="c.key" :class="{ r: numeric(c) }">{{ fmt(row[c.key], f(c.format ?? 'text')) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </template>
  </PrintShell>
</template>

<style scoped>
/* Folha de papel: cores claras sempre (o tema escuro do sistema não vaza para os gráficos). */
:deep(.sheet), .rp-chart {
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --series-5: #e87ba4; --series-6: #008300; --series-7: #6250d6; --series-8: #e34948;
  --seq-low: #cde2fb; --seq-high: #104281; --chart-grid: #e5e7eb; --chart-axis: #9ca3af; --chart-ink: #4b5563;
  --diverge-pos: #2a78d6; --diverge-neg: #e34948; --diverge-mid: #9aa0aa;
  --surface-card: #fff; --surface-sunken: #f3f4f6; --surface-raised: #fff; --text-strong: #111; --text-body: #222;
  --text-muted: #555; --text-subtle: #777; --border: #d1d5db; --border-subtle: #e5e7eb;
  --success: #16a34a; --success-subtle: #dcfce7; --success-text: #166534;
  --danger: #dc2626; --danger-subtle: #fee2e2; --danger-text: #b91c1c; --text-brand: #1d4ed8;
}
.rp-options { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; padding: 8px 10px; border: 1px dashed #bbb;
              border-radius: 6px; font: 12px var(--font-sans); color: #333; }
.rp-options label { display: inline-flex; gap: 6px; align-items: center; cursor: pointer; }
.rp-options :deep(.p-checkbox:not(.p-checkbox-checked) .p-checkbox-box) { background: #fff; border-color: #9ca3af; }
.rp-filters { margin: 0; font-size: 9pt; color: #333; }
.rp-about { margin: 0; padding: 6px 8px; border-left: 3px solid #2a78d6; background: #f3f6fb; font-size: 9pt; }
.rp-kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(42mm, 1fr)); gap: 6px; }
.rp-kpis > div { border: 1px solid #bbb; border-radius: 4px; padding: 6px 8px; break-inside: avoid; }
.rp-kpis small { display: block; font-size: 7.5pt; color: #555; text-transform: uppercase; letter-spacing: 0.03em; }
.rp-kpis b { display: block; font-size: 12.5pt; }
.rp-kpis span { display: block; font-size: 7.5pt; color: #333; }
.rp-kpis em { display: block; font-size: 7.5pt; color: #666; font-style: normal; }
.rp-block { break-inside: avoid; }
.rp-desc { margin: -2px 0 6px; font-size: 8.5pt; color: #555; }
.rp-chart { width: 100%; }
.rp-chart :deep(svg) { max-width: 100%; }
.rp-chart :deep(.hit), .rp-block :deep(.ctip) { display: none; }
/* Comparativo no papel: compacto e sem rolagem (cabe inteiro na largura do A4). */
.rp-chart :deep(.scroll) { overflow: visible; }
.rp-chart :deep(.cmp) { font-size: 8pt; table-layout: fixed; }
.rp-chart :deep(.cmp thead th) { white-space: normal; padding: 4px 5px; font-size: 7pt; }
.rp-chart :deep(.cmp tbody th), .rp-chart :deep(.cmp td) { padding: 4px 5px; min-width: 0; white-space: normal; }
.rp-chart :deep(.cmp .val) { white-space: normal; }
.rp-empty { margin: 0; font-size: 9pt; color: #555; }
.rp-rank { font-size: 9pt; }
.rp-rank .n { width: 18px; color: #777; }
.rp-rank small { color: #666; }
.rp-rank .bar { width: 28%; }
.rp-rank .bar i { display: block; height: 6px; border-radius: 0 3px 3px 0; background: #2a78d6; print-color-adjust: exact;
                  -webkit-print-color-adjust: exact; }
.rp-table { font-size: 8.5pt; }
.rp-table tr.strong td { font-weight: 700; background: #f3f4f6; }
.rp-table, .rp-table tr { break-inside: auto; }
.rp-table thead { display: table-header-group; }
.rp-table tr { break-inside: avoid; }
:deep(.doc-body) { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
</style>
