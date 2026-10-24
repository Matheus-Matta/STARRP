<script setup lang="ts">
/**
 * Tabela de documento impresso: cabeçalho repete em cada página, linhas zebradas,
 * números à direita e linha de totais. Na bobina vira lista compacta.
 */
import type { ColumnDef } from "@/resources/types";
import { date, dateTime, money, percent, quantity } from "@/utils/format";

const props = defineProps<{
  columns: ColumnDef[];
  rows: Record<string, unknown>[];
  totals?: Record<string, unknown>;
  empty?: string;
  thermal?: boolean;
}>();

const numeric = (c: ColumnDef) => ["money", "quantity", "percent"].includes(c.type ?? "");
function show(c: ColumnDef, v: unknown) {
  if (v === null || v === undefined || v === "") return "—";
  switch (c.type) {
    case "money": return money(v);
    case "quantity": return quantity(v);
    case "percent": return percent(v);
    case "date": return date(v);
    case "datetime": return dateTime(v);
    case "boolean": return v ? "Sim" : "Não";
    case "tag": return c.map?.[String(v)] ?? String(v);
    default: return String(v);
  }
}
const firstText = props.columns.find((c) => !numeric(c))?.key;
</script>

<template>
  <p v-if="!rows.length" class="pt-empty">{{ empty ?? "Nenhum registro." }}</p>
  <ul v-else-if="thermal" class="pt-thermal">
    <li v-for="(row, i) in rows" :key="i">
      <div class="pt-thermal__main">{{ show(columns.find((c) => c.key === firstText)!, row[firstText!]) }}</div>
      <div class="pt-thermal__rest">
        <span v-for="c in columns.filter((c) => c.key !== firstText)" :key="c.key">{{ c.label }}: <b>{{ show(c, row[c.key]) }}</b></span>
      </div>
    </li>
  </ul>
  <table v-else class="pt">
    <thead><tr><th v-for="c in columns" :key="c.key" :class="{ r: numeric(c) }">{{ c.label }}</th></tr></thead>
    <tbody>
      <tr v-for="(row, i) in rows" :key="i"><td v-for="c in columns" :key="c.key" :class="{ r: numeric(c) }">{{ show(c, row[c.key]) }}</td></tr>
    </tbody>
    <tfoot v-if="totals">
      <tr><td v-for="c in columns" :key="c.key" :class="{ r: numeric(c) }">{{ c.key in totals ? show(c, totals[c.key]) : "" }}</td></tr>
    </tfoot>
  </table>
</template>
