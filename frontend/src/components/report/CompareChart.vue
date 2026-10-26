<script setup lang="ts">
/**
 * Cruzamento lado a lado: cada linha é um grupo (classe A/B/C, no prazo × atrasada, vendedor)
 * e cada coluna uma medida (nota, recompra, margem...). Embaixo do número, uma barra relativa
 * ao maior da coluna; o melhor valor da coluna ganha ▲ verde e o pior ▼ vermelho (com o
 * símbolo, não só a cor) — quando a coluna diz o que é bom (`good`). No celular, um cartão por grupo.
 */
import { computed } from "vue";

import { useViewport } from "@/composables/useViewport";

import { fmt, type Format, seriesColor } from "./chart";

type Metric = { key: string; label: string; format?: Format; good?: "up" | "down" };
type Row = Record<string, unknown> & { label: string; group?: string };
const props = defineProps<{ metrics: Metric[]; rows: Row[] }>();
const { isPhone } = useViewport();

const has = (v: unknown) => v !== null && v !== undefined && v !== "";
const stats = computed(() => Object.fromEntries(props.metrics.map((m) => {
  const values = props.rows.map((r) => r[m.key]).filter(has).map(Number);
  return [m.key, { max: Math.max(1e-9, ...values.map(Math.abs)), hi: Math.max(...values), lo: Math.min(...values), n: values.length }];
})));
function mark(m: Metric, value: unknown): "best" | "worst" | null {
  const s = stats.value[m.key];
  if (!m.good || !has(value) || !s || s.n < 2 || s.hi === s.lo) return null;
  const v = Number(value);
  const best = m.good === "up" ? s.hi : s.lo;
  const worst = m.good === "up" ? s.lo : s.hi;
  return v === best ? "best" : v === worst ? "worst" : null;
}
const width = (m: Metric, value: unknown) => (has(value) ? `${(Math.abs(Number(value)) / stats.value[m.key]!.max) * 100}%` : "0");
/** Cor do grupo pela ordem em que aparece (Classe A = 1ª cor, como nos outros gráficos). */
const groups = computed(() => [...new Set(props.rows.map((r) => r.group).filter(Boolean))] as string[]);
const dot = (r: Row) => (r.group ? seriesColor(groups.value.indexOf(r.group)) : null);
</script>

<template>
  <p v-if="!rows.length" class="empty">Sem dados no período para cruzar.</p>
  <div v-else-if="isPhone" class="cards">
    <div v-for="r in rows" :key="r.label" class="card">
      <strong class="card__title"><i v-if="dot(r)" class="dot" :style="{ background: dot(r)! }" />{{ r.label }}</strong>
      <dl>
        <div v-for="m in metrics" :key="m.key" :class="mark(m, r[m.key])">
          <dt>{{ m.label }}</dt>
          <dd>{{ has(r[m.key]) ? fmt(r[m.key], m.format ?? "number") : "—" }}
            <span v-if="mark(m, r[m.key])" class="sym">{{ mark(m, r[m.key]) === "best" ? "▲" : "▼" }}</span></dd>
        </div>
      </dl>
    </div>
  </div>
  <div v-else class="scroll">
    <table class="cmp">
      <thead>
        <tr><th />
          <th v-for="m in metrics" :key="m.key" class="r">{{ m.label }}
            <small v-if="m.good">{{ m.good === "up" ? "maior é melhor" : "menor é melhor" }}</small></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.label">
          <th scope="row"><i v-if="dot(r)" class="dot" :style="{ background: dot(r)! }" />{{ r.label }}</th>
          <td v-for="m in metrics" :key="m.key" class="r" :class="mark(m, r[m.key])">
            <span class="val">
              <span v-if="mark(m, r[m.key])" class="sym" :aria-label="mark(m, r[m.key]) === 'best' ? 'melhor' : 'pior'">
                {{ mark(m, r[m.key]) === "best" ? "▲" : "▼" }}</span>
              {{ has(r[m.key]) ? fmt(r[m.key], m.format ?? "number") : "—" }}
            </span>
            <span class="track"><i :style="{ width: width(m, r[m.key]) }" /></span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.scroll { overflow-x: auto; }
.cmp { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13.5px; }
.cmp thead th { padding: 8px 12px; font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.03em;
                color: var(--text-muted); background: var(--surface-sunken); border-bottom: 1px solid var(--border-subtle);
                white-space: nowrap; vertical-align: bottom; }
.cmp thead small { display: block; font-size: 10px; text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--text-subtle); }
.cmp tbody th { text-align: left; padding: 10px 12px; font-weight: 700; color: var(--text-strong); white-space: nowrap;
                border-bottom: 1px solid var(--border-subtle); }
.cmp td { padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); min-width: 110px; }
.r { text-align: right; }
.val { display: block; font-weight: 600; color: var(--text-strong); font-variant-numeric: tabular-nums; white-space: nowrap; }
.track { display: block; height: 4px; margin-top: 5px; border-radius: 2px; background: var(--surface-sunken); overflow: hidden; }
.track i { display: block; height: 100%; margin-left: auto; border-radius: 2px; background: var(--chart-axis); }
.best { background: color-mix(in srgb, var(--success-subtle) 70%, transparent); }
.best .val, .best .sym { color: var(--success-text); }
.best .track i { background: var(--success); }
.worst { background: color-mix(in srgb, var(--danger-subtle) 60%, transparent); }
.worst .val, .worst .sym { color: var(--danger-text); }
.worst .track i { background: var(--danger); }
.sym { font-size: 10px; margin-right: 2px; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 8px; vertical-align: middle; }
.empty { margin: 0; color: var(--text-muted); font-size: 13px; }
.cards { display: flex; flex-direction: column; gap: 8px; }
.card { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.card__title { display: block; margin-bottom: 6px; color: var(--text-strong); }
.card dl { margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 10px; }
.card dl div { border-radius: 6px; padding: 2px 4px; }
.card dt { font-size: 11px; color: var(--text-muted); }
.card dd { margin: 0; font-weight: 700; color: var(--text-strong); }
</style>
