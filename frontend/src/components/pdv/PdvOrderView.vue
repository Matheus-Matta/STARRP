<script setup lang="ts">
/**
 * Um pedido aberto DENTRO do PDV (clique na lista de Pedidos): a mesma página de
 * leitura da retaguarda (`RecordView` com o `display` de vendas) e, no topo, o que
 * dá para fazer com ele daqui — retomar o guardado, imprimir o concluído.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import { computed, ref } from "vue";

import { http } from "@/api/http";
import { resourceApi } from "@/api/resource";
import RecordView from "@/components/resource/RecordView.vue";
import { useNotify } from "@/composables/useNotify";
import { useSession } from "@/stores/session";
import { FULFILLMENT_FLOW, fulfillmentStatus, overallStatus, sales } from "@/resources/sales";
import { dateTime } from "@/utils/format";

const props = defineProps<{ id: string; busy: boolean; seller: boolean }>();
const emit = defineEmits<{ back: []; resume: [id: string]; print: [id: string] }>();

const query = useQuery({
  queryKey: computed(() => ["pdv-order", props.id]),
  queryFn: () => resourceApi.get<Record<string, unknown>>("/sales/", props.id),
});
const sale = computed(() => query.data.value ?? null);
const status = computed(() => String(sale.value?.status ?? ""));
const ctx = computed(() => ({ id: props.id, values: sale.value ?? {}, reload: async () => void (await query.refetch()) }));

/* Entrega: anda para a próxima etapa (ou pula), ou volta uma com motivo. */
const notify = useNotify();
const step = computed(() => FULFILLMENT_FLOW.indexOf(String(sale.value?.fulfillment_status)));
const canMove = useSession().can("logistics.manage");
const delivers = computed(() => status.value === "completed" && Boolean(sale.value?.shipping_address) && step.value >= 0);
const NEXT = [
  { to: "ready", label: "Separado", icon: "pi pi-box" },
  { to: "shipped", label: "Saiu para entrega", icon: "pi pi-truck" },
  { to: "delivered", label: "Entregue", icon: "pi pi-home" },
];
const nextSteps = computed(() => NEXT.filter((n) => FULFILLMENT_FLOW.indexOf(n.to) > step.value));
const moving = ref(false);
const backing = ref(false);
const reason = ref("");
async function move(to: string, note = "") {
  moving.value = true;
  try {
    await http.post(`/sales/${props.id}/fulfillment/`, { status: to, note });
    await query.refetch();
    backing.value = false;
    reason.value = "";
    notify.success(`Entrega: ${fulfillmentStatus.map[to]}`, to === "delivered" ? "Pedido concluído." : undefined);
  } catch (error) {
    notify.error(error, "Entrega não atualizada");
  } finally {
    moving.value = false;
  }
}
</script>

<template>
  <section class="panel">
    <header class="panel__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para os pedidos" @click="emit('back')" />
      <div class="panel__title">
        <h2>Pedido {{ sale?.number ?? "…" }}</h2>
        <p v-if="sale">
          {{ overallStatus.map[String(sale.overall_status)] ?? status }} · aberto em {{ dateTime(String(sale.created_at)) }}
          <template v-if="sale.parked_at"> · guardado em {{ dateTime(String(sale.parked_at)) }}</template>
        </p>
      </div>
      <div class="panel__actions">
        <Button v-if="status === 'draft'" :label="seller ? 'Continuar editando' : 'Retomar e cobrar'" icon="pi pi-play"
                :loading="busy" @click="emit('resume', id)" />
        <Button v-if="status === 'completed'" label="Imprimir" icon="pi pi-print" severity="secondary" outlined
                @click="emit('print', id)" />
      </div>
    </header>
    <div v-if="delivers" class="flow" role="group" aria-label="Entrega">
      <span class="flow__now"><i class="pi pi-truck" /> Entrega: <b>{{ fulfillmentStatus.map[String(sale?.fulfillment_status)] }}</b></span>
      <Button v-for="n in canMove ? nextSteps : []" :key="n.to" :label="n.label" :icon="n.icon" size="small" :loading="moving"
              :severity="n.to === 'delivered' ? 'success' : 'secondary'" :outlined="n.to !== 'delivered'" @click="move(n.to)" />
      <Button v-if="canMove && step > 0 && !backing" label="Voltar etapa" icon="pi pi-undo" size="small" text severity="secondary"
              @click="backing = true" />
      <form v-if="backing" class="flow__back" @submit.prevent="reason.trim() && move(FULFILLMENT_FLOW[step - 1]!, reason)">
        <InputText v-model="reason" size="small" placeholder="Motivo (ex.: cliente não estava)" autofocus />
        <Button type="submit" label="Voltar" size="small" :disabled="!reason.trim()" :loading="moving" />
        <Button label="Cancelar" size="small" text severity="secondary" @click="backing = false" />
      </form>
    </div>
    <div v-if="query.isPending.value" class="loading"><i class="pi pi-spin pi-spinner" /> Carregando o pedido…</div>
    <p v-else-if="query.isError.value" class="loading">Não foi possível abrir o pedido.</p>
    <RecordView v-else-if="sale" :resource="sales" :ctx="ctx" />
  </section>
</template>

<style scoped>
.panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; padding: 12px; overflow-y: auto; }
.panel__head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.panel__title { flex: 1; min-width: 0; }
.panel__title h2 { margin: 0; font: 700 17px/1.2 var(--font-sans); color: var(--text-strong); }
.panel__title p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.panel__actions { display: flex; gap: 8px; }
.flow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 10px;
        border: 1px solid var(--border); background: var(--surface-card); }
.flow__now { margin-right: auto; font-size: 13px; color: var(--text-muted); display: flex; gap: 6px; align-items: center; }
.flow__now b { color: var(--text-strong); }
.flow__back { display: flex; gap: 6px; align-items: center; width: 100%; }
.flow__back :deep(input) { flex: 1; }
.loading { padding: 40px; text-align: center; color: var(--text-muted); display: flex; gap: 8px; justify-content: center; }
</style>
