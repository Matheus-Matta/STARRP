<script setup lang="ts">
/** Fechamento do turno de caixa: vendas, formas de pagamento, gaveta e diferença. */
import { useQuery } from "@tanstack/vue-query";
import Skeleton from "primevue/skeleton";
import { computed } from "vue";

import { financeApi } from "@/api/operations";
import type { FormActionContext } from "@/resources/types";
import { dateTime, money } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const report = useQuery({ queryKey: ["cash-report", props.ctx.id], queryFn: () => financeApi.cashReport(props.ctx.id) });
const r = computed(() => report.data.value);
const DRAWER: [string, string][] = [
  ["opening", "Troco inicial"], ["sale", "Vendas em dinheiro"], ["supply", "Suprimentos"], ["withdrawal", "Sangrias"],
  ["refund", "Devoluções em dinheiro"], ["expected", "Esperado na gaveta"], ["counted", "Contado"],
];
const difference = computed(() => Number(r.value?.drawer.difference ?? 0));
</script>

<template>
  <div v-if="!r" class="stack"><Skeleton v-for="n in 6" :key="n" height="1.4rem" /></div>
  <div v-else class="report">
    <p class="muted">{{ r.session.register }} · aberto {{ dateTime(r.session.opened_at) }} por {{ r.session.opened_by }}
      <template v-if="r.session.closed_at"> · fechado {{ dateTime(r.session.closed_at) }} por {{ r.session.closed_by }}</template></p>
    <div class="kpis">
      <div><small>Vendas</small><strong>{{ money(r.sales.total) }}</strong><span>{{ r.sales.count }} vendas</span></div>
      <div><small>Ticket médio</small><strong>{{ money(r.sales.average_ticket) }}</strong></div>
      <div><small>Margem bruta</small><strong>{{ money(r.sales.gross_margin) }}</strong><span>custo {{ money(r.sales.cost) }}</span></div>
      <div><small>Descontos</small><strong>{{ money(r.sales.discounts) }}</strong>
        <span>{{ r.sales.cancelled_count }} canceladas ({{ money(r.sales.cancelled_total) }})</span></div>
    </div>
    <div class="cols">
      <section>
        <h3>Formas de pagamento</h3>
        <div v-for="m in r.by_payment_method" :key="m.method__name" class="line">
          <span>{{ m.method__name }} <small class="muted">· {{ m.count }}</small></span><strong>{{ money(m.total) }}</strong>
        </div>
        <p v-if="!r.by_payment_method.length" class="muted">Nenhum pagamento.</p>
      </section>
      <section>
        <h3>Gaveta</h3>
        <div v-for="[key, label] in DRAWER" :key="key" class="line" :class="{ total: key === 'expected' }">
          <span>{{ label }}</span><strong>{{ r.drawer[key] == null ? "—" : money(r.drawer[key]) }}</strong>
        </div>
        <div v-if="r.drawer.difference != null" class="line diff" :class="difference < 0 ? 'neg' : difference > 0 ? 'pos' : 'zero'">
          <span>Diferença</span><strong>{{ money(r.drawer.difference) }}</strong>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 8px; }
.report > p { margin: 0 0 0.75rem; font-size: 12.5px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.5rem; }
.kpis div { display: flex; flex-direction: column; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; }
.kpis small { font-size: 12px; color: var(--text-muted); }
.kpis strong { font-size: 18px; color: var(--text-strong); }
.kpis span { font-size: 11.5px; color: var(--text-muted); }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-top: 1rem; }
h3 { font: 650 12px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); margin-bottom: 0.4rem; }
.line { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border-subtle); font-size: 13.5px; }
.line.total { font-weight: 700; }
.diff.neg strong { color: var(--danger-text); }
.diff.pos strong { color: var(--warning-text); }
.diff.zero strong { color: var(--success-text); }
@media (max-width: 640px) { .cols { grid-template-columns: 1fr; } }
</style>
