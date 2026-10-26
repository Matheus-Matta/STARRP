<script setup lang="ts">
/**
 * Ranking em barras horizontais: rótulo, barra e o valor escrito ao lado (dá para ler sem
 * passar o mouse). Uma cor só; com `group` (ex.: classe A/B/C) cada grupo tem a sua, com legenda.
 * Valor negativo (conta no vermelho) cresce para a esquerda, na cor divergente.
 */
import { computed, ref } from "vue";

import { fmt, type Format, seriesColor } from "./chart";

type Row = { label: string; value: string | number; sub?: string; group?: string };
/** `ordered: false`: as linhas já vêm numa ordem natural (dias da semana) — sem número de posição. */
const props = defineProps<{ rows: Row[]; format: Format; limit?: number; ordered?: boolean; empty?: string }>();
const expanded = ref(false);
const cap = computed(() => props.limit ?? 10);
const shown = computed(() => (expanded.value ? props.rows : props.rows.slice(0, cap.value)));
const max = computed(() => Math.max(1, ...props.rows.map((r) => Math.abs(Number(r.value)))));
const hasNegative = computed(() => props.rows.some((r) => Number(r.value) < 0));
/** Grupo → cor pela ordem em que aparece (A, B, C...): a cor segue o grupo, não a posição. */
const groups = computed(() => [...new Set(props.rows.map((r) => r.group).filter(Boolean))] as string[]);
const color = (row: Row) => (Number(row.value) < 0 ? "var(--diverge-neg)"
  : row.group ? seriesColor(groups.value.indexOf(row.group)) : seriesColor(0));
/** Com negativos, cada lado do zero tem metade da trilha. */
const width = (row: Row) => (Number(row.value) ? `${Math.max(1.5, (Math.abs(Number(row.value)) / max.value) * (hasNegative.value ? 50 : 100))}%` : "0");
/** Tudo zerado (ex.: crescimento sem período anterior para comparar): diz isso em vez de barras vazias. */
const allZero = computed(() => props.rows.length > 0 && props.rows.every((r) => !Number(r.value)));
</script>

<template>
  <div class="ranking">
    <ul v-if="groups.length > 1" class="legend">
      <li v-for="(g, i) in groups" :key="g"><span class="legend__box" :style="{ background: seriesColor(i) }" />{{ g }}</li>
    </ul>
    <p v-if="!rows.length" class="empty">{{ empty ?? "Sem dados no período." }}</p>
    <p v-else-if="allZero" class="empty"><i class="pi pi-info-circle" /> Todos com {{ fmt(0, format) }} no período
      ({{ rows.length }} {{ rows.length === 1 ? "item" : "itens" }}): ainda não há o que comparar.</p>
    <ol v-if="!allZero" class="rows">
      <li v-for="(row, index) in shown" :key="`${row.label}-${index}`" class="row" :title="`${row.label}: ${fmt(row.value, format)}`">
        <span v-if="ordered !== false" class="row__pos">{{ index + 1 }}</span>
        <div class="row__main">
          <div class="row__head">
            <span class="row__label">{{ row.label }}</span>
            <strong class="row__value">{{ fmt(row.value, format) }}</strong>
          </div>
          <div class="row__track" :class="{ 'row__track--neg': hasNegative }">
            <span class="row__bar" :class="{ neg: Number(row.value) < 0 }" :style="{ width: width(row), background: color(row) }" />
          </div>
          <small v-if="row.sub" class="row__sub">{{ row.sub }}</small>
        </div>
      </li>
    </ol>
    <button v-if="rows.length > cap" type="button" class="more" @click="expanded = !expanded">
      {{ expanded ? "Mostrar menos" : `Ver todos (${rows.length})` }}
    </button>
  </div>
</template>

<style scoped>
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; gap: 10px; align-items: flex-start; }
.row__pos { width: 20px; flex: none; padding-top: 1px; font-size: 11.5px; font-weight: 700; color: var(--text-subtle);
            font-variant-numeric: tabular-nums; text-align: right; }
.row__main { flex: 1; min-width: 0; }
.row__head { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.row__label { color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row__value { color: var(--text-strong); font-variant-numeric: tabular-nums; white-space: nowrap; }
.row__track { position: relative; height: 8px; margin-top: 5px; border-radius: 4px; background: var(--surface-sunken); }
.row__bar { position: absolute; left: 0; top: 0; height: 100%; border-radius: 0 4px 4px 0; transition: width 0.4s var(--ease-out); }
.row__track--neg .row__bar { left: 50%; max-width: 50%; }
.row__track--neg .row__bar.neg { left: auto; right: 50%; border-radius: 4px 0 0 4px; }
.row__sub { display: block; margin-top: 3px; font-size: 11.5px; color: var(--text-muted); }
.more { margin-top: 10px; border: 0; background: transparent; padding: 4px 0; color: var(--text-brand); font: 600 12.5px var(--font-sans); cursor: pointer; }
.empty { margin: 0; color: var(--text-muted); font-size: 13px; }
.legend { list-style: none; margin: 0 0 10px; padding: 0; display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--text-body); }
.legend li { display: flex; align-items: center; gap: 6px; }
.legend__box { width: 10px; height: 10px; border-radius: 3px; }
</style>
