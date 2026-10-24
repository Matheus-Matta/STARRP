<script setup lang="ts">
/** Consulta de preço (F5): lê o código e mostra preço vigente, promoção e estoque, sem lançar na venda. */
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import { nextTick, ref, watch } from "vue";

import { salesApi } from "@/api/sales";
import type { VariantLookup } from "@/api/types";
import { money, quantity } from "@/utils/format";

const props = defineProps<{ visible: boolean }>();
const emit = defineEmits<{ close: [] }>();
const code = ref("");
const found = ref<VariantLookup | null>(null);
const error = ref("");

async function check() {
  const value = code.value.trim();
  if (!value) return;
  error.value = "";
  try {
    found.value = await salesApi.lookup(value);
  } catch {
    found.value = null;
    error.value = `Nada encontrado para “${value}”.`;
  }
  code.value = "";
}

watch(() => props.visible, async (open) => {
  if (!open) return;
  found.value = null;
  error.value = "";
  await nextTick();
  document.getElementById("pdv-price-code")?.focus();
});
</script>

<template>
  <Dialog :visible="visible" modal header="Consulta de preço" :style="{ width: 'min(460px, calc(100vw - 24px))' }"
          @update:visible="emit('close')">
    <InputText id="pdv-price-code" v-model="code" placeholder="Leia ou digite o código e tecle Enter" fluid @keydown.enter.prevent="check" />
    <p v-if="error" class="error">{{ error }}</p>
    <div v-if="found" class="result">
      <strong>{{ found.display_name }}</strong>
      <small>{{ found.sku }}</small>
      <span class="price">
        <s v-if="found.list_price !== found.current_price">{{ money(found.list_price) }}</s>
        {{ money(found.current_price) }}<small v-if="found.sold_by_weight"> / kg</small>
      </span>
      <small v-if="found.stock_quantity != null">{{ quantity(found.stock_quantity) }} em estoque</small>
    </div>
  </Dialog>
</template>

<style scoped>
.error { margin: 10px 0 0; color: var(--danger-text); font-size: 13px; }
.result { display: flex; flex-direction: column; gap: 3px; margin-top: 14px; padding: 14px; border-radius: 10px; background: var(--surface-sunken); }
.result strong { font-size: 16px; color: var(--text-strong); }
.result small { font-size: 12px; color: var(--text-muted); }
.price { margin: 6px 0 2px; font: 800 2rem/1 var(--font-sans); color: var(--brand); }
.price s { font-size: 1rem; font-weight: 600; color: var(--text-subtle); margin-right: 6px; }
.price small { font-size: 0.9rem; }
</style>
