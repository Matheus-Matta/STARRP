<script setup lang="ts">
/**
 * Endereços do pedido na retaguarda: corrige a entrega e a cobrança só deste pedido, ou copia
 * de novo do cadastro do cliente ("Usar o do cliente").
 */
import Button from "primevue/button";
import { ref } from "vue";

import { blankAddress, type OrderAddresses, salesApi } from "@/api/sales";
import OrderAddressForm from "@/components/sales/OrderAddressForm.vue";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const current = props.ctx.values.addresses as OrderAddresses | undefined;
const draft = ref<OrderAddresses>(JSON.parse(JSON.stringify(current?.delivery ? current
  : { delivery: blankAddress(), billing: null, billing_same_as_delivery: true })) as OrderAddresses);
const saving = ref(false);

async function run(action: () => Promise<OrderAddresses>, done: string) {
  saving.value = true;
  try {
    draft.value = await action();
    notify.success(done);
    emit("done");
  } catch (error) {
    notify.error(error, "Endereço não salvo");
  } finally {
    saving.value = false;
  }
}
const save = () => run(() => salesApi.saveAddresses(props.ctx.id, draft.value), "Endereços do pedido salvos");
const inherit = () => run(() => salesApi.saveAddresses(props.ctx.id, { inherit: true }), "Endereços copiados do cliente");
</script>

<template>
  <div class="oad">
    <p class="muted">Vale só para este pedido: o cadastro do cliente fica como está.</p>
    <OrderAddressForm v-model="draft" :disabled="saving" />
    <div class="oad__foot">
      <Button v-if="ctx.values.customer" label="Usar o do cliente" icon="pi pi-refresh" severity="secondary" text
              :disabled="saving" @click="inherit" />
      <Button label="Salvar endereços" icon="pi pi-check" :loading="saving" @click="save" />
    </div>
  </div>
</template>

<style scoped>
.oad { display: flex; flex-direction: column; gap: 12px; min-width: min(720px, 100%); }
.oad > p { margin: 0; font-size: 13px; }
.oad__foot { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
</style>
