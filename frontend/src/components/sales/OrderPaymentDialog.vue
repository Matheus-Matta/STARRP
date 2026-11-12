<script setup lang="ts">
/**
 * "Trocar pagamento" no pedido concluído (permissão `sales.edit_payment`): troca a FORMA de um
 * pagamento com o mesmo valor ("lançou PIX, foi cartão"). O antigo fica cancelado e o que ele
 * gerou é estornado (conta, título a receber, gaveta); o novo gera o que a forma nova gera.
 * Dinheiro de turno já fechado não se troca aqui (acerte com sangria/suprimento).
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import { computed, ref, watch } from "vue";

import { http } from "@/api/http";
import { resourceApi } from "@/api/resource";
import type { PaymentMethod } from "@/api/types";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { money } from "@/utils/format";

type Pay = { id: string; method: string; method_name: string; amount: string; installments: number; nsu: string; status: string };

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const v = props.ctx.values;
const payments = computed(() => ((v.payments ?? []) as Pay[]).filter((p) => p.status === "approved"));
const hasInvoice = computed(() => ((v.invoices ?? []) as { status: string }[]).some((i) => i.status === "authorized"));

const methodsQuery = useQuery({
  queryKey: ["order-payment-methods"],
  queryFn: () => resourceApi.list<PaymentMethod>("/payment-methods/", { is_active: true, page_size: 100, ordering: "position" }),
});
const NEEDS_CUSTOMER = new Set(["installment_plan", "store_credit"]);
const methods = computed(() => (methodsQuery.data.value?.results ?? [])
  .filter((m) => !(NEEDS_CUSTOMER.has(m.kind) && !v.customer)));

const paymentId = ref<string | null>(payments.value.length === 1 ? payments.value[0]!.id : null);
const payment = computed(() => payments.value.find((p) => p.id === paymentId.value) ?? null);
const methodId = ref<string | null>(null);
const method = computed(() => methods.value.find((m) => m.id === methodId.value) ?? null);
const installments = ref(1);
const nsu = ref("");
const reason = ref("");
const saving = ref(false);
watch(methodId, () => (installments.value = 1));

const ready = computed(() => payment.value && method.value && method.value.id !== payment.value.method && reason.value.trim());

async function save() {
  saving.value = true;
  try {
    await http.post(`/sales/${props.ctx.id}/payments/${payment.value!.id}/change/`, {
      method: method.value!.id, installments: installments.value, nsu: nsu.value, reason: reason.value });
    notify.success("Forma de pagamento trocada", `${payment.value!.method_name} → ${method.value!.name}`);
    emit("done");
  } catch (error) {
    notify.error(error, "Pagamento não trocado");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="opd">
    <p class="muted">O valor fica o mesmo; muda só a forma. O lançamento antigo é estornado no financeiro (e na gaveta,
      se era dinheiro com o turno aberto).</p>
    <p v-if="hasInvoice" class="warn"><i class="pi pi-exclamation-triangle" /> A nota fiscal já autorizada continua com a
      forma original.</p>

    <div class="field">
      <label>Pagamento a trocar</label>
      <div class="pays">
        <button v-for="p in payments" :key="p.id" type="button" class="pay" :class="{ active: paymentId === p.id }"
                @click="paymentId = p.id">
          <strong>{{ p.method_name }}</strong>
          <span>{{ money(p.amount) }}<small v-if="p.installments > 1"> · {{ p.installments }}x</small><small v-if="p.nsu"> · NSU {{ p.nsu }}</small></span>
        </button>
      </div>
    </div>

    <div v-if="payment" class="grid">
      <div class="field">
        <label for="opd-method">Nova forma</label>
        <Select v-model="methodId" input-id="opd-method" :options="methods" option-label="name" option-value="id" fluid
                :option-disabled="(m: PaymentMethod) => m.id === payment!.method" placeholder="Escolha" />
      </div>
      <div v-if="method && (method.max_installments ?? 1) > 1" class="field">
        <label>Parcelas</label>
        <InputNumber v-model="installments" :min="1" :max="method.max_installments" show-buttons fluid />
      </div>
      <div v-if="method?.requires_reference" class="field">
        <label for="opd-nsu">NSU / autorização</label>
        <InputText id="opd-nsu" v-model="nsu" fluid placeholder="Do comprovante" />
      </div>
    </div>

    <div class="field">
      <label for="opd-reason">Motivo <b class="req">*</b></label>
      <InputText id="opd-reason" v-model="reason" fluid placeholder="Ex.: o caixa lançou PIX, mas foi cartão" />
    </div>
    <div class="opd__foot">
      <Button label="Cancelar" severity="secondary" text @click="emit('close')" />
      <Button label="Trocar forma" icon="pi pi-check" :loading="saving" :disabled="!ready || saving" @click="save" />
    </div>
  </div>
</template>

<style scoped>
.opd { display: flex; flex-direction: column; gap: 12px; min-width: min(560px, 100%); }
.opd p { margin: 0; font-size: 13px; }
.warn { color: var(--warning-text); display: flex; gap: 6px; align-items: center; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 12.5px; font-weight: 600; color: var(--text-muted); }
.req { color: var(--danger-text); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.pays { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(180px, 100%), 1fr)); gap: 8px; }
.pay { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; text-align: left; cursor: pointer; border-radius: 10px;
       border: 1px solid var(--border); background: var(--surface-card); font-family: var(--font-sans); color: var(--text-body); }
.pay strong { color: var(--text-strong); font-size: 13.5px; }
.pay small { color: var(--text-muted); }
.pay:hover { border-color: var(--brand-border); }
.pay.active { border-color: var(--brand); background: var(--brand-subtle); }
.opd__foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
