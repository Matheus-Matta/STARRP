<script setup lang="ts">
/**
 * Painel financeiro: quanto tem, quanto vence e se a loja deu lucro.
 * - saldo de cada conta (com transferência entre elas);
 * - a receber e a pagar por vencimento (vencido, 7 dias, 30 dias, depois);
 * - fluxo de caixa do período (entradas × saídas por dia);
 * - DRE do período: receita → CMV → lucro bruto → despesas → resultado.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { financeApi } from "@/api/operations";
import PageHeader from "@/components/common/PageHeader.vue";
import SectionCard from "@/components/common/SectionCard.vue";
import StatCard from "@/components/common/StatCard.vue";
import CashFlowChart from "@/components/finance/CashFlowChart.vue";
import RelationSelect from "@/components/resource/RelationSelect.vue";
import { useNotify } from "@/composables/useNotify";
import { useSession } from "@/stores/session";
import { money, percent } from "@/utils/format";
import { openPrint } from "@/utils/print";

const router = useRouter();
const session = useSession();
const notify = useNotify();
const queryClient = useQueryClient();
const days = ref(30);
const periods = [{ label: "7 dias", value: 7 }, { label: "30 dias", value: 30 }, { label: "90 dias", value: 90 }];
const period = computed(() => ({
  date_from: new Date(Date.now() - (days.value - 1) * 86_400_000).toLocaleDateString("sv-SE"),
  date_to: new Date().toLocaleDateString("sv-SE"),
}));
const store = computed(() => session.activeStoreId);

const balances = useQuery({ queryKey: computed(() => ["fin-balances", store.value]), queryFn: financeApi.balances });
const aging = useQuery({ queryKey: computed(() => ["fin-aging", store.value]), queryFn: financeApi.aging });
const flow = useQuery({ queryKey: computed(() => ["fin-flow", store.value, days.value]), queryFn: () => financeApi.cashFlow(period.value) });
const dre = useQuery({ queryKey: computed(() => ["fin-dre", store.value, days.value]), queryFn: () => financeApi.dre(period.value) });

const n = (v: unknown) => Number(v ?? 0);
const cards = computed(() => {
  const a = aging.data.value;
  return [
    { label: "Saldo em contas", value: money(balances.data.value?.total), icon: "pi pi-wallet", tone: "brand" as const,
      caption: `${balances.data.value?.accounts.length ?? 0} contas` },
    { label: "A receber vencido", value: money(a?.receivable.overdue), icon: "pi pi-arrow-down-left", tone: "warning" as const,
      caption: `+ ${money(a?.receivable.next_7_days)} em 7 dias` },
    { label: "A pagar vencido", value: money(a?.payable.overdue), icon: "pi pi-arrow-up-right", tone: "danger" as const,
      caption: `+ ${money(a?.payable.next_7_days)} em 7 dias` },
    { label: "Resultado do período", value: money(dre.data.value?.operating_result), icon: "pi pi-chart-line",
      tone: (n(dre.data.value?.operating_result) >= 0 ? "success" : "danger") as "success" | "danger",
      caption: `margem ${percent(dre.data.value?.operating_margin_percent)}` },
  ];
});

const chart = computed(() => {
  const byDay = new Map((flow.data.value?.by_day ?? []).map((d) => [d.date, d]));
  return Array.from({ length: days.value }, (_, i) => {
    const day = new Date(`${period.value.date_from}T00:00:00`);
    day.setDate(day.getDate() + i);
    const row = byDay.get(day.toLocaleDateString("sv-SE"));
    return { label: day.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }), inflow: n(row?.inflow), outflow: n(row?.outflow) };
  });
});

/** Linhas da DRE: o que soma (+), o que desconta (−) e os subtotais. */
type DreLine = { label: string; value: string; sign?: string; total?: boolean; final?: boolean; indent?: boolean; pct?: string };
const dreLines = computed<DreLine[]>(() => {
  const d = dre.data.value;
  if (!d) return [];
  return [
    { label: "Receita bruta", value: d.gross_revenue },
    { label: "Frete cobrado", value: d.freight, sign: "+" },
    { label: "Descontos", value: d.discounts, sign: "−" },
    { label: "Devoluções", value: d.returns, sign: "−" },
    { label: "Receita líquida", value: d.net_revenue, total: true },
    { label: "Custo das mercadorias (CMV)", value: d.cmv, sign: "−" },
    { label: "Lucro bruto", value: d.gross_profit, total: true, pct: d.gross_margin_percent },
    { label: "Taxas de cartão", value: d.card_fees, sign: "−" },
    { label: "Comissões", value: d.commissions, sign: "−" },
    { label: "Diferenças de caixa", value: d.cash_differences, sign: "±" },
    ...d.expenses.map((e) => ({ label: e.category, value: e.amount, sign: "−", indent: true })),
    { label: "Resultado operacional", value: d.operating_result, total: true, pct: d.operating_margin_percent, final: true },
  ];
});

