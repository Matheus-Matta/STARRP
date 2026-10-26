<script setup lang="ts">
/**
 * Painel de estoque: o que precisa de atenção hoje.
 * - produtos abaixo do mínimo (repor);
 * - lotes vencendo nos próximos dias (vender primeiro ou baixar);
 * - documentos em rascunho (esquecidos sem confirmar);
 * e atalhos para lançar entrada, saída, transferência e inventário.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";
import { computed } from "vue";
import { useRouter } from "vue-router";

import { stockApi } from "@/api/operations";
import { resourceApi } from "@/api/resource";
import EmptyState from "@/components/common/EmptyState.vue";
import PageHeader from "@/components/common/PageHeader.vue";
import SectionCard from "@/components/common/SectionCard.vue";
import StatCard from "@/components/common/StatCard.vue";
import { documentKind } from "@/resources/stock";
import { useSession } from "@/stores/session";
import { date, quantity } from "@/utils/format";

const router = useRouter();
const session = useSession();
const store = computed(() => session.activeStoreId);
const soon = new Date(Date.now() + 15 * 86_400_000).toLocaleDateString("sv-SE");
const today = new Date().toLocaleDateString("sv-SE");

const alerts = useQuery({ queryKey: computed(() => ["stock-alerts", store.value]), queryFn: stockApi.alerts });
const lots = useQuery({
  queryKey: computed(() => ["lots-expiring", store.value]),
  queryFn: () => resourceApi.list("/stock/lots/", { status: "available", expires_at__lte: soon, ordering: "expires_at", page_size: 8 }),
});
const drafts = useQuery({
  queryKey: computed(() => ["stock-drafts", store.value]),
  queryFn: () => resourceApi.list("/stock/documents/", { status: "draft", ordering: "-number", page_size: 8 }),
});
const movesToday = useQuery({
  queryKey: computed(() => ["moves-today", store.value]),
  queryFn: () => resourceApi.list("/stock/movements/", { created_at__gte: today, page_size: 1 }),
});

const loading = computed(() => alerts.isPending.value || lots.isPending.value || drafts.isPending.value);
const cards = computed(() => [
  { label: "Abaixo do mínimo", value: String(alerts.data.value?.length ?? 0), icon: "pi pi-exclamation-triangle",
    tone: (alerts.data.value?.length ? "danger" : "success") as "danger" | "success", caption: "produtos para repor" },
  { label: "Lotes vencendo", value: String(lots.data.value?.count ?? 0), icon: "pi pi-calendar-clock",
    tone: "warning" as const, caption: "nos próximos 15 dias" },
  { label: "Rascunhos", value: String(drafts.data.value?.count ?? 0), icon: "pi pi-file-edit", tone: "info" as const,
    caption: "lançamentos sem confirmar" },
  { label: "Movimentos hoje", value: String(movesToday.data.value?.count ?? 0), icon: "pi pi-arrow-right-arrow-left",
    tone: "brand" as const, caption: "entradas e saídas" },
]);

const QUICK = [
  { kind: "entry", label: "Entrada", icon: "pi pi-download" },
  { kind: "exit", label: "Saída", icon: "pi pi-upload" },
  { kind: "transfer", label: "Transferência", icon: "pi pi-arrow-right-arrow-left" },
  { kind: "inventory", label: "Inventário", icon: "pi pi-list-check" },
];
const newDoc = (kind: string) => router.push(`/cadastros/entradas-e-saidas/novo?kind=${kind}`);
const daysTo = (iso: string) => Math.round((new Date(`${iso}T00:00:00`).getTime() - new Date(`${today}T00:00:00`).getTime()) / 86_400_000);
</script>

<template>
  <section class="page">
    <PageHeader title="Painel de estoque" icon="pi pi-warehouse" :subtitle="session.activeStore?.name ?? 'Todas as minhas filiais'">
      <Button v-for="q in QUICK" :key="q.kind" :label="q.label" :icon="q.icon" size="small" severity="secondary" outlined
              @click="newDoc(q.kind)" />
    </PageHeader>

    <div class="cards">
      <template v-if="loading"><Skeleton v-for="n in 4" :key="n" height="7.2rem" border-radius="12px" /></template>
      <StatCard v-for="card in cards" v-else :key="card.label" v-bind="card" />
    </div>

    <div class="two">
      <SectionCard title="Abaixo do estoque mínimo" description="Somando os depósitos da filial" icon="pi pi-exclamation-triangle">
        <div v-if="alerts.isPending.value" class="stack"><Skeleton v-for="n in 4" :key="n" height="1.8rem" /></div>
        <EmptyState v-else-if="!alerts.data.value?.length" title="Tudo acima do mínimo" icon="pi pi-check-circle"
                    description="Defina o estoque mínimo nas variantes do produto para ser avisado aqui." />
        <table v-else class="list">
          <thead><tr><th>Produto</th><th class="right">Saldo</th><th class="right">Mínimo</th></tr></thead>
          <tbody>
            <tr v-for="a in alerts.data.value" :key="a.id" @click="router.push(`/cadastros/produtos/${a.product}`)">
              <td><strong>{{ a.product_name }}</strong> <small class="muted">{{ a.name }} · {{ a.sku }}</small></td>
              <td class="right neg">{{ quantity(a.stock) }}</td>
              <td class="right">{{ quantity(a.min_stock) }}</td>
            </tr>
          </tbody>
        </table>
      </SectionCard>

      <SectionCard title="Lotes vencendo" description="Próximos 15 dias: venda primeiro ou dê baixa" icon="pi pi-calendar-clock">
        <template #actions>
          <Button label="Ver todos" text size="small" @click="router.push(`/cadastros/lotes?status=available&expires_at__lte=${soon}`)" />
        </template>
        <div v-if="lots.isPending.value" class="stack"><Skeleton v-for="n in 4" :key="n" height="1.8rem" /></div>
        <EmptyState v-else-if="!lots.data.value?.results.length" title="Nenhum lote vencendo" icon="pi pi-check-circle"
                    description="Lotes com validade nos próximos 15 dias aparecem aqui." />
        <table v-else class="list">
          <thead><tr><th>Produto</th><th>Validade</th><th class="right">Saldo</th></tr></thead>
          <tbody>
            <tr v-for="lot in lots.data.value.results" :key="String(lot.id)" @click="router.push(`/cadastros/lotes/${lot.id}`)">
              <td><strong>{{ lot.variant_name }}</strong> <small class="muted">lote {{ lot.lot_number || lot.code }}</small></td>
              <td>
                {{ date(lot.expires_at) }}
                <span class="pill pill--after" :class="daysTo(String(lot.expires_at)) < 0 ? 'pill--danger' : 'pill--warning'">
                  {{ daysTo(String(lot.expires_at)) < 0 ? "vencido" : `${daysTo(String(lot.expires_at))} dias` }}
                </span>
              </td>
              <td class="right">{{ quantity(lot.quantity) }}</td>
            </tr>
          </tbody>
        </table>
      </SectionCard>
    </div>

    <SectionCard title="Entradas e saídas em rascunho" description="Só movem o estoque depois de confirmados" icon="pi pi-file-edit">
      <template #actions>
        <Button label="Ver todos" text size="small" @click="router.push('/cadastros/entradas-e-saidas?status=draft')" />
      </template>
      <div v-if="drafts.isPending.value" class="stack"><Skeleton v-for="n in 3" :key="n" height="1.8rem" /></div>
      <EmptyState v-else-if="!drafts.data.value?.results.length" title="Nenhum rascunho" icon="pi pi-check-circle"
                  description="Tudo o que foi lançado já está confirmado." />
      <table v-else class="hide-sm-3 hide-sm-4 list">
        <thead><tr><th>Nº</th><th>Tipo</th><th>Depósito</th><th>Data</th><th class="right">Itens</th></tr></thead>
        <tbody>
          <tr v-for="doc in drafts.data.value.results" :key="String(doc.id)"
              @click="router.push(`/cadastros/entradas-e-saidas/${doc.id}`)">
            <td><strong>{{ doc.number }}</strong></td>
            <td><span class="pill pill--brand">{{ documentKind.map[String(doc.kind)] }}</span></td>
            <td>{{ doc.warehouse_name }}</td>
            <td>{{ date(doc.effective_date) }}</td>
            <td class="right">{{ doc.item_count }}</td>
          </tr>
        </tbody>
      </table>
    </SectionCard>
  </section>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr)); gap: 1rem; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap: 1rem; }
.stack { display: flex; flex-direction: column; gap: 8px; }
.list { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.list th { text-align: left; padding: 8px 10px; font: 650 11.5px/1.3 var(--font-sans); letter-spacing: 0.04em; text-transform: uppercase;
           color: var(--text-muted); background: var(--surface-sunken); }
.list td { padding: 9px 10px; border-top: 1px solid var(--border-subtle); }
.list tbody tr { cursor: pointer; transition: background-color var(--dur-fast) ease; }
.list tbody tr:hover { background: var(--surface-hover); }
.list .pill--after { margin-left: 6px; }
.right, .list .right { text-align: right; }
.neg { color: var(--danger-text); font-weight: 700; }
@media (max-width: 520px) { .two { grid-template-columns: 1fr; } .cards { grid-template-columns: 1fr 1fr; gap: 0.6rem; } }
</style>
