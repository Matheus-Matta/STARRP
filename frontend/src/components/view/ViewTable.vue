<script setup lang="ts">
/** Tabela de leitura (itens, pagamentos, parcelas...) com a linha de totais das colunas `total`. */
import { computed } from "vue";

import CellValue from "@/components/resource/CellValue.vue";
import type { ColumnDef } from "@/resources/types";

const props = defineProps<{ columns: ColumnDef[]; rows: Record<string, unknown>[]; empty?: string }>();
const numeric = (c: ColumnDef) => ["money", "quantity", "percent"].includes(c.type ?? "");
const filled = (v: unknown) => v !== null && v !== undefined && v !== "";
/** Coluna de texto vazia em todas as linhas (lote, autorização...) não ocupa espaço. */
const shown = computed(() => props.columns.filter((c) => c.title || numeric(c) || props.rows.some((r) => filled(r[c.key]))));
const totals = computed(() => {
  if (!props.columns.some((c) => c.total) || props.rows.length < 2) return null;
  return Object.fromEntries(props.columns.filter((c) => c.total)
    .map((c) => [c.key, props.rows.reduce((s, r) => s + Number(r[c.key] ?? 0), 0)]));
});
</script>

<template>
  <p v-if="!rows.length" class="vt-empty">{{ empty ?? "Nada por aqui." }}</p>
  <div v-else class="vt-wrap">
    <table class="vt">
      <thead><tr><th v-for="c in shown" :key="c.key" :class="{ r: numeric(c) }">{{ c.label }}</th></tr></thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="String(row.id ?? i)">
          <td v-for="c in shown" :key="c.key" :class="{ r: numeric(c), t: c.title }"><CellValue :column="c" :value="row[c.key]" /></td>
        </tr>
      </tbody>
      <tfoot v-if="totals">
        <tr>
          <td v-for="(c, index) in shown" :key="c.key" :class="{ r: numeric(c) }">
            <CellValue v-if="c.key in totals" :column="c" :value="totals[c.key]" />
            <template v-else-if="index === 0">Total</template>
          </td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>

<style scoped>
.vt-wrap { overflow-x: auto; }
.vt { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.vt th {
  text-align: left; padding: 9px 14px; font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--text-muted); background: var(--surface-sunken, var(--surface-hover)); border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
}
.vt td { padding: 10px 14px; border-bottom: 1px solid var(--border-subtle); color: var(--text-body); }
/* Só o nome (coluna-título) quebra linha; código, lote e números ficam inteiros. */
.vt td:not(.t) { white-space: nowrap; }
.vt td.t { min-width: 180px; }
.vt tbody tr:last-child td { border-bottom: 0; }
.vt tbody tr:hover td { background: var(--surface-hover); }
.vt .r { text-align: right; white-space: nowrap; }
.vt .t { font-weight: 600; color: var(--text-strong); }
.vt tfoot td { border-top: 1px solid var(--border); border-bottom: 0; font-weight: 700; color: var(--text-strong); background: var(--surface-sunken, var(--surface-hover)); }
.vt-empty { margin: 0; padding: 20px 16px; color: var(--text-muted); font-size: 13px; }
</style>