const BUCKETS: [keyof NonNullable<typeof aging.data.value>["receivable"], string][] = [
  ["overdue", "Vencido"], ["next_7_days", "Próximos 7 dias"], ["next_30_days", "8 a 30 dias"], ["later", "Depois"],
];
const today = new Date();
const plus = (d: number) => new Date(today.getTime() + d * 86_400_000).toLocaleDateString("sv-SE");
function openDue(kind: string, bucket: string) {
  const range: Record<string, string> = {
    overdue: `due_date__lte=${plus(-1)}`, next_7_days: `due_date__gte=${plus(0)}&due_date__lte=${plus(7)}`,
    next_30_days: `due_date__gte=${plus(8)}&due_date__lte=${plus(30)}`, later: `due_date__gte=${plus(31)}`,
  };
  router.push(`/cadastros/vencimentos?title__kind=${kind}&status=open&${range[bucket]}`);
}

// Transferência entre contas
const transferring = ref(false);
const transfer = ref({ source: null as string | null, target: null as string | null, amount: 0, description: "" });
const saving = ref(false);
async function doTransfer() {
  if (!transfer.value.source || !transfer.value.target || transfer.value.amount <= 0) return notify.warn("Preencha origem, destino e valor.");
  saving.value = true;
  try {
    await financeApi.transfer({ source: transfer.value.source, target: transfer.value.target,
                                amount: transfer.value.amount.toFixed(2), description: transfer.value.description });
    notify.success("Transferência feita");
    transferring.value = false;
    await queryClient.invalidateQueries({ queryKey: ["fin-balances"] });
    await queryClient.invalidateQueries({ queryKey: ["fin-flow"] });
  } catch (error) {
    notify.error(error, "Não foi possível transferir");
  } finally {
    saving.value = false;
  }
}
const accountRelation = { endpoint: "/finance/accounts/", params: { is_active: "true" } };
</script>

