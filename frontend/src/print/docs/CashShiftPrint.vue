<script setup lang="ts">
/**
 * Fechamento do turno de caixa.
 * A4: o extrato completo (identificação, resumo, pagamentos, gaveta, ocorrências,
 * vendas, movimentos, itens e assinaturas). Bobina 80 mm: o "Z" do turno para grampear.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";

import { financeApi } from "@/api/operations";
import type { ColumnDef } from "@/resources/types";
import { dateTime, money } from "@/utils/format";

import PrintMeta from "../PrintMeta.vue";
import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const query = useQuery({ queryKey: ["print-cash", props.id], queryFn: () => financeApi.cashStatement(props.id) });
const s = computed(() => query.data.value);
const STATUS: Record<string, string> = { open: "Aberto", pending_approval: "Aguardando gerente", closed: "Fechado", cancelled: "Cancelado" };

const DRAWER: [string, string][] = [
  ["opening", "Troco inicial"], ["sale", "Vendas em dinheiro"], ["supply", "Suprimentos"], ["withdrawal", "Sangrias"],
  ["refund", "Devoluções"], ["expected", "Esperado"], ["counted", "Contado"], ["difference", "Diferença"],
];
// Fechamento cego: para o operador a gaveta vem só com troco inicial e contado.
const drawerRows = computed(() => DRAWER.filter(([key]) => s.value && key in s.value.drawer)
  .map(([key, label]) => ({ label, value: s.value?.drawer[key] ?? null })));
const payColumns: ColumnDef[] = [
  { key: "method__name", label: "Forma" }, { key: "count", label: "Qtd." }, { key: "total", label: "Total", type: "money" },
];
const saleColumns: ColumnDef[] = [
  { key: "number", label: "Nº" }, { key: "completed_at", label: "Hora", type: "datetime" }, { key: "customer", label: "Cliente" },
  { key: "seller", label: "Vendedor" }, { key: "payments", label: "Pagamentos" }, { key: "discount", label: "Desc.", type: "money" },
  { key: "total", label: "Total", type: "money" }, { key: "status_label", label: "Situação" },
];
const movementColumns: ColumnDef[] = [
  { key: "created_at", label: "Quando", type: "datetime" }, { key: "kind_label", label: "Tipo" },
  { key: "amount", label: "Valor", type: "money" }, { key: "status_label", label: "Situação" },
  { key: "reason", label: "Motivo" }, { key: "operator", label: "Operador" },
];
const itemColumns: ColumnDef[] = [
  { key: "description", label: "Produto" }, { key: "sku", label: "SKU" }, { key: "quantity", label: "Qtd.", type: "quantity" },
  { key: "total", label: "Total", type: "money" }, { key: "cost", label: "Custo", type: "money" }, { key: "margin", label: "Margem", type: "money" },
];
const sum = (rows: Record<string, unknown>[], key: string) => rows.reduce((t, r) => t + Number(r[key] ?? 0), 0).toFixed(2);
const filename = computed(() => `fechamento-${s.value?.session.register ?? "caixa"}-${(s.value?.session.opened_at ?? "").slice(0, 10)}`);
</script>

<template>
  <PrintShell v-model:format="format" title="Fechamento de caixa" :formats="['a4', '80mm']" :ready="!!s" :filename="filename"
              :subtitle="s ? `${s.session.register} · ${dateTime(s.session.opened_at)}` : ''">
    <template v-if="s" #default="{ thermal }">
      <PrintMeta :columns="3" :items="[
        ['Caixa / terminal', `${s.session.register} · ${s.session.terminal || '—'}`],
        ['Situação', STATUS[s.session.status] ?? s.session.status],
        ['Aprovado por', s.session.approved_by],
        ['Abertura', `${dateTime(s.session.opened_at)} · ${s.session.opened_by}`],
        ['Fechamento', s.session.closed_at ? `${dateTime(s.session.closed_at)} · ${s.session.closed_by}` : 'Em aberto'],
        ['Vendas', `${s.sales.count} · ticket ${money(s.sales.average_ticket)}`],
      ]" />

      <div class="doc-kpis">
        <div><small>Vendido</small><b>{{ money(s.sales.total) }}</b></div>
        <div><small>Custo</small><b>{{ money(s.sales.cost) }}</b></div>
        <div><small>Margem bruta</small><b>{{ money(s.sales.gross_margin) }}</b></div>
        <div><small>Cancelado</small><b>{{ s.sales.cancelled_count }} · {{ money(s.sales.cancelled_total) }}</b></div>
      </div>

      <div class="cols" :class="{ 'cols--one': thermal }">
        <section class="doc-section">
          <h2>Formas de pagamento</h2>
          <PrintTable :columns="payColumns" :rows="s.by_payment_method" :thermal="thermal"
                      :totals="{ method__name: 'Total', total: sum(s.by_payment_method, 'total') }" empty="Nenhum pagamento." />
        </section>
        <section class="doc-section">
          <h2>Gaveta (dinheiro)</h2>
          <table class="pt drawer">
            <tbody>
              <tr v-for="row in drawerRows" :key="row.label" :class="{ strong: ['Esperado', 'Diferença'].includes(row.label) }">
                <td>{{ row.label }}</td>
                <td class="r" :class="{ neg: row.label === 'Diferença' && Number(row.value) < 0 }">{{ row.value == null ? "—" : money(row.value) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section v-if="s.occurrences.length" class="doc-section">
        <h2>Ocorrências</h2>
        <ul class="issues"><li v-for="(o, i) in s.occurrences" :key="i"><b>{{ o.kind }}:</b> {{ o.text }}</li></ul>
      </section>

      <template v-if="!thermal">
        <section class="doc-section">
          <h2>Vendas do turno ({{ s.sales_list.length }})</h2>
          <PrintTable :columns="saleColumns" :rows="s.sales_list" />
        </section>
        <section class="doc-section">
          <h2>Movimentos da gaveta</h2>
          <PrintTable :columns="movementColumns" :rows="s.movements" empty="Nenhum movimento." />
        </section>
        <section class="doc-section">
          <h2>Itens vendidos</h2>
          <PrintTable :columns="itemColumns" :rows="s.items"
                      :totals="{ description: 'Total', total: sum(s.items, 'total'), cost: sum(s.items, 'cost'), margin: sum(s.items, 'margin') }" />
        </section>
      </template>

      <div class="doc-signatures">
        <div>Operador do caixa</div>
        <div>Gerente / conferente</div>
      </div>
    </template>
  </PrintShell>
</template>

<style scoped>
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cols--one { grid-template-columns: 1fr; }
.drawer tr.strong td { font-weight: 700; background: #f3f4f6; }
.issues { margin: 0; padding-left: 16px; font-size: 8.5pt; }
</style>
