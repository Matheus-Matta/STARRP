<script setup lang="ts">
/**
 * Pedidos da loja DENTRO do PDV (a mesma lista das telas): só os desta loja — a API
 * recorta pela loja ativa, então vendedor e caixa nunca veem pedido de outra loja.
 *
 * Clicar num pedido abre a página dele aqui mesmo (`PdvOrderView`): itens, serviços,
 * pagamentos e valores; de lá, retomar o guardado ou imprimir o concluído.
 */
import Button from "primevue/button";
import SelectButton from "primevue/selectbutton";
import { computed, ref } from "vue";

import type { Row } from "@/api/resource";
import PdvOrderView from "@/components/pdv/PdvOrderView.vue";
import EmbeddedList from "@/components/resource/EmbeddedList.vue";
import { saleColumns } from "@/resources/sales";
import type { ListViewDef } from "@/resources/types";

const props = defineProps<{ seller: boolean; busy: boolean }>();
const emit = defineEmits<{ resume: [id: string]; receipt: [id: string]; back: [] }>();
/** Pedido aberto na página de leitura (null = a lista). */
const opened = ref<string | null>(null);

type Filter = "draft" | "open" | "deliveries" | "completed" | "cancelled";
const filter = ref<Filter>("draft");
const OPTIONS = [
  { label: "Guardados", value: "draft" }, { label: "Em aberto", value: "open" },
  { label: "Entregas", value: "deliveries" },
  { label: "Concluídos hoje", value: "completed" }, { label: "Cancelados hoje", value: "cancelled" },
];
/** Filtro → parâmetros: "Entregas" são as pagas que ainda não chegaram no cliente (qualquer dia). */
const PARAMS: Record<Filter, Record<string, string>> = {
  draft: { status: "draft" },
  open: { status: "open" },
  deliveries: { status: "completed", fulfillment_status__in: "pending,ready,shipped" },
  completed: { overall_status: "completed" },
  cancelled: { status: "cancelled" },
};
const today = () => new Date().toLocaleDateString("sv-SE");

const view = computed<ListViewDef>(() => ({
  endpoint: "/sales/",
  params: () => ({
    ...PARAMS[filter.value],
    ...(filter.value === "completed" || filter.value === "cancelled" ? { created_at__gte: `${today()}T00:00:00` } : {}),
  }),
  ordering: filter.value === "deliveries" ? "completed_at" : filter.value === "completed" ? "-completed_at" : "-created_at",
  columns: [
    { key: "number", label: "Nº", title: true },
    { key: "created_at", label: filter.value === "draft" ? "Guardado" : "Aberto em", type: "datetime" },
    { key: "customer_name", label: "Cliente" },
    { key: "seller_name", label: "Vendedor" },
    { key: "item_count", label: "Itens", sortable: false },
    { key: "total", label: "Total", type: "money" },
    ...saleColumns.filter((c) => ["overall_status", "payment_status", "fulfillment_status"].includes(c.key)),
  ],
}));

const hint = computed(() => ({
  draft: props.seller ? "Pedidos guardados da filial. Abra um para ver e continuar editando." : "Abra um pedido para conferir, retomar e cobrar.",
  open: "Vendas em andamento agora nos caixas da filial.",
  deliveries: "Pagas e ainda não entregues (as mais antigas primeiro). Abra para separar, despachar e dar baixa.",
  completed: "Abra uma venda para conferir ou reimprimir.",
  cancelled: "Vendas canceladas hoje nesta filial.",
})[filter.value]);

function pick(row: Row) {
  opened.value = String(row.id);
}
</script>

<template>
  <PdvOrderView v-if="opened" :id="opened" :busy="busy" :seller="seller" @back="opened = null"
                @resume="(id) => emit('resume', id)" @print="(id) => emit('receipt', id)" />
  <section v-else class="panel">
    <header class="panel__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para a venda" @click="emit('back')" />
      <div>
        <h2>Pedidos da filial</h2>
        <p>{{ hint }}</p>
      </div>
    </header>
    <SelectButton v-model="filter" :options="OPTIONS" option-label="label" option-value="value" :allow-empty="false" class="filter" />
    <EmbeddedList :key="filter" :view="view" id="" :values="{}" title="Pedidos" :pick="true"
                  compact placeholder="Buscar por número ou cliente…" @pick="pick" />
  </section>
</template>

<style scoped>
.panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 12px; overflow-y: auto; }
.panel__head { display: flex; align-items: center; gap: 10px; }
.panel__head h2 { margin: 0; font: 700 17px/1.2 var(--font-sans); color: var(--text-strong); }
.panel__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.filter { align-self: flex-start; }
</style>
