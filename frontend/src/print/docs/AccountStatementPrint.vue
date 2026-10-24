<script setup lang="ts">
/** Extrato da conta financeira no período (`?de=AAAA-MM-DD&ate=AAAA-MM-DD`), com saldo corrido. */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

import { financeApi } from "@/api/operations";
import type { ColumnDef } from "@/resources/types";
import { date, money } from "@/utils/format";

import PrintMeta from "../PrintMeta.vue";
import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const route = useRoute();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const today = new Date().toLocaleDateString("sv-SE");
const from = String(route.query.de ?? new Date(Date.now() - 29 * 86_400_000).toLocaleDateString("sv-SE"));
const to = String(route.query.ate ?? today);
const query = useQuery({ queryKey: ["print-account", props.id, from, to],
                         queryFn: () => financeApi.accountStatement(props.id, { date_from: from, date_to: to }) });
const s = computed(() => query.data.value);
const rows = computed(() => (s.value?.lines ?? []).map((l) => ({
  ...l, inflow: l.kind === "in" ? l.amount : null, outflow: l.kind === "out" ? l.amount : null,
})));
const total = (key: "inflow" | "outflow") => rows.value.reduce((t, r) => t + Number(r[key] ?? 0), 0).toFixed(2);
const columns: ColumnDef[] = [
  { key: "date", label: "Data", type: "date" }, { key: "description", label: "Descrição" }, { key: "category", label: "Categoria" },
  { key: "inflow", label: "Entrada", type: "money" }, { key: "outflow", label: "Saída", type: "money" },
  { key: "balance", label: "Saldo", type: "money" },
];
</script>

<template>
  <PrintShell v-model:format="format" title="Extrato da conta" :formats="['a4', 'a4-landscape']" :ready="!!s"
              :filename="`extrato-${s?.account ?? 'conta'}-${from}-a-${to}`" :subtitle="s ? `${s.account} · ${date(from)} a ${date(to)}` : ''">
    <template v-if="s">
      <PrintMeta :columns="4" :items="[
        ['Saldo anterior', money(s.opening_balance)], ['Entradas', money(total('inflow'))],
        ['Saídas', money(total('outflow'))], ['Saldo final', money(s.closing_balance)],
      ]" />
      <PrintTable :columns="columns" :rows="rows" empty="Nenhum lançamento no período."
                  :totals="{ description: 'Totais do período', inflow: total('inflow'), outflow: total('outflow'), balance: s.closing_balance }" />
    </template>
  </PrintShell>
</template>
