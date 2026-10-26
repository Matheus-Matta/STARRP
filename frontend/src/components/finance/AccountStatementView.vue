<script setup lang="ts">
/** Extrato da conta financeira: saldo inicial, cada lançamento com o saldo corrido e o saldo final do período. */
import { useQuery } from "@tanstack/vue-query";
import DatePicker from "primevue/datepicker";
import Skeleton from "primevue/skeleton";
import { computed, ref } from "vue";

import Button from "primevue/button";

import { financeApi } from "@/api/operations";
import { openPrint } from "@/utils/print";
import { date, money } from "@/utils/format";

const props = defineProps<{ id: string; values: Record<string, unknown> }>();
const range = ref<(Date | null)[]>([new Date(Date.now() - 29 * 86_400_000), new Date()]);
const iso = (d: Date | null | undefined) => (d ? d.toLocaleDateString("sv-SE") : undefined);
const params = computed(() => ({ date_from: iso(range.value[0]), date_to: iso(range.value[1] ?? range.value[0]) }));
const query = useQuery({
  queryKey: computed(() => ["account-statement", props.id, params.value]),
  queryFn: () => financeApi.accountStatement(props.id, params.value),
});
const s = computed(() => query.data.value);
const inflow = computed(() => (s.value?.lines ?? []).filter((l) => l.kind === "in").reduce((t, l) => t + Number(l.amount), 0));
const outflow = computed(() => (s.value?.lines ?? []).filter((l) => l.kind === "out").reduce((t, l) => t + Number(l.amount), 0));
</script>

<template>
  <div class="statement">
    <div class="bar">
      <Button label="Imprimir" icon="pi pi-print" size="small" severity="secondary" outlined
              @click="openPrint('conta', id, { de: params.date_from, ate: params.date_to })" />
      <DatePicker v-model="range" selection-mode="range" date-format="dd/mm/yy" show-icon :manual-input="false" size="small" />
    </div>
    <div v-if="!s" class="stack"><Skeleton v-for="i in 6" :key="i" height="2.2rem" /></div>
    <template v-else>
      <div class="kpis">
        <div><small>Saldo inicial</small><strong>{{ money(s.opening_balance) }}</strong></div>
        <div><small>Entradas</small><strong class="pos">{{ money(inflow) }}</strong></div>
        <div><small>Saídas</small><strong class="neg">{{ money(outflow) }}</strong></div>
        <div><small>Saldo final</small><strong>{{ money(s.closing_balance) }}</strong></div>
      </div>
      <table class="hide-sm-3 list">
        <thead><tr><th>Data</th><th>Descrição</th><th>Categoria</th><th class="right">Valor</th><th class="right">Saldo</th></tr></thead>
        <tbody>
          <tr class="opening"><td colspan="4">Saldo anterior</td><td class="right">{{ money(s.opening_balance) }}</td></tr>
          <tr v-for="(line, i) in s.lines" :key="i">
            <td>{{ date(line.date) }}</td><td><strong>{{ line.description }}</strong></td><td>{{ line.category || "—" }}</td>
            <td class="right" :class="line.kind === 'in' ? 'pos' : 'neg'">{{ line.kind === "in" ? "+" : "−" }} {{ money(line.amount) }}</td>
            <td class="right" :class="{ neg: Number(line.balance) < 0 }">{{ money(line.balance) }}</td>
          </tr>
          <tr v-if="!s.lines.length"><td colspan="5" class="muted empty">Nenhum lançamento no período.</td></tr>
        </tbody>
      </table>
    </template>
  </div>
</template>

<style scoped>
.statement, .stack { display: flex; flex-direction: column; gap: 1rem; }
.bar { display: flex; justify-content: flex-end; gap: 0.5rem; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr)); gap: 0.6rem; }
.kpis div { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); }
.kpis small { font-size: 12px; color: var(--text-muted); }
.kpis strong { font-size: 19px; color: var(--text-strong); }
.list { width: 100%; border-collapse: collapse; font-size: 13.5px; background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.list th { text-align: left; padding: 9px 10px; font: 650 11.5px/1.3 var(--font-sans); letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); background: var(--surface-sunken); }
.list td { padding: 9px 10px; border-top: 1px solid var(--border-subtle); }
.opening td { color: var(--text-muted); font-style: italic; }
.right, .list .right { text-align: right; }
.pos { color: var(--success-text); }
.neg { color: var(--danger-text); }
.empty { text-align: center; padding: 18px; }
</style>
