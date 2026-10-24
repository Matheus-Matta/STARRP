<script setup lang="ts">
/** DRE do período (`?de=&ate=`): da receita bruta ao resultado operacional, com % sobre a receita líquida. */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

import { financeApi } from "@/api/operations";
import { date, money, percent } from "@/utils/format";

import PrintShell, { type PrintFormat } from "../PrintShell.vue";

const props = defineProps<{ id?: string; initialFormat?: PrintFormat }>();
const route = useRoute();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const from = String(route.query.de ?? new Date(Date.now() - 29 * 86_400_000).toLocaleDateString("sv-SE"));
const to = String(route.query.ate ?? new Date().toLocaleDateString("sv-SE"));
const query = useQuery({ queryKey: ["print-dre", from, to], queryFn: () => financeApi.dre({ date_from: from, date_to: to }) });
const d = computed(() => query.data.value);
const net = computed(() => Number(d.value?.net_revenue ?? 0));
const pct = (v: unknown) => (net.value ? percent(((Number(v) / net.value) * 100).toFixed(2)) : "—");

type Line = { label: string; value: string; sign?: string; total?: boolean; indent?: boolean };
const lines = computed<Line[]>(() => {
  const x = d.value;
  if (!x) return [];
  return [
    { label: "Receita bruta de vendas", value: x.gross_revenue },
    { label: "Frete cobrado", value: x.freight, sign: "+" },
    { label: "Descontos concedidos", value: x.discounts, sign: "−" },
    { label: "Devoluções", value: x.returns, sign: "−" },
    { label: "Receita líquida", value: x.net_revenue, total: true },
    { label: "Custo das mercadorias vendidas (CMV)", value: x.cmv, sign: "−" },
    { label: "Lucro bruto", value: x.gross_profit, total: true },
    { label: "Taxas de cartão", value: x.card_fees, sign: "−" },
    { label: "Comissões", value: x.commissions, sign: "−" },
    { label: "Diferenças de caixa", value: x.cash_differences, sign: "±" },
    ...x.expenses.map((e) => ({ label: e.category, value: e.amount, sign: "−", indent: true })),
    { label: "Resultado operacional", value: x.operating_result, total: true },
  ];
});
</script>

<template>
  <PrintShell v-model:format="format" title="DRE — Demonstração do resultado" :formats="['a4']" :ready="!!d"
              :filename="`dre-${from}-a-${to}`" :subtitle="`Período de ${date(from)} a ${date(to)}`">
    <table v-if="d" class="pt dre">
      <thead><tr><th>Conta</th><th class="r">Valor</th><th class="r">% receita líquida</th></tr></thead>
      <tbody>
        <tr v-for="line in lines" :key="line.label" :class="{ total: line.total, indent: line.indent }">
          <td>{{ line.sign ? `(${line.sign}) ` : "" }}{{ line.label }}</td>
          <td class="r" :class="{ neg: line.total && Number(line.value) < 0 }">{{ money(line.value) }}</td>
          <td class="r">{{ pct(line.value) }}</td>
        </tr>
      </tbody>
    </table>
    <p class="doc-note">Regime de competência: vendas pela data de conclusão; despesas pela data de emissão do título.</p>
  </PrintShell>
</template>

<style scoped>
.dre { font-size: 10pt; }
.dre td { padding: 6px 8px; }
.dre tr.total td { font-weight: 700; background: #f3f4f6; border-top: 1.5px solid #111; }
.dre tr.indent td:first-child { padding-left: 24px; color: #444; }
.dre tr:last-child td { font-size: 11.5pt; }
</style>
