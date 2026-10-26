<script setup lang="ts">
/**
 * Link de avaliação da venda: o cliente abre no celular (sem login) e avalia os produtos e
 * a entrega. Copiar o link, copiar a mensagem pronta ou abrir direto no WhatsApp do cliente.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import { computed, ref, watch } from "vue";

import { reviewsApi } from "@/api/reviews";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";

const props = defineProps<{ ctx: FormActionContext }>();
const notify = useNotify();
const query = useQuery({ queryKey: ["review-link", props.ctx.id], queryFn: () => reviewsApi.link(props.ctx.id) });
const text = ref("");
watch(() => query.data.value, (link) => link && (text.value = link.text), { immediate: true });
const whatsapp = computed(() => {
  const phone = query.data.value?.phone ?? "";
  const number = phone.length >= 10 && !phone.startsWith("55") ? `55${phone}` : phone;
  return `https://wa.me/${number}?text=${encodeURIComponent(text.value)}`;
});

async function copy(value: string, what: string) {
  try {
    await navigator.clipboard.writeText(value);
    notify.success(`${what} copiado`);
  } catch {
    notify.warn("Não deu para copiar: selecione e copie manualmente.");
  }
}
</script>

<template>
  <div class="link">
    <p v-if="query.isError.value" class="error"><i class="pi pi-exclamation-circle" /> {{ (query.error.value as Error)?.message ?? "Não foi possível gerar o link." }}</p>
    <template v-else-if="query.data.value">
      <p class="muted">O cliente abre no celular, sem login, e avalia os produtos{{ ctx.values.shipping_address ? " e a entrega" : "" }}.
        O link vale por 120 dias.</p>
      <label>Link
        <span class="row">
          <InputText :model-value="query.data.value.url" readonly fluid @focus="($event.target as HTMLInputElement).select()" />
          <Button icon="pi pi-copy" severity="secondary" outlined aria-label="Copiar link" @click="copy(query.data.value.url, 'Link')" />
        </span>
      </label>
      <label>Mensagem
        <Textarea v-model="text" rows="4" auto-resize fluid />
      </label>
      <div class="actions">
        <Button label="Copiar mensagem" icon="pi pi-copy" severity="secondary" outlined @click="copy(text, 'Mensagem')" />
        <a :href="whatsapp" target="_blank" rel="noopener" class="p-button p-component wa">
          <i class="pi pi-whatsapp" /> {{ query.data.value.phone ? "Enviar no WhatsApp do cliente" : "Abrir no WhatsApp" }}
        </a>
      </div>
    </template>
    <p v-else class="muted">Gerando o link…</p>
  </div>
</template>

<style scoped>
.link { display: flex; flex-direction: column; gap: 12px; }
.link > p { margin: 0; font-size: 13px; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.row { display: flex; gap: 6px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.wa { display: inline-flex; gap: 8px; align-items: center; background: #1fa855; border-color: #1fa855; color: #fff; text-decoration: none; }
.error { color: var(--danger-text); display: flex; gap: 6px; align-items: center; }
</style>
