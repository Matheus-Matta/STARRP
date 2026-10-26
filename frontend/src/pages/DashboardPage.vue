<script setup lang="ts">
/** Painel: indicadores, vendas por dia e rankings do período escolhido. */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { reportsApi } from "@/api/reports";
import BarChart from "@/components/common/BarChart.vue";
import PageHeader from "@/components/common/PageHeader.vue";
import RankList from "@/components/common/RankList.vue";
import SectionCard from "@/components/common/SectionCard.vue";
import StatCard from "@/components/common/StatCard.vue";
import { useSession } from "@/stores/session";
import { money, plural } from "@/utils/format";

const session = useSession();
const router = useRouter();
const days = ref(30);
const periods = [{ label: "7 dias", value: 7 }, { label: "30 dias", value: 30 }, { label: "90 dias", value: 90 }];
const dateFrom = computed(() => new Date(Date.now() - (days.value - 1) * 86_400_000).toLocaleDateString("sv-SE"));

const query = useQuery({
  queryKey: computed(() => ["dashboard", session.activeStoreId, days.value]),
  queryFn: () => reportsApi.dashboard({ date_from: dateFrom.value }),
});
const data = computed(() => query.data.value);

const cards = computed(() => {
  const s = data.value?.summary;
  if (!s) return [];
  return [
    { label: "Faturamento", value: money(s.revenue), icon: "pi pi-wallet", tone: "brand" as const, caption: plural(s.sales_count, "venda", "vendas") },
    { label: "Ticket médio", value: money(s.average_ticket), icon: "pi pi-receipt", tone: "info" as const },
    { label: "Margem bruta", value: money(s.gross_margin), icon: "pi pi-chart-line", tone: "success" as const },
    { label: "Descontos", value: money(s.discounts), icon: "pi pi-percentage", tone: "warning" as const },
    { label: "Devoluções", value: money(s.returns_total), icon: "pi pi-replay", tone: "danger" as const,
      caption: plural(s.cancelled_count, "cancelamento", "cancelamentos") },
    { label: "Vendas em aberto", value: String(data.value?.open_sales ?? 0), icon: "pi pi-clock", tone: "info" as const },
  ];
});

/** Um ponto por dia do período, com zero nos dias sem venda (o eixo não "pula" dias). */
const chart = computed(() => {
  const byDay = new Map((data.value?.by_day ?? []).map((d) => [d.day, d]));
  return Array.from({ length: days.value }, (_, i) => {
    const day = new Date(`${dateFrom.value}T00:00:00`);
    day.setDate(day.getDate() + i);
    const key = day.toLocaleDateString("sv-SE");
    const row = byDay.get(key);
    return {
      label: day.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }),
      value: Number(row?.revenue ?? 0),
      // Balão com o dia por extenso ("sáb., 24/10") + o valor; sem venda, diz isso.
      hint: `${day.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" })} · ${
        row ? `${money(row.revenue)} · ${plural(row.count, "venda", "vendas")}` : "sem vendas"}`,
    };
  });
});
const products = computed(() => (data.value?.top_products ?? []).map((p) => ({
  label: p.description, value: Number(p.revenue), display: money(p.revenue),
  meta: `${Number(p.sold_quantity).toLocaleString("pt-BR")} un · margem ${money(p.margin)}`,
})));
const methods = computed(() => (data.value?.by_payment_method ?? []).map((m) => ({
  label: m.method__name, value: Number(m.total), display: money(m.total), meta: plural(m.count, "pagamento", "pagamentos"),
})));
</script>

<template>
  <section class="page">
    <PageHeader title="Painel" icon="pi pi-chart-bar"
                :subtitle="`${session.activeStore?.name ?? 'Todas as minhas filiais'} · últimos ${days} dias`">
      <SelectButton v-model="days" :options="periods" option-label="label" option-value="value" :allow-empty="false" />
      <Button v-if="session.can('sales.manage')" label="Abrir PDV" icon="pi pi-shopping-cart" @click="router.push('/pdv')" />
    </PageHeader>

    <div class="cards">
      <template v-if="query.isLoading.value">
        <Skeleton v-for="n in 6" :key="n" height="7.2rem" border-radius="12px" />
      </template>
      <StatCard v-for="(card, index) in cards" v-else :key="card.label" v-bind="card" :style="{ animationDelay: `${index * 40}ms` }" />
    </div>

    <SectionCard title="Vendas por dia" description="Faturamento das vendas concluídas" icon="pi pi-chart-bar">
      <Skeleton v-if="query.isLoading.value" height="220px" />
      <BarChart v-else :points="chart" />
    </SectionCard>

    <div class="two">
      <SectionCard title="Mais vendidos" description="Por faturamento" icon="pi pi-star">
        <RankList :rows="products" />
      </SectionCard>
      <SectionCard title="Formas de pagamento" description="Recebido por forma" icon="pi pi-credit-card">
        <RankList :rows="methods" />
      </SectionCard>
    </div>
  </section>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr)); gap: 1rem; }
@media (max-width: 520px) { .cards { grid-template-columns: 1fr 1fr; gap: 0.6rem; } }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(360px, 100%), 1fr)); gap: 1rem; }
</style>
