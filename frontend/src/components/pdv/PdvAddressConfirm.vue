<script setup lang="ts">
/**
 * Etapa do PDV entre a venda e o pagamento (config da filial "Confirmar endereço antes do
 * pagamento"): mostra o endereço de entrega e de cobrança do pedido, herdados do cliente, para
 * conferir e corrigir. Confirmar grava no pedido (o cadastro do cliente não muda) e segue para
 * o pagamento. Pedido sem endereço nem chega aqui.
 */
import Button from "primevue/button";
import { ref, watch } from "vue";

import { type OrderAddresses, salesApi } from "@/api/sales";
import type { Sale } from "@/api/types";
import OrderAddressForm from "@/components/sales/OrderAddressForm.vue";
import { useNotify } from "@/composables/useNotify";

const props = defineProps<{ sale: Sale }>();
const emit = defineEmits<{ confirmed: [addresses: OrderAddresses]; back: [] }>();
const notify = useNotify();
/** Cópia simples: o endereço vem de um objeto reativo (o `structuredClone` não aceita proxy). */
const copy = (value: unknown) => JSON.parse(JSON.stringify(value)) as OrderAddresses;
const draft = ref<OrderAddresses>(copy(props.sale.addresses));
const saving = ref(false);
watch(() => props.sale.id, () => (draft.value = copy(props.sale.addresses)));

async function confirm() {
  saving.value = true;
  try {
    const saved = await salesApi.saveAddresses(String(props.sale.id), draft.value);
    emit("confirmed", saved);
  } catch (error) {
    notify.error(error, "Confira o endereço");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="panel">
    <header class="panel__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para a venda" @click="emit('back')" />
      <div>
        <h2>Confirme o endereço</h2>
        <p>Pedido {{ sale.number }}{{ sale.customer_name ? ` de ${sale.customer_name}` : "" }}: veio do cadastro do cliente.
          Corrija o que estiver errado (vale só para este pedido).</p>
      </div>
    </header>
    <OrderAddressForm v-model="draft" :disabled="saving" />
    <footer class="panel__foot">
      <Button label="Voltar" severity="secondary" text @click="emit('back')" />
      <Button label="Confirmar e ir para o pagamento" icon="pi pi-arrow-right" icon-pos="right" :loading="saving" autofocus
              @click="confirm" />
    </footer>
  </section>
</template>

<style scoped>
.panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; padding: 12px; overflow-y: auto; }
.panel__head { display: flex; align-items: flex-start; gap: 10px; }
.panel__head h2 { margin: 0; font: 700 17px/1.2 var(--font-sans); color: var(--text-strong); }
.panel__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.panel__foot { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; position: sticky; bottom: 0; padding-top: 8px;
               background: linear-gradient(transparent, var(--surface-ground) 30%); }
</style>
