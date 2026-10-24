<script setup lang="ts">
/** Documento de estoque (entrada, saída, transferência, inventário...): itens, custos e assinaturas. */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";

import { resourceApi } from "@/api/resource";
import { documentKind, documentStatus, exitReason } from "@/resources/stock";
import type { ColumnDef } from "@/resources/types";
import { date, dateTime } from "@/utils/format";

import PrintMeta from "../PrintMeta.vue";
import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

type Doc = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const query = useQuery({ queryKey: ["print-stockdoc", props.id], queryFn: () => resourceApi.get<Doc>("/stock/documents/", props.id) });
const doc = computed(() => query.data.value);
const entry = computed(() => doc.value?.kind === "entry");
const inventory = computed(() => doc.value?.kind === "inventory");
const rows = computed(() => (doc.value?.items ?? []).map((i: Doc) => ({
  ...i, total: (Number(i.quantity) * Number(i.unit_cost ?? 0)).toFixed(2),
  lot: [i.lot_number, i.expires_at ? `val. ${date(i.expires_at)}` : ""].filter(Boolean).join(" · "),
  difference: i.expected_quantity == null ? null : (Number(i.quantity) - Number(i.expected_quantity)).toFixed(3),
})));
const columns = computed<ColumnDef[]>(() => [
  { key: "variant_name", label: "Produto" }, { key: "sku", label: "SKU" },
  ...(inventory.value ? [{ key: "expected_quantity", label: "Sistema", type: "quantity" as const }] : []),
  { key: "quantity", label: inventory.value ? "Contado" : "Qtd.", type: "quantity" },
  ...(inventory.value ? [{ key: "difference", label: "Diferença", type: "quantity" as const }] : []),
  ...(entry.value ? [{ key: "unit_cost", label: "Custo unit.", type: "money" as const }, { key: "total", label: "Total", type: "money" as const },
                     { key: "lot", label: "Lote / validade" }] : []),
]);
const totals = computed(() => ({
  variant_name: `${rows.value.length} itens`,
  quantity: rows.value.reduce((t: number, r: Doc) => t + Number(r.quantity), 0).toFixed(3),
  ...(entry.value ? { total: rows.value.reduce((t: number, r: Doc) => t + Number(r.total), 0).toFixed(2) } : {}),
}));
</script>

<template>
  <PrintShell v-model:format="format" :title="`${documentKind.map[doc?.kind] ?? 'Documento'} nº ${doc?.number ?? ''}`" :formats="['a4']"
              :ready="!!doc" :store-id="doc?.store" :filename="`estoque-${(documentKind.map[doc?.kind] ?? '').toLowerCase()}-${doc?.number ?? id}`"
              :subtitle="doc ? `${documentStatus.map[doc.status]} · ${date(doc.effective_date)}` : ''">
    <template v-if="doc">
      <PrintMeta :columns="3" :items="[
        ['Depósito', doc.warehouse_name],
        doc.kind === 'transfer' ? ['Destino', doc.destination_name] : ['Fornecedor', doc.supplier_name],
        ['Nota / documento', doc.external_number],
        ['Data', date(doc.effective_date)],
        ['Confirmado em', doc.posted_at ? dateTime(doc.posted_at) : 'Rascunho'],
        doc.kind === 'exit' ? ['Motivo da saída', exitReason.map[doc.exit_reason]] : ['Situação', documentStatus.map[doc.status]],
      ]" />
      <p v-if="doc.reason" class="doc-note"><b>Observação:</b> {{ doc.reason }}</p>
      <section class="doc-section">
        <h2>Itens</h2>
        <PrintTable :columns="columns" :rows="rows" :totals="totals" />
      </section>
      <div class="doc-signatures">
        <div>{{ entry ? "Recebido por" : "Separado por" }}</div>
        <div>Conferido por</div>
        <div>Responsável</div>
      </div>
    </template>
  </PrintShell>
</template>
