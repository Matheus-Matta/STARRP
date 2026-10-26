<script setup lang="ts">
/**
 * Cascata (DRE): cada linha soma (azul) ou tira (vermelho) do acumulado; os subtotais
 * (receita líquida, lucro bruto, resultado) são colunas inteiras em cinza com o valor escrito.
 * Cores divergentes azul ↔ vermelho, nunca a cor de status.
 */
import { computed } from "vue";

import { axisFmt, fmt, type Format, niceScale } from "./chart";
import ChartTooltip from "./ChartTooltip.vue";
import { useTooltip } from "./useTooltip";
import { useWidth } from "./useWidth";

type Step = { label: string; value: string | number; kind: "add" | "sub" | "total" };
const props = defineProps<{ steps: Step[]; format: Format }>();
const { el, width } = useWidth();
const { tip, show, hide } = useTooltip();
const H = 280;
const M = { top: 22, right: 12, bottom: 44, left: 70 };
const innerW = computed(() => width.value - M.left - M.right);
const innerH = H - M.top - M.bottom;

const bars = computed(() => {
  let running = 0;
  return props.steps.map((s) => {
    const v = Number(s.value);
    if (s.kind === "total") {
      running = v;
      return { ...s, from: 0, to: v };
    }
    const from = running;
    running += v;
    return { ...s, from, to: running };
  });
});
const lo = computed(() => Math.min(0, ...bars.value.flatMap((b) => [b.from, b.to])));
const hi = computed(() => Math.max(0, ...bars.value.flatMap((b) => [b.from, b.to])));
const scale = computed(() => niceScale(hi.value - lo.value));
const y = (v: number) => M.top + innerH - ((v - lo.value) / scale.value.max) * innerH;
const band = computed(() => innerW.value / Math.max(1, props.steps.length));
const barW = computed(() => Math.min(36, band.value * 0.62));
/** Rótulo em até duas linhas: a 1ª palavra e o resto ("Diferenças" / "de caixa"). */
const twoLines = (label: string) => {
  const [first, ...rest] = label.split(" ");
  return rest.length ? [first, rest.join(" ")] : [first];
};
const color = (b: Step & { to: number }) => (b.kind === "total" ? "var(--diverge-mid)"
  : Number(b.value) >= 0 ? "var(--diverge-pos)" : "var(--diverge-neg)");
</script>

<template>
  <div ref="el" class="chart">
    <ul class="legend">
      <li><span class="legend__box" style="background: var(--diverge-pos)" />Soma</li>
      <li><span class="legend__box" style="background: var(--diverge-neg)" />Desconta</li>
      <li><span class="legend__box" style="background: var(--diverge-mid)" />Subtotal</li>
    </ul>
    <svg :width="width" :height="H" role="img" aria-label="Cascata do demonstrativo">
      <g v-for="t in scale.ticks" :key="t">
        <line :x1="M.left" :x2="width - M.right" :y1="y(t + lo)" :y2="y(t + lo)" class="grid" />
        <text :x="M.left - 8" :y="y(t + lo) + 4" text-anchor="end" class="tick">{{ axisFmt(t + lo, format) }}</text>
      </g>
      <line :x1="M.left" :x2="width - M.right" :y1="y(0)" :y2="y(0)" class="zero" />
      <g v-for="(b, i) in bars" :key="b.label">
        <!-- conector: onde a coluna anterior terminou -->
        <line v-if="i > 0" :x1="M.left + band * (i - 1) + (band + barW) / 2" :x2="M.left + band * i + (band - barW) / 2"
              :y1="y(bars[i - 1]!.to)" :y2="y(bars[i - 1]!.to)" class="link" />
        <rect :x="M.left + band * i + (band - barW) / 2" :y="Math.min(y(b.from), y(b.to))" :width="barW"
              :height="Math.max(1.5, Math.abs(y(b.from) - y(b.to)))" rx="3" :fill="color(b)" tabindex="0" class="bar"
              @mousemove="show($event, b.label, [{ label: b.kind === 'total' ? 'subtotal' : 'no período', value: fmt(b.value, format) }])"
              @focus="show($event, b.label, [{ label: b.kind === 'total' ? 'subtotal' : 'no período', value: fmt(b.value, format) }])"
              @mouseleave="hide" @blur="hide" />
        <text v-if="b.kind === 'total'" :x="M.left + band * i + band / 2" :y="Math.min(y(b.from), y(b.to)) - 6"
              text-anchor="middle" class="value">{{ axisFmt(Number(b.value), format) }}</text>
        <text :x="M.left + band * i + band / 2" :y="H - 26" text-anchor="middle" class="tick label">
          <tspan v-for="(line, w) in twoLines(b.label)" :key="w" :x="M.left + band * i + band / 2" :dy="w ? 12 : 0">{{ line }}</tspan>
        </text>
      </g>
    </svg>
    <ChartTooltip :tip="tip" />
  </div>
</template>

<style scoped>
.chart { width: 100%; overflow-x: auto; }
svg { display: block; overflow: visible; min-width: 560px; }
.grid { stroke: var(--chart-grid); stroke-width: 1; }
.zero { stroke: var(--chart-axis); stroke-width: 1; }
.link { stroke: var(--chart-axis); stroke-width: 1; }
.tick { fill: var(--chart-ink); font-size: 11px; font-variant-numeric: tabular-nums; }
.label { font-size: 10.5px; }
.value { fill: var(--text-strong); font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.bar { outline: none; }
.bar:hover, .bar:focus-visible { filter: brightness(1.1); }
.legend { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--text-body); }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend__box { width: 10px; height: 10px; border-radius: 3px; }
</style>
