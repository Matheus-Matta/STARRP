<script setup lang="ts">
/** Demonstrativo do título (conta a pagar/receber): dados, parcelas, pagos e em aberto. */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";

import { resourceApi } from "@/api/resource";
import { titleKind, titleStatus } from "@/resources/finance";
import type { ColumnDef } from "@/resources/types";
import { date, money } from "@/utils/format";

import PrintMeta from "../PrintMeta.vue";
import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

type Title = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const query = useQuery({ queryKey: ["print-title", props.id], queryFn: () => resourceApi.get<Title>("/finance/titles/", props.id) });
const t = computed(() => query.data.value);
const rows = computed(() => (t.value?.installments ?? []).map((i: Title) => ({
  ...i, balance: (Number(i.amount) - Number(i.paid_amount)).toFixed(2),
})));
const sum = (key: string) => rows.value.reduce((s: number, r: Title) => s + Number(r[key] ?? 0), 0).toFixed(2);
const columns: ColumnDef[] = [
  { key: "number", label: "Parcela" }, { key: "due_date", label: "Vencimento", type: "date" },
  { key: "amount", label: "Valor", type: "money" }, { key: "paid_amount", label: "Pago", type: "money" },
  { key: "paid_at", label: "Pago em", type: "date" }, { key: "balance", label: "Saldo", type: "money" },
  { key: "status", label: "Situação", type: "tag", map: titleStatus.map },
];
</script>

<template>
  <PrintShell v-model:format="format" :title="`Conta ${titleKind.map[t?.kind]?.toLowerCase() ?? ''}`" :formats="['a4']" :ready="!!t"
              :store-id="t?.store" :filename="`${t?.kind === 'receivable' ? 'receber' : 'pagar'}-${(t?.document_number || t?.description || id).toString().toLowerCase().replace(/[^a-z0-9à-ú]+/gi, '-')}`" :subtitle="t?.description">
    <template v-if="t">
      <PrintMeta :columns="3" :items="[
        [t.kind === 'receivable' ? 'Cliente' : 'Fornecedor', t.customer_name ?? t.supplier_name],
        ['Documento', t.document_number], ['Categoria', t.category_name],
        ['Emissão', date(t.issue_date)], ['Valor total', money(t.total)], ['Situação', titleStatus.map[t.status]],
      ]" />
      <p v-if="t.notes" class="doc-note"><b>Observações:</b> {{ t.notes }}</p>
      <section class="doc-section">
        <h2>Parcelas</h2>
        <PrintTable :columns="columns" :rows="rows" :totals="{ number: 'Total', amount: sum('amount'), paid_amount: sum('paid_amount'), balance: sum('balance') }" />
      </section>
      <div class="doc-signatures"><div>Responsável</div><div>{{ t.kind === "receivable" ? "Cliente" : "Fornecedor" }}</div></div>
    </template>
  </PrintShell>
</template>
