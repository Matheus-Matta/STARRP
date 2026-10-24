<script setup lang="ts">
/**
 * Lista de separação para levar ao depósito: na ordem do caminho (endereço),
 * com uma caixinha para marcar cada item pego, as faltas e a carga para o frete.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";

import { stockApi } from "@/api/operations";
import type { ColumnDef } from "@/resources/types";
import { quantity } from "@/utils/format";

import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const query = useQuery({ queryKey: ["print-picking", props.id], queryFn: () => stockApi.picking(props.id) });
const p = computed(() => query.data.value);
const rows = computed(() => (p.value?.lines ?? []).map((l) => ({ ...l, check: "☐", bin: l.bin || "—" })));
const columns: ColumnDef[] = [
  { key: "check", label: "✔" }, { key: "bin", label: "Endereço" }, { key: "description", label: "Produto" },
  { key: "sku", label: "SKU" }, { key: "lot", label: "Lote" }, { key: "quantity", label: "Qtd.", type: "quantity" },
];
const boxColumns: ColumnDef[] = [
  { key: "description", label: "Produto" }, { key: "label", label: "Caixa" }, { key: "contents", label: "Conteúdo" },
  { key: "barcode", label: "Código" }, { key: "quantity", label: "Qtd." },
];
</script>

<template>
  <PrintShell v-model:format="format" :title="`Lista de separação nº ${p?.document ?? ''}`" :formats="['a4', '80mm']" :ready="!!p"
              :filename="`separacao-${p?.document ?? id}`" :subtitle="p?.warehouse">
    <template v-if="p" #default="{ thermal }">
      <section class="doc-section">
        <h2>Pegar (na ordem do caminho)</h2>
        <PrintTable :columns="columns" :rows="rows" :thermal="thermal" />
      </section>
      <section v-if="p.shortages.length" class="doc-section">
        <h2>Faltas</h2>
        <ul class="short"><li v-for="s in p.shortages" :key="s.variant">{{ s.description }}: faltam {{ quantity(s.missing_quantity) }}</li></ul>
      </section>
      <section class="doc-section">
        <h2>Carga</h2>
        <p class="doc-note">{{ p.load.box_count }} caixas · {{ quantity(p.load.gross_weight) }} kg · {{ Number(p.load.cubic_meters).toLocaleString("pt-BR") }} m³</p>
        <PrintTable v-if="p.load.boxes.some((b) => b.label)" :columns="boxColumns" :rows="p.load.boxes" :thermal="thermal" />
      </section>
      <div class="doc-signatures"><div>Separado por</div><div>Conferido por</div></div>
    </template>
  </PrintShell>
</template>

<style scoped>
.short { margin: 0; padding-left: 16px; color: #b91c1c; font-size: 9pt; }
</style>