<template>
  <section class="page">
    <PageHeader title="Painel financeiro" icon="pi pi-chart-line"
                :subtitle="`${session.activeStore?.name ?? 'Todas as minhas lojas'} · últimos ${days} dias`">
      <SelectButton v-model="days" :options="periods" option-label="label" option-value="value" :allow-empty="false" />
      <Button label="Lançamento" icon="pi pi-plus" size="small" severity="secondary" outlined
              @click="router.push('/cadastros/lancamentos/novo')" />
      <Button label="Conta a pagar" icon="pi pi-plus" size="small" @click="router.push('/cadastros/contas-a-pagar/novo')" />
    </PageHeader>

    <div class="cards">
      <template v-if="balances.isPending.value || aging.isPending.value">
        <Skeleton v-for="i in 4" :key="i" height="7.2rem" border-radius="12px" />
      </template>
      <StatCard v-for="card in cards" v-else :key="card.label" v-bind="card" />
    </div>

    <div class="two">
      <SectionCard title="Saldo por conta" description="Saldo inicial + lançamentos" icon="pi pi-wallet">
        <template #actions>
          <Button label="Transferir" icon="pi pi-arrow-right-arrow-left" size="small" text @click="transferring = true" />
        </template>
        <div v-if="balances.isPending.value" class="stack"><Skeleton v-for="i in 3" :key="i" height="1.8rem" /></div>
        <div v-else class="lines">
          <div v-for="acc in balances.data.value?.accounts" :key="acc.id" class="line"
               @click="router.push(`/cadastros/lancamentos?financial_account=${acc.id}`)">
            <span>{{ acc.name }}</span>
            <strong :class="{ neg: n(acc.balance) < 0 }">{{ money(acc.balance) }}</strong>
          </div>
          <div class="line total"><span>Total</span><strong>{{ money(balances.data.value?.total) }}</strong></div>
        </div>
      </SectionCard>

      <SectionCard title="Vencimentos em aberto" description="Clique para ver as parcelas" icon="pi pi-calendar">
        <div v-if="aging.isPending.value" class="stack"><Skeleton v-for="i in 4" :key="i" height="1.8rem" /></div>
        <table v-else class="aging">
          <thead><tr><th /><th class="right">A receber</th><th class="right">A pagar</th></tr></thead>
          <tbody>
            <tr v-for="[key, label] in BUCKETS" :key="key" :class="{ late: key === 'overdue' }">
              <td>{{ label }}</td>
              <td class="right link" @click="openDue('receivable', key)">{{ money(aging.data.value?.receivable[key]) }}</td>
              <td class="right link" @click="openDue('payable', key)">{{ money(aging.data.value?.payable[key]) }}</td>
            </tr>
          </tbody>
        </table>
      </SectionCard>
    </div>

    <SectionCard title="Fluxo de caixa" icon="pi pi-chart-bar"
                 :description="flow.data.value ? `Entrou ${money(flow.data.value.inflow)} · saiu ${money(flow.data.value.outflow)} · saldo final ${money(flow.data.value.closing_balance)}` : 'Entradas e saídas por dia'">
      <Skeleton v-if="flow.isPending.value" height="220px" />
      <CashFlowChart v-else :days="chart" />
    </SectionCard>

    <SectionCard title="DRE do período" description="Resultado das vendas menos custos e despesas" icon="pi pi-calculator">
      <template #actions>
        <Button label="Imprimir DRE" icon="pi pi-print" size="small" text
                @click="openPrint('dre', '', { de: period.date_from, ate: period.date_to })" />
      </template>
      <div v-if="dre.isPending.value" class="stack"><Skeleton v-for="i in 8" :key="i" height="1.5rem" /></div>
      <div v-else class="dre">
        <div v-for="line in dreLines" :key="line.label" class="dre__line"
             :class="{ total: line.total, final: line.final, indent: line.indent }">
          <span>{{ line.sign ? `(${line.sign}) ` : "" }}{{ line.label }}</span>
          <span class="pct">{{ line.pct ? percent(line.pct) : "" }}</span>
          <strong :class="{ neg: line.final && n(line.value) < 0 }">{{ money(line.value) }}</strong>
        </div>
      </div>
    </SectionCard>

    <Dialog v-model:visible="transferring" modal header="Transferir entre contas" :style="{ width: 'min(440px, calc(100vw - 24px))' }">
      <div class="grid-form">
        <div class="field full"><label>De</label><RelationSelect v-model="transfer.source" :relation="accountRelation" /></div>
        <div class="field full"><label>Para</label><RelationSelect v-model="transfer.target" :relation="accountRelation" /></div>
        <div class="field span-3"><label>Valor</label>
          <InputNumber v-model="transfer.amount" mode="currency" currency="BRL" locale="pt-BR" fluid /></div>
        <div class="field span-3"><label>Descrição</label><InputText v-model="transfer.description" placeholder="Depósito do cofre" fluid /></div>
      </div>
      <template #footer>
        <Button label="Cancelar" severity="secondary" text @click="transferring = false" />
        <Button label="Transferir" icon="pi pi-check" :loading="saving" @click="doTransfer" />
      </template>
    </Dialog>
  </section>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 1rem; }
.stack { display: flex; flex-direction: column; gap: 8px; }
.lines { display: flex; flex-direction: column; }
.line { display: flex; justify-content: space-between; padding: 9px 4px; border-bottom: 1px solid var(--border-subtle); font-size: 13.5px; cursor: pointer; }
.line:hover { background: var(--surface-hover); }
.line.total { cursor: default; font-weight: 700; border-bottom: 0; }
.line.total:hover { background: none; }
.neg { color: var(--danger-text); }
.aging { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.aging th { padding: 8px; font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); background: var(--surface-sunken); }
.aging td { padding: 9px 8px; border-top: 1px solid var(--border-subtle); }
.aging .late td { color: var(--danger-text); font-weight: 600; }
.link { cursor: pointer; text-decoration: underline; text-decoration-color: var(--border-strong); text-underline-offset: 3px; }
.link:hover { text-decoration-color: currentColor; }
.right { text-align: right; }
.dre { display: flex; flex-direction: column; max-width: 720px; }
.dre__line { display: grid; grid-template-columns: 1fr 80px 140px; gap: 0.5rem; padding: 7px 4px; border-bottom: 1px solid var(--border-subtle); font-size: 13.5px; }
.dre__line strong { text-align: right; font-weight: 600; }
.dre__line .pct { text-align: right; color: var(--text-muted); font-size: 12.5px; }
.dre__line.indent span:first-child { padding-left: 1.25rem; color: var(--text-muted); }
.dre__line.total { font-weight: 700; color: var(--text-strong); background: var(--surface-sunken); }
.dre__line.final { font-size: 15px; border-bottom: 0; }
@media (max-width: 520px) { .two { grid-template-columns: 1fr; } .cards { grid-template-columns: 1fr 1fr; } }
</style>
