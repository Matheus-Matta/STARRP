<script setup lang="ts">
/** Concessão avulsa de saldo, independente de venda ou devolução. */
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import Textarea from "primevue/textarea";
import { computed, ref } from "vue";

import { http } from "@/api/http";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { money } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const amount = ref<number | null>(null);
const reason = ref("");
const saving = ref(false);
const ready = computed(() => Number(amount.value) > 0 && reason.value.trim().length >= 3);

async function save() {
  saving.value = true;
  try {
    await http.post(`/customers/${props.ctx.id}/grant-credit/`, {
      amount: Number(amount.value).toFixed(2),
      reason: reason.value.trim(),
    });
    notify.success("Crédito concedido", `${money(amount.value)} entrou na carteira do cliente.`);
    emit("done");
  } catch (error) {
    notify.error(error, "Crédito não concedido");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="ccd">
    <div class="balance">
      <span>Saldo atual</span>
      <strong>{{ money(ctx.values.credit_balance) }}</strong>
    </div>
    <p class="muted">Este crédito não depende de pedido ou devolução e poderá ser usado no checkout.</p>
    <div class="field">
      <label for="ccd-amount">Valor <b>*</b></label>
      <InputNumber v-model="amount" input-id="ccd-amount" mode="currency" currency="BRL" locale="pt-BR"
                   :min="0.01" :min-fraction-digits="2" :max-fraction-digits="2" fluid autofocus />
    </div>
    <div class="field">
      <label for="ccd-reason">Motivo <b>*</b></label>
      <Textarea id="ccd-reason" v-model="reason" rows="3" maxlength="255" auto-resize fluid
                placeholder="Ex.: bonificação comercial ou fidelização" />
      <small>O motivo ficará registrado no extrato da carteira.</small>
    </div>
    <div class="ccd__foot">
      <Button label="Cancelar" severity="secondary" text :disabled="saving" @click="emit('close')" />
      <Button label="Conceder crédito" icon="pi pi-check" severity="success" :loading="saving"
              :disabled="!ready || saving" @click="save" />
    </div>
  </div>
</template>

<style scoped>
.ccd { display: flex; min-width: min(520px, 100%); flex-direction: column; gap: 12px; }
.ccd p { margin: 0; font-size: 13px; }
.balance { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-radius: 10px;
  background: var(--brand-subtle); color: var(--text-brand); }
.balance span { font-size: 13px; font-weight: 600; }
.balance strong { font-size: 20px; font-variant-numeric: tabular-nums; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { color: var(--text-muted); font-size: 12.5px; font-weight: 600; }
.field label b { color: var(--danger-text); }
.field label small, .field > small { color: var(--text-muted); font-size: 11.5px; font-weight: 400; }
.ccd__foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
