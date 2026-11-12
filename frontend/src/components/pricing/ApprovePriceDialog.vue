<script setup lang="ts">
/** Aprovar com outro preço: começa no sugerido e mostra a margem que fica com o custo. */
import Button from "primevue/button";
import { computed, ref } from "vue";

import { pricingApi } from "@/api/pricing";
import FormField from "@/components/resource/FormField.vue";
import { useNotify } from "@/composables/useNotify";
import type { FieldDef, FormActionContext } from "@/resources/types";
import { money } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const values = ref<Record<string, unknown>>({ price: props.ctx.values.suggested_price ?? "" });
const field: FieldDef = { name: "price", label: "Novo preço de venda", type: "money", required: true, span: 6 };
const saving = ref(false);

const cost = computed(() => Number(props.ctx.values.cost ?? 0));
const floor = computed(() => Number(props.ctx.values.floor_price ?? 0));
const price = computed(() => Number(values.value.price ?? 0));
const margin = computed(() => (price.value > 0 && cost.value > 0 ? ((price.value - cost.value) / price.value) * 100 : null));

async function approve() {
  saving.value = true;
  try {
    await pricingApi.approve(props.ctx.id, String(values.value.price));
    notify.success("Preço aplicado", "O cadastro do produto já está com o novo preço.");
    emit("done");
  } catch (error) {
    notify.error(error, "Preço não aplicado");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="approve">
    <FormField v-model="values.price" :field="field" :context="values" />
    <dl class="facts">
      <div><dt>Preço atual</dt><dd>{{ money(ctx.values.current_price) }}</dd></div>
      <div><dt>Mediana do mercado</dt><dd>{{ money(ctx.values.market_median) }}</dd></div>
      <div v-if="cost"><dt>Custo</dt><dd>{{ money(cost) }}</dd></div>
      <div v-if="margin !== null">
        <dt>Margem com este preço</dt>
        <dd :class="{ low: floor && price < floor }">{{ margin.toLocaleString("pt-BR", { maximumFractionDigits: 1 }) }}%</dd>
      </div>
    </dl>
    <p v-if="floor && price < floor" class="warn">
      <i class="pi pi-exclamation-triangle" /> Abaixo de {{ money(floor) }} a margem fica menor que a mínima da conta.
    </p>
    <div class="foot">
      <Button label="Voltar" severity="secondary" text @click="emit('close')" />
      <Button label="Aplicar preço" icon="pi pi-check" severity="success" :loading="saving" :disabled="!(price > 0)"
              @click="approve" />
    </div>
  </div>
</template>

<style scoped>
.approve { display: flex; flex-direction: column; gap: 12px; min-width: min(360px, 80vw); }
.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; margin: 0; }
.facts div { display: grid; gap: 2px; }
.facts dt { font-size: 12px; color: var(--text-muted); }
.facts dd { margin: 0; font-weight: 700; color: var(--text-strong); }
.facts dd.low { color: var(--danger-text); }
.warn { margin: 0; font-size: 12.5px; color: var(--warning-text); }
.foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
