<script setup lang="ts">
/**
 * Colunas: uma série, várias lado a lado (agrupadas) ou empilhadas. Barra de no máximo 24px,
 * ponta arredondada (4px) e base reta, 2px de folga entre barras encostadas; a faixa do dia
 * inteira é o alvo do balão (maior que a barra).
 */
import { computed } from "vue";

import { axisFmt, barPath, fmt, type Format, type Grain, niceScale, seriesColor, tipTitle, xLabel } from "./chart";
import ChartTooltip from "./ChartTooltip.vue";
import { useTooltip } from "./useTooltip";
import { useWidth } from "./useWidth";

const props = defineProps<{ x: string[]; series: { name: string; values: (string | number)[] }[]; format: Format;
                            stacked?: boolean; grain?: Grain }>();
const { el, width } = useWidth();
const { tip, show, hide } = useTooltip();
const H = 240;
const M = { top: 12, right: 12, bottom: 28, left: 64 };
const innerW = computed(() => width.value - M.left - M.right);
const innerH = H - M.top - M.bottom;
const num = computed(() => props.series.map((s) => s.values.map((v) => Math.max(0, Number(v)))));
const totals = computed(() => props.x.map((_, i) => num.value.reduce((sum, vals) => sum + (vals[i] ?? 0), 0)));
const scale = computed(() => niceScale(props.stacked ? Math.max(0, ...totals.value) : Math.max(0, ...num.value.flat())));
const band = computed(() => innerW.value / Math.max(1, props.x.length));
const count = computed(() => (props.stacked ? 1 : props.series.length));
const barW = computed(() => Math.max(2, Math.min(24, (band.value * 0.72 - 2 * (count.value - 1)) / count.value)));
const groupW = computed(() => barW.value * count.value + 2 * (count.value - 1));
const y = (v: number) => M.top + innerH - (v / scale.value.max) * innerH;
const every = computed(() => Math.max(1, Math.ceil(props.x.length / Math.max(2, Math.floor(innerW.value / 56)))));

type Bar = { key: string; d: string; color: string };
const bars = computed<Bar[]>(() => {
  const out: Bar[] = [];
  props.x.forEach((_, i) => {
    const left = M.left + band.value * i + (band.value - groupW.value) / 2;
    let base = 0;
    num.value.forEach((vals, s) => {
      const v = vals[i] ?? 0;
      if (!v) return;
      if (props.stacked) {
        const top = y(base + v);
        const bottom = y(base) - (base > 0 ? 2 : 0); // 2px de folga entre os segmentos
        const isTop = num.value.slice(s + 1).every((rest) => !(rest[i] ?? 0)); // só o de cima arredonda
        const d = isTop ? barPath(left, top, barW.value, bottom - top)
          : bottom > top ? `M${left},${bottom} V${top} H${left + barW.value} V${bottom} Z` : "";
        out.push({ key: `${i}-${s}`, d, color: seriesColor(s) });
        base += v;
      } else {
        const x0 = left + s * (barW.value + 2);
        out.push({ key: `${i}-${s}`, d: barPath(x0, y(v), barW.value, y(0) - y(v)), color: seriesColor(s) });
      }
    });
  });
  return out.filter((b) => b.d);
});

function enter(event: MouseEvent | FocusEvent, i: number) {
  const label = props.x[i];
  const title = tipTitle(label, props.grain);
  const rows = props.series.map((s, k) => ({ label: s.name, value: fmt(s.values[i], props.format), color: seriesColor(k) }));
  if (props.stacked && props.series.length > 1) rows.push({ label: "Total", value: fmt(totals.value[i], props.format), color: "" });
  show(event, title, rows);
}
</script>

<template>
  <div ref="el" class="chart">
    <ul v-if="series.length > 1" class="legend">
      <li v-for="(s, i) in series" :key="s.name"><span class="legend__box" :style="{ background: seriesColor(i) }" />{{ s.name }}</li>
    </ul>
    <svg :width="width" :height="H" role="img" :aria-label="series.map((s) => s.name).join(', ')">
      <g v-for="t in scale.ticks" :key="t">
        <line :x1="M.left" :x2="width - M.right" :y1="y(t)" :y2="y(t)" class="grid" />
        <text :x="M.left - 8" :y="y(t) + 4" text-anchor="end" class="tick">{{ axisFmt(t, format) }}</text>
      </g>
      <template v-for="(label, i) in x" :key="i">
        <text v-if="i % every === 0" :x="M.left + band * i + band / 2" :y="H - 8" text-anchor="middle" class="tick">{{ xLabel(label, grain) }}</text>
      </template>
      <path v-for="b in bars" :key="b.key" :d="b.d" :fill="b.color" />
      <rect v-for="(_, i) in x" :key="`hit-${i}`" :x="M.left + band * i" :y="M.top" :width="band" :height="innerH"
            fill="transparent" tabindex="0" class="hit" @mousemove="enter($event, i)" @focus="enter($event, i)"
            @mouseleave="hide" @blur="hide" />
    </svg>
    <ChartTooltip :tip="tip" />
  </div>
</template>

<style scoped>
.chart { width: 100%; }
svg { display: block; overflow: visible; }
.grid { stroke: var(--chart-grid); stroke-width: 1; }
.tick { fill: var(--chart-ink); font-size: 11px; font-variant-numeric: tabular-nums; }
.hit { outline: none; }
.hit:hover, .hit:focus-visible { fill: color-mix(in srgb, var(--text-strong) 5%, transparent); }
.legend { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--text-body); }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend__box { width: 10px; height: 10px; border-radius: 3px; }
</style>
