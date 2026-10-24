<script setup lang="ts">
/**
 * Extrato do turno de caixa (a conferência linha a linha, como no StarChef):
 * identificação, resumo, formas de pagamento, gaveta, ocorrências, movimentos da
 * gaveta, vendas do turno e itens vendidos somados por produto. Imprime e exporta CSV.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";
import { computed } from "vue";
import { useRouter } from "vue-router";

import { financeApi } from "@/api/operations";
import { openPrint } from "@/utils/print";
import SectionCard from "@/components/common/SectionCard.vue";
import { dateTime, money, quantity } from "@/utils/format";

const props = defineProps<{ id: string; values: Record<string, unknown> }>();
const router = useRouter();
const query = useQuery({ queryKey: ["cash-statement", props.id], queryFn: () => financeApi.cashStatement(props.id) });
const s = computed(() => query.data.value);

const STATUS: Record<string, string> = { open: "Aberto", pending_approval: "Aguardando gerente", closed: "Fechado", cancelled: "Cancelado" };
const DRAWER: [string, string][] = [
  ["opening", "Troco inicial"], ["sale", "Vendas em dinheiro"], ["supply", "Suprimentos"], ["withdrawal", "Sangrias"],
  ["refund", "Devoluções em dinheiro"], ["expected", "Esperado na gaveta"], ["counted", "Contado"], ["difference", "Diferença"],
];
const n = (v: unknown) => Number(v ?? 0);
const printPage = () => openPrint("turno", props.id, { formato: "a4" });

function csv() {
  const r = s.value!;
  const lines = [
    ["Extrato do turno", r.session.register, dateTime(r.session.opened_at)],
    [],
    ["Vendas"], ["Nº", "Hora", "Cliente", "Vendedor", "Pagamentos", "Total", "Situação"],
    ...r.sales_list.map((x) => [x.number, dateTime(x.completed_at ?? x.created_at), x.customer, x.seller, x.payments, x.total, x.status_label]),
    [],
    ["Movimentos da gaveta"], ["Quando", "Tipo", "Valor", "Situação", "Motivo", "Operador"],
    ...r.movements.map((m) => [dateTime(m.created_at), m.kind_label, m.amount, m.status_label, m.reason, m.operator]),
    [],
    ["Itens vendidos"], ["Produto", "SKU", "Qtd.", "Total", "Custo", "Margem"],
    ...r.items.map((i) => [i.description, i.sku, i.quantity, i.total, i.cost, i.margin]),
  ];
  const text = "﻿" + lines.map((l) => l.map((c) => `"${String(c ?? "").replace(/"/g, '""').replace(/^(-?\d+)\.(\d+)$/, "$1,$2")}"`).join(";")).join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  Object.assign(document.createElement("a"), { href: url, download: `turno-${r.session.register}.csv` }).click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div v-if="!s" class="stack"><Skeleton v-for="i in 6" :key="i" height="5rem" border-radius="10px" /></div>
  <div v-else class="statement">
    <div class="actions screen-only">
      <Button label="Exportar CSV" icon="pi pi-file-export" size="small" severity="secondary" outlined @click="csv" />
      <Button label="Imprimir" icon="pi pi-print" size="small" @click="printPage" />
    </div>

    <section class="identity">
      <div><small>Situação</small><b>{{ STATUS[s.session.status] ?? s.session.status }}</b></div>
      <div><small>Caixa / terminal</small><b>{{ s.session.register }} · {{ s.session.terminal || "—" }}</b></div>
      <div><small>Abertura</small><b>{{ dateTime(s.session.opened_at) }} · {{ s.session.opened_by || "—" }}</b></div>
      <div><small>Fechamento</small><b>{{ s.session.closed_at ? `${dateTime(s.session.closed_at)} · ${s.session.closed_by}` : "Em aberto" }}</b></div>
      <div><small>Aprovação</small><b>{{ s.session.approved_by || "—" }}</b></div>
      <div><small>Vendas</small><b>{{ s.sales.count }} · ticket médio {{ money(s.sales.average_ticket) }}</b></div>
    </section>

    <div class="kpis">
      <div><small>Vendido</small><strong>{{ money(s.sales.total) }}</strong></div>
      <div><small>Custo</small><strong>{{ money(s.sales.cost) }}</strong></div>
      <div><small>Margem bruta</small><strong class="pos">{{ money(s.sales.gross_margin) }}</strong></div>
      <div><small>Descontos</small><strong>{{ money(s.sales.discounts) }}</strong></div>
      <div><small>Cancelamentos</small><strong :class="{ neg: s.sales.cancelled_count }">{{ s.sales.cancelled_count }} · {{ money(s.sales.cancelled_total) }}</strong></div>
    </div>

    <SectionCard v-if="s.occurrences.length" title="Ocorrências" description="O que pede conferência neste turno" icon="pi pi-exclamation-triangle">
      <ul class="issues">
        <li v-for="(o, i) in s.occurrences" :key="i"><span class="pill" :class="`pill--${o.tone}`">{{ o.kind }}</span> {{ o.text }}</li>
      </ul>
    </SectionCard>

    <div class="two">
      <SectionCard title="Formas de pagamento" description="Recebido no turno" icon="pi pi-credit-card">
        <div v-for="m in s.by_payment_method" :key="m.method__name" class="line">
          <span>{{ m.method__name }} <small class="muted">· {{ m.count }} pagamento(s)</small></span><strong>{{ money(m.total) }}</strong>
        </div>
        <p v-if="!s.by_payment_method.length" class="muted">Nenhum pagamento.</p>
      </SectionCard>
      <SectionCard title="Gaveta" description="Dinheiro físico" icon="pi pi-inbox">
        <div v-for="[key, label] in DRAWER.filter(([k]) => k in (s?.drawer ?? {}))" :key="key" class="line" :class="{ total: key === 'expected', diff: key === 'difference' }">
          <span>{{ label }}</span>
          <strong :class="{ neg: key === 'difference' && n(s.drawer[key]) < 0 }">{{ s.drawer[key] == null ? "—" : money(s.drawer[key]) }}</strong>
        </div>
      </SectionCard>
    </div>

    <SectionCard title="Vendas do turno" :description="`${s.sales_list.length} vendas — clique para abrir`" icon="pi pi-shopping-cart">
      <table class="list">
        <thead><tr><th>Nº</th><th>Hora</th><th>Cliente</th><th>Vendedor</th><th>Pagamentos</th><th class="right">Total</th><th>Situação</th></tr></thead>
        <tbody>
          <tr v-for="x in s.sales_list" :key="x.id" :class="{ cancelled: x.status === 'cancelled' }" @click="router.push(`/cadastros/vendas/${x.id}`)">
            <td><strong>{{ x.number }}</strong></td><td>{{ dateTime(x.completed_at ?? x.created_at) }}</td>
            <td>{{ x.customer || "—" }}</td><td>{{ x.seller || "—" }}</td><td>{{ x.payments || "—" }}</td>
            <td class="right"><strong>{{ money(x.total) }}</strong></td><td>{{ x.status_label }}</td>
          </tr>
        </tbody>
      </table>
    </SectionCard>

    <SectionCard title="Movimentos da gaveta" description="Sangrias, suprimentos e dinheiro das vendas" icon="pi pi-arrow-right-arrow-left">
      <table class="list">
        <thead><tr><th>Quando</th><th>Tipo</th><th class="right">Valor</th><th>Situação</th><th>Motivo / destino</th><th>Operador</th></tr></thead>
        <tbody>
          <tr v-for="m in s.movements" :key="m.id">
            <td>{{ dateTime(m.created_at) }}</td><td>{{ m.kind_label }}</td><td class="right"><strong>{{ money(m.amount) }}</strong></td>
            <td><span class="pill" :class="m.status === 'approved' ? 'pill--success' : 'pill--warning'">{{ m.status_label }}</span></td>
            <td>{{ [m.reason, m.destination].filter(Boolean).join(" · ") || "—" }}</td><td>{{ m.operator }}</td>
          </tr>
        </tbody>
      </table>
    </SectionCard>

    <SectionCard title="Itens vendidos" description="Somados por produto, do que mais rendeu" icon="pi pi-box">
      <table class="list">
        <thead><tr><th>Produto</th><th class="right">Qtd.</th><th class="right">Vendas</th><th class="right">Total</th><th class="right">Custo</th><th class="right">Margem</th></tr></thead>
        <tbody>
          <tr v-for="i in s.items" :key="i.variant">
            <td><strong>{{ i.description }}</strong> <small class="muted">{{ i.sku }}</small></td>
            <td class="right">{{ quantity(i.quantity) }} {{ i.unit.toLowerCase() }}</td><td class="right">{{ i.sales }}</td>
            <td class="right"><strong>{{ money(i.total) }}</strong></td><td class="right">{{ money(i.cost) }}</td>
            <td class="right pos">{{ money(i.margin) }}</td>
          </tr>
        </tbody>
      </table>
    </SectionCard>
  </div>
</template>

<style scoped>
.stack, .statement { display: flex; flex-direction: column; gap: 1rem; }
.actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
.identity { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--border); }
.identity > div { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; background: var(--surface-card); }
.identity small { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); }
.identity b { color: var(--text-strong); font-size: 13.5px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.6rem; }
.kpis div { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); }
.kpis small { font-size: 12px; color: var(--text-muted); }
.kpis strong { font-size: 19px; color: var(--text-strong); }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1rem; }
.line { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border-subtle); font-size: 13.5px; }
.line.total { font-weight: 700; }
.issues { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 13.5px; }
.issues li { display: flex; gap: 10px; align-items: center; }
.list { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.list th { text-align: left; padding: 8px 10px; font: 650 11.5px/1.3 var(--font-sans); letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); background: var(--surface-sunken); }
.list td { padding: 9px 10px; border-top: 1px solid var(--border-subtle); }
.list tbody tr { cursor: pointer; }
.list tbody tr:hover { background: var(--surface-hover); }
.list tr.cancelled td { color: var(--text-subtle); text-decoration: line-through; }
.right { text-align: right; }
.pos { color: var(--success-text); }
.neg { color: var(--danger-text); }
@media (max-width: 720px) { .identity { grid-template-columns: 1fr 1fr; } .list { display: block; overflow-x: auto; } }
@media print { .screen-only { display: none !important; } }
</style>
