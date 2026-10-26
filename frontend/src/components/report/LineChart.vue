<script setup lang="ts">
/**
 * Linha (evolução no tempo). 2px, pontas redondas, área leve só na 1ª série; a linha-guia
 * vertical encontra o dia mais perto do ponteiro e o balão mostra TODAS as séries naquele dia.
 * Uma escala só (nunca dois eixos).
 */
import { computed, ref } from "vue";

import { axisFmt, fmt, type Format, type Grain, niceScale, seriesColor, tipTitle, xLabel } from "./chart";
import ChartTooltip from "./ChartTooltip.vue";
import { useTooltip } from "./useTooltip";
import { useWidth } from "./useWidth";

/** `zero: false` (saldo): a escala começa perto do menor valor, para a variação aparecer. */
const props = defineProps<{ x: string[]; series: { name: string; values: (string | number)[] }[]; format: Format;
                            zero?: boolean; grain?: Grain }>();
const { el, width } = useWidth();
const { tip, show, hide } = useTooltip();
const H = 240;
const M = { top: 12, right: 16, bottom: 28, left: 64 };
const hover = ref<number | null>(null);

const values = computed(() => props.series.map((s) => s.values.map(Number)));
const minVal = computed(() => {
  const all = values.value.flat();
  if (props.zero !== false) return Math.min(0, ...all);
  const [lo, hi] = [Math.min(...all), Math.max(...all)];
  const floor = lo - (hi - lo) * 0.15;
  return floor > 0 ? niceScale(floor).ticks.filter((t) => t <= floor).at(-1) ?? 0 : Math.min(0, floor);
});
const scale = computed(() => niceScale(Math.max(...values.value.flat(), 0) - minVal.value));
const innerW = computed(() => width.value - M.left - M.right);
const innerH = H - M.top - M.bottom;
const xAt = (i: number) => M.left + (props.x.length <= 1 ? innerW.value / 2 : (i / (props.x.length - 1)) * innerW.value);
const yAt = (v: number) => M.top + innerH - ((v - minVal.value) / scale.value.max) * innerH;
const paths = computed(() => values.value.map((vals) => vals.map((v, i) => `${i ? "L" : "M"}${xAt(i)},${yAt(v)}`).join(" ")));
const baseY = computed(() => yAt(Math.max(0, minVal.value)));
const area = computed(() => {
  const first = values.value[0];
  if (!first?.length) return "";
  return `${paths.value[0]} L${xAt(first.length - 1)},${baseY.value} L${xAt(0)},${baseY.value} Z`;
});
const every = computed(() => Math.max(1, Math.ceil(props.x.length / Math.max(2, Math.floor(innerW.value / 70)))));
const last = computed(() => {
  const first = values.value[0];
  return first?.length ? { x: xAt(first.length - 1), y: yAt(first[first.length - 1] ?? 0) } : null;
});

function move(event: MouseEvent) {
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect();
  const rel = (event.clientX - rect.left - M.left) / innerW.value;
  const index = Math.max(0, Math.min(props.x.length - 1, Math.round(rel * (props.x.length - 1))));
  hover.value = index;
  const label = props.x[index];
  show(event, tipTitle(label, props.grain),
       props.series.map((s, i) => ({ label: s.name, value: fmt(s.values[index], props.format), color: seriesColor(i) })));
}
function leave() {
  hover.value = null;
  hide();
}
</script>

<template>
  <div ref="el" class="chart">
    <ul v-if="series.length > 1" class="legend">
      <li v-for="(s, i) in series" :key="s.name"><span class="legend__line" :style="{ background: seriesColor(i) }" />{{ s.name }}</li>
    </ul>
    <svg :width="width" :height="H" role="img" :aria-label="series.map((s) => s.name).join(', ')"
         @mousemove="move" @mouseleave="leave">
      <g v-for="t in scale.ticks" :key="t">
        <line :x1="M.left" :x2="width - M.right" :y1="yAt(t + minVal)" :y2="yAt(t + minVal)" class="grid" />
        <text :x="M.left - 8" :y="yAt(t + minVal) + 4" text-anchor="end" class="tick">{{ axisFmt(t + minVal, format) }}</text>
      </g>
      <template v-for="(label, i) in x" :key="i">
        <text v-if="i % every === 0" :x="xAt(i)" :y="H - 8" text-anchor="middle" class="tick">{{ xLabel(label, grain) }}</text>
      </template>
      <path :d="area" :fill="seriesColor(0)" opacity="0.1" />
      <path v-for="(d, i) in paths" :key="i" :d="d" fill="none" :stroke="seriesColor(i)" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round" />
      <g v-if="hover !== null">
        <line :x1="xAt(hover)" :x2="xAt(hover)" :y1="M.top" :y2="M.top + innerH" class="cross" />
        <circle v-for="(vals, i) in values" :key="i" :cx="xAt(hover)" :cy="yAt(vals[hover] ?? 0)" r="4.5"
                :fill="seriesColor(i)" stroke="var(--surface-card)" stroke-width="2" />
      </g>
      <!-- Último ponto da série principal: marca onde o período terminou. -->
      <circle v-else-if="last" :cx="last.x" :cy="last.y" r="4" :fill="seriesColor(0)" stroke="var(--surface-card)"
              stroke-width="2" />
    </svg>
    <ChartTooltip :tip="tip" />
  </div>
</template>

<style scoped>
.chart { width: 100%; }
svg { display: block; overflow: visible; }
.grid { stroke: var(--chart-grid); stroke-width: 1; }
.cross { stroke: var(--chart-axis); stroke-width: 1; }
.tick { fill: var(--chart-ink); font-size: 11px; font-variant-numeric: tabular-nums; }
.legend { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--text-body); }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend__line { width: 14px; height: 2px; border-radius: 1px; }
</style>
