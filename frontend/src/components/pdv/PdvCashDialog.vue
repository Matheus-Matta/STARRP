<script setup lang="ts">
/** Caixa: abrir turno, sangria/suprimento e fechamento (com contagem cega). */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import { computed, ref, watch } from "vue";

import type { CashRegister } from "@/api/types";

export type CashMode = "open" | "withdrawal" | "supply" | "close";

/** `myRegister`: o caixa do usuário (um por usuário). A abertura NÃO pergunta o caixa: mostra o dele
 *  ou, sem caixa próprio (gerente assumindo), o 1º livre; nenhum livre = aviso, sem abrir. */
/** `backoffice`: quem tem acesso à retaguarda ganha o botão de voltar para ela. */
const props = withDefaults(defineProps<{ mode: CashMode; registers: CashRegister[]; busy: boolean; closable?: boolean;
                                         myRegister?: string | null; backoffice?: boolean }>(), { closable: true });
const visible = defineModel<boolean>("visible", { required: true });
const emit = defineEmits<{ confirm: [data: { register?: string; amount: string; reason: string }]; backoffice: [] }>();

const amount = ref<number | null>(0);
const reason = ref("");

/** Caixa com turno de outro operador (o backend manda `in_use_by`). */
const inUse = (r: CashRegister) => (r as CashRegister & { in_use_by?: string | null }).in_use_by ?? null;
const mine = computed(() => props.registers.find((r) => r.id === props.myRegister) ?? null);
const chosen = computed(() => mine.value ?? props.registers.find((r) => !inUse(r)) ?? null);

const titles: Record<CashMode, string> = {
  open: "Abrir caixa", withdrawal: "Sangria", supply: "Suprimento", close: "Fechar caixa",
};
const amountLabel = computed(() => ({
  open: "Dinheiro contado na gaveta", withdrawal: "Valor retirado", supply: "Valor colocado",
  close: "Dinheiro contado na gaveta",
})[props.mode]);

watch(visible, (open) => {
  if (!open) return;
  amount.value = props.mode === "open" ? 0 : null;
  reason.value = "";
});

function confirm() {
  if (amount.value === null || (props.mode === "open" && !chosen.value)) return;
  emit("confirm", { register: props.mode === "open" ? chosen.value?.id : undefined, amount: amount.value.toFixed(2),
                    reason: reason.value });
}
</script>

<template>
  <Dialog v-model:visible="visible" modal :header="titles[mode]" :closable="closable" :style="{ width: '26rem' }">
    <form class="form" @submit.prevent="confirm">
      <div v-if="mode === 'open' && chosen" class="mine">
        <i class="pi pi-wallet" /><strong>{{ chosen.name }}</strong><small>{{ mine ? "o seu caixa" : "caixa livre da filial" }}</small>
      </div>
      <p v-else-if="mode === 'open'" class="none">
        <i class="pi pi-exclamation-circle" /> Nenhum caixa livre: {{ registers.length ? "todos estão com turno aberto." :
          "você não está vinculado a um caixa. Peça ao gerente em Financeiro › Caixas." }}</p>
      <div class="field">
        <label>{{ amountLabel }}</label>
        <InputNumber v-model="amount" mode="currency" currency="BRL" locale="pt-BR" autofocus fluid />
        <small v-if="mode === 'close'" class="hint">Conte o dinheiro antes: o sistema compara com o esperado depois.</small>
        <small v-else-if="mode === 'open'" class="hint">Conte o que está na gaveta e digite. O sistema confere com o que o
          último fechamento deixou; se não bater, o gerente confere antes de vender.</small>
      </div>
      <div v-if="mode === 'withdrawal' || mode === 'supply' || mode === 'open'" class="field">
        <label>{{ mode === "open" ? "Observação (opcional)" : "Motivo" }}</label>
        <InputText v-model="reason" fluid />
      </div>
      <Button type="submit" :label="titles[mode]" :loading="busy" :disabled="mode === 'open' && !chosen" fluid />
      <div v-if="closable || backoffice" class="exits">
        <Button v-if="closable" label="Fechar" icon="pi pi-times" severity="secondary" text size="small"
                @click="visible = false" />
        <Button v-if="backoffice" label="Voltar à retaguarda" icon="pi pi-arrow-left" severity="secondary" text
                size="small" @click="visible = false; emit('backoffice')" />
      </div>
    </form>
  </Dialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 1rem; }
.exits { display: flex; justify-content: space-between; gap: 8px; margin-top: -0.5rem; }
.mine { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 10px; background: var(--brand-subtle);
        border: 1px solid var(--brand-border); font-size: 14px; color: var(--text-strong); }
.mine i { color: var(--text-brand); }
.mine small { margin-left: auto; font-size: 12px; color: var(--text-muted); }
.none { margin: 0; display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border-radius: 10px; font-size: 13px;
        background: var(--warning-subtle); color: var(--text-strong); }
.none i { color: var(--warning-text); margin-top: 2px; }
</style>
