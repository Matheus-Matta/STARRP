<script setup lang="ts">
/**
 * "Buscar na SEFAZ": consulta já, ao abrir. Da lista de notas busca em todos os
 * CNPJs; dentro de um "Dados fiscais" (`ctx.id`), só nele. Mostra o que cada
 * CNPJ trouxe ou por que não deu (sem certificado, intervalo da SEFAZ...).
 */
import Button from "primevue/button";
import ProgressSpinner from "primevue/progressspinner";
import { onMounted, ref } from "vue";

import { type DfeResult, nfeApi } from "@/api/fiscal";
import { toApiError } from "@/api/errors";
import type { FormActionContext } from "@/resources/types";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: [] }>();
const results = ref<DfeResult[] | null>(null);
const failure = ref("");

onMounted(async () => {
  try {
    results.value = (await nfeApi.sync(props.ctx.id || undefined)).results;
  } catch (error) {
    failure.value = toApiError(error).message;
  }
});
</script>

<template>
  <div class="sync">
    <div v-if="!results && !failure" class="loading">
      <ProgressSpinner style="width: 34px; height: 34px" stroke-width="5" />
      <span>Consultando a SEFAZ… pode levar alguns segundos por CNPJ.</span>
    </div>
    <p v-else-if="failure" class="row row--error"><i class="pi pi-times-circle" /> {{ failure }}</p>
    <ul v-else class="rows">
      <li v-for="r in results" :key="r.config" class="row" :class="r.ok ? 'row--ok' : 'row--error'">
        <i :class="r.ok ? 'pi pi-check-circle' : 'pi pi-exclamation-circle'" />
        <div>
          <strong>{{ r.config }}</strong>
          <small v-if="r.ok">{{ r.notes ? `${r.notes} nota(s) nova(s)` : "Nenhuma nota nova" }} · {{ r.message }}</small>
          <small v-else>{{ r.message }}</small>
        </div>
      </li>
    </ul>
    <div class="foot">
      <Button label="Fechar" severity="secondary" outlined :disabled="!results && !failure" @click="emit('done')" />
    </div>
  </div>
</template>

<style scoped>
.loading { display: flex; align-items: center; gap: 12px; padding: 18px 4px; color: var(--text-muted); font-size: 13.5px; }
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.row { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 8px; margin: 0; }
.row i { margin-top: 2px; }
.row div { display: flex; flex-direction: column; gap: 1px; }
.row strong { font-size: 13.5px; color: var(--text-strong); }
.row small { font-size: 12.5px; color: var(--text-muted); }
.row--ok { background: var(--success-subtle); color: var(--success-text); }
.row--error { background: var(--danger-subtle); color: var(--danger-text); }
.foot { display: flex; justify-content: flex-end; margin-top: 1rem; }
</style>
