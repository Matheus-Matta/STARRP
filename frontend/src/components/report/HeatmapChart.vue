<script setup lang="ts">
/**
 * Mapa de calor (sequencial, um tom só: do quase-zero ao mais forte). Cada célula é o alvo do
 * balão; a escala aparece embaixo (mínimo → máximo). Célula zerada fica no fundo.
 */
import { computed } from "vue";

import { fmt, type Format } from "./chart";
import ChartTooltip from "./ChartTooltip.vue";
import { useTooltip } from "./useTooltip";

const props = defineProps<{ rows: string[]; cols: string[]; values: (string | number)[][]; format: Format }>();
const { tip, show, hide } = useTooltip();
const max = computed(() => Math.max(1, ...props.values.flat().map(Number)));
const fill = (v: string | number) => {
  const n = Number(v);
  if (!n) return "var(--surface-sunken)";
  const strength = Math.round(12 + (n / max.value) * 88); // nunca some: o menor ainda se vê
  return `color-mix(in oklab, var(--seq-high) ${strength}%, var(--seq-low))`;
};
</script>

<template>
  <div class="heat">
    <div class="heat__scroll">
      <div class="grid" :style="{ gridTemplateColumns: `44px repeat(${cols.length}, minmax(22px, 1fr))` }">
        <span />
        <span v-for="c in cols" :key="c" class="col">{{ c }}</span>
        <template v-for="(row, r) in rows" :key="row">
          <span class="rowlabel">{{ row }}</span>
          <span v-for="(c, k) in cols" :key="c" class="cell" tabindex="0" :style="{ background: fill(values[r]?.[k] ?? 0) }"
                @mousemove="show($event, `${row} · ${c}`, [{ label: 'no período', value: fmt(values[r]?.[k] ?? 0, format) }])"
                @focus="show($event, `${row} · ${c}`, [{ label: 'no período', value: fmt(values[r]?.[k] ?? 0, format) }])"
                @mouseleave="hide" @blur="hide" />
        </template>
      </div>
    </div>
    <div class="scale"><span>menos</span><i class="scale__ramp" /><span>mais · até {{ fmt(max, format) }}</span></div>
    <ChartTooltip :tip="tip" />
  </div>
</template>

<style scoped>
.heat__scroll { overflow-x: auto; }
.grid { display: grid; gap: 3px; min-width: 520px; }
.col { font-size: 10.5px; color: var(--chart-ink); text-align: center; font-variant-numeric: tabular-nums; }
.rowlabel { font-size: 11.5px; color: var(--text-muted); display: flex; align-items: center; }
.cell { height: 26px; border-radius: 4px; outline: none; transition: transform 0.1s ease; }
.cell:hover, .cell:focus-visible { box-shadow: 0 0 0 2px var(--text-strong) inset; }
.scale { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-size: 11.5px; color: var(--text-muted); }
.scale__ramp { width: 120px; height: 8px; border-radius: 4px; background: linear-gradient(90deg, var(--seq-low), var(--seq-high)); }
</style>
