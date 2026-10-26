<script setup lang="ts">
/** Tabela de leitura (itens, pagamentos, parcelas...) com a linha de totais das colunas `total`.
 * No celular cada linha vira um bloco: o título em cima e as outras colunas em "rótulo  valor". */
import { computed } from "vue";

import CellValue from "@/components/resource/CellValue.vue";
import { useViewport } from "@/composables/useViewport";
import type { ColumnDef } from "@/resources/types";

const props = defineProps<{ columns: ColumnDef[]; rows: Record<string, unknown>[]; empty?: string }>();
const { isPhone } = useViewport();
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
  <ul v-else-if="isPhone" class="vs">
    <li v-for="(row, i) in rows" :key="String(row.id ?? i)">
      <template v-for="c in shown" :key="c.key">
        <strong v-if="c.title" class="vs__title"><CellValue :column="c" :value="row[c.key]" /></strong>
      </template>
      <dl>
        <template v-for="c in shown" :key="c.key">
          <div v-if="!c.title && filled(row[c.key])"><dt>{{ c.label }}</dt><dd><CellValue :column="c" :value="row[c.key]" /></dd></div>
        </template>
      </dl>
    </li>
    <li v-if="totals" class="vs__total">
      <dl>
        <template v-for="c in shown" :key="c.key">
          <div v-if="c.key in totals"><dt>Total · {{ c.label }}</dt><dd><CellValue :column="c" :value="totals[c.key]" /></dd></div>
        </template>
      </dl>
    </li>
  </ul>
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
.vs { list-style: none; margin: 0; padding: 0; }
.vs li { padding: 10px 14px; border-bottom: 1px solid var(--border-subtle); }
.vs li:last-child { border-bottom: 0; }
.vs__title { display: block; margin-bottom: 4px; font-size: 14px; color: var(--text-strong); }
.vs dl { margin: 0; display: flex; flex-direction: column; gap: 2px; }
.vs dl div { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
.vs dt { color: var(--text-muted); }
.vs dd { margin: 0; text-align: right; min-width: 0; overflow-wrap: anywhere; }
.vs__total { background: var(--surface-sunken, var(--surface-hover)); font-weight: 700; }
.vt-empty { margin: 0; padding: 20px 16px; color: var(--text-muted); font-size: 13px; }
</style>
