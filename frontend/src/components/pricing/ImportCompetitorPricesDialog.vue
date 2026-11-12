<script setup lang="ts">
/** Planilha de preços de concorrentes: entra o que está certo e as linhas com problema voltam com o motivo. */
import Button from "primevue/button";
import { ref } from "vue";

import { pricingApi, type CompetitorImport } from "@/api/pricing";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";

defineProps<{ ctx?: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const input = ref<HTMLInputElement>();
const sending = ref(false);
const result = ref<CompetitorImport | null>(null);

async function send(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  sending.value = true;
  try {
    result.value = await pricingApi.importCompetitors(file);
    if (!result.value.error_count) {
      notify.success("Planilha importada", `${result.value.imported} preço(s) em ${result.value.products} produto(s).`);
      emit("done");
    }
  } catch (error) {
    notify.error(error, "Planilha não importada");
  } finally {
    sending.value = false;
    if (input.value) input.value.value = "";
  }
}
</script>

<template>
  <div class="import">
    <p>Uma linha por preço, em .xlsx ou .csv, com estas colunas na primeira linha:</p>
    <ul>
      <li><strong>Produto</strong>: SKU ou código de barras</li>
      <li><strong>Concorrente</strong>: a loja ou o site</li>
      <li><strong>Preço</strong></li>
      <li><strong>Data</strong> e <strong>Link</strong>: opcionais (sem data, vale hoje)</li>
    </ul>
    <div v-if="result" class="result">
      <strong>{{ result.imported }} preço(s) importado(s), {{ result.error_count }} linha(s) com problema</strong>
      <ul class="errors">
        <li v-for="e in result.errors" :key="e.linha">Linha {{ e.linha }}: {{ e.erro }}</li>
      </ul>
    </div>
    <input ref="input" type="file" accept=".xlsx,.xlsm,.csv,.tsv" hidden @change="send" />
    <div class="foot">
      <Button :label="result ? 'Fechar' : 'Voltar'" severity="secondary" text @click="result ? emit('done') : emit('close')" />
      <Button label="Escolher planilha" icon="pi pi-upload" :loading="sending" @click="input?.click()" />
    </div>
  </div>
</template>

<style scoped>
.import { display: flex; flex-direction: column; gap: 10px; font-size: 13px; min-width: min(420px, 80vw); }
p, ul { margin: 0; }
ul { padding-left: 18px; display: grid; gap: 3px; }
.result { padding: 10px 12px; border-radius: 8px; background: var(--warning-subtle); display: grid; gap: 6px; }
.errors { max-height: 180px; overflow-y: auto; }
.foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
