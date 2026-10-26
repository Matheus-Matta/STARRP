<script setup lang="ts">
/**
 * Parte do todo: uma barra 100% (fatias com 2px de folga) e a legenda com valor e %.
 * No máximo 8 fatias (o backend já junta o resto em "Outros"); a cor segue a fatia.
 */
import { computed } from "vue";

import { fmt, type Format, seriesColor } from "./chart";
import ChartTooltip from "./ChartTooltip.vue";
import { useTooltip } from "./useTooltip";

const props = defineProps<{ rows: { label: string; value: string | number }[]; format: Format }>();
const { tip, show, hide } = useTooltip();
const parts = computed(() => props.rows.filter((r) => Number(r.value) > 0).slice(0, 8));
const total = computed(() => parts.value.reduce((sum, r) => sum + Number(r.value), 0));
const pct = (v: string | number) => (total.value ? (Number(v) / total.value) * 100 : 0);
const pctText = (v: string | number) => `${pct(v).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
</script>

<template>
  <div class="share">
    <p v-if="!parts.length" class="empty">Sem dados no período.</p>
    <!-- Uma fatia só não é gráfico: é uma frase. -->
    <p v-else-if="parts.length === 1" class="single">
      <strong>100%</strong> em <b>{{ parts[0]!.label }}</b> · {{ fmt(parts[0]!.value, format) }}
    </p>
    <template v-else>
      <div class="bar" role="img" :aria-label="parts.map((p) => `${p.label} ${pctText(p.value)}`).join(', ')">
        <span v-for="(p, i) in parts" :key="p.label" class="bar__part" tabindex="0"
              :style="{ flexGrow: Number(p.value), background: seriesColor(i) }"
              @mousemove="show($event, p.label, [{ label: pctText(p.value), value: fmt(p.value, format), color: seriesColor(i) }])"
              @focus="show($event, p.label, [{ label: pctText(p.value), value: fmt(p.value, format), color: seriesColor(i) }])"
              @mouseleave="hide" @blur="hide" />
      </div>
      <ul class="legend">
        <li v-for="(p, i) in parts" :key="p.label">
          <span class="legend__box" :style="{ background: seriesColor(i) }" />
          <span class="legend__label">{{ p.label }}</span>
          <strong class="legend__value">{{ fmt(p.value, format) }}</strong>
          <span class="legend__pct">{{ pctText(p.value) }}</span>
        </li>
      </ul>
      <p class="total">Total <strong>{{ fmt(total, format) }}</strong></p>
    </template>
    <ChartTooltip :tip="tip" />
  </div>
</template>

<style scoped>
.bar { display: flex; gap: 2px; height: 28px; border-radius: 6px; overflow: hidden; }
.bar__part { min-width: 3px; outline: none; transition: filter 0.12s ease; }
.bar__part:hover, .bar__part:focus-visible { filter: brightness(1.12); }
.legend { list-style: none; margin: 14px 0 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
.legend li { display: grid; grid-template-columns: 12px minmax(0, 1fr) auto 52px; align-items: center; gap: 8px; font-size: 13px; }
.legend__box { width: 10px; height: 10px; border-radius: 3px; }
.legend__label { color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.legend__value { color: var(--text-strong); font-variant-numeric: tabular-nums; }
.legend__pct { color: var(--text-muted); font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; }
.total { margin: 10px 0 0; padding-top: 8px; border-top: 1px solid var(--border-subtle); display: flex; justify-content: space-between;
         font-size: 12.5px; color: var(--text-muted); }
.total strong { color: var(--text-strong); }
.single { margin: 0; padding: 14px; border-radius: 10px; background: var(--surface-sunken); font-size: 14px; color: var(--text-body); }
.single strong { font-size: 20px; color: var(--text-strong); margin-right: 4px; }
.single b { color: var(--text-strong); }
.empty { margin: 0; color: var(--text-muted); font-size: 13px; }
</style>
