<script setup lang="ts">
/** Caixa: abrir turno, sangria/suprimento e fechamento (com contagem cega). */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import { computed, ref, watch } from "vue";

import type { CashRegister } from "@/api/types";

export type CashMode = "open" | "withdrawal" | "supply" | "close";

const props = defineProps<{ mode: CashMode; registers: CashRegister[]; busy: boolean; closable?: boolean }>();
const visible = defineModel<boolean>("visible", { required: true });
const emit = defineEmits<{ confirm: [data: { register?: string; amount: string; reason: string }] }>();

const register = ref<string | null>(null);
const amount = ref<number | null>(0);
const reason = ref("");

const titles: Record<CashMode, string> = {
  open: "Abrir caixa", withdrawal: "Sangria", supply: "Suprimento", close: "Fechar caixa",
};
const amountLabel = computed(() => ({
  open: "Troco inicial em gaveta", withdrawal: "Valor retirado", supply: "Valor colocado",
  close: "Dinheiro contado na gaveta",
})[props.mode]);

watch(visible, (open) => {
  if (!open) return;
  register.value = props.registers[0]?.id ?? null;
  amount.value = props.mode === "open" ? 0 : null;
  reason.value = "";
});

function confirm() {
  if (amount.value === null || (props.mode === "open" && !register.value)) return;
  emit("confirm", { register: register.value ?? undefined, amount: amount.value.toFixed(2), reason: reason.value });
}
</script>

<template>
  <Dialog v-model:visible="visible" modal :header="titles[mode]" :closable="closable !== false" :style="{ width: '26rem' }">
    <form class="form" @submit.prevent="confirm">
      <div v-if="mode === 'open'" class="field">
        <label>Caixa</label>
        <Select v-model="register" :options="registers" option-label="name" option-value="id" fluid />
      </div>
      <div class="field">
        <label>{{ amountLabel }}</label>
        <InputNumber v-model="amount" mode="currency" currency="BRL" locale="pt-BR" autofocus fluid />
        <small v-if="mode === 'close'" class="hint">Conte o dinheiro antes: o sistema compara com o esperado depois.</small>
      </div>
      <div v-if="mode === 'withdrawal' || mode === 'supply'" class="field">
        <label>Motivo</label>
        <InputText v-model="reason" fluid />
      </div>
      <Button type="submit" :label="titles[mode]" :loading="busy" fluid />
    </form>
  </Dialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 1rem; }
</style>
