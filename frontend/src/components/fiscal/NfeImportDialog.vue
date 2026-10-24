<script setup lang="ts">
/**
 * Importar o XML da nota (o fornecedor mandou por e-mail, ou a SEFAZ ainda não
 * liberou). Aceita vários arquivos de uma vez; com um só, abre a nota.
 */
import Button from "primevue/button";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { toApiError } from "@/api/errors";
import { nfeApi } from "@/api/fiscal";
import type { FormActionContext } from "@/resources/types";

defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: [] }>();
const router = useRouter();
const files = ref<File[]>([]);
const sending = ref(false);
const results = ref<{ name: string; ok: boolean; message: string; id?: string }[]>([]);

function pick(event: Event) {
  files.value = [...((event.target as HTMLInputElement).files ?? [])];
  results.value = [];
}

async function send() {
  sending.value = true;
  results.value = [];
  for (const file of files.value) {
    try {
      const nfe = await nfeApi.importXml(file);
      results.value.push({ name: file.name, ok: true, message: "Importada", id: nfe.id });
    } catch (error) {
      results.value.push({ name: file.name, ok: false, message: toApiError(error).message });
    }
  }
  sending.value = false;
  const only = results.value.length === 1 ? results.value[0] : undefined;
  if (only?.ok) {
    emit("done");
    void router.push(`/cadastros/notas-de-entrada/${only.id}`);
  }
}
</script>

<template>
  <div class="import">
    <label class="drop" :class="{ chosen: files.length }">
      <input type="file" accept=".xml,text/xml" multiple @change="pick">
      <i class="pi pi-file-import" />
      <span>{{ files.length ? `${files.length} arquivo(s): ${files.map((f) => f.name).join(", ")}` : "Escolha o XML da NF-e (um ou vários)" }}</span>
    </label>
    <ul v-if="results.length" class="rows">
      <li v-for="r in results" :key="r.name" :class="r.ok ? 'ok' : 'error'">
        <i :class="r.ok ? 'pi pi-check' : 'pi pi-times'" /> <b>{{ r.name }}</b> {{ r.message }}
      </li>
    </ul>
    <div class="foot">
      <Button v-if="results.length" label="Fechar" severity="secondary" outlined @click="emit('done')" />
      <Button label="Importar" icon="pi pi-upload" :loading="sending" :disabled="!files.length" @click="send" />
    </div>
  </div>
</template>

<style scoped>
.import { display: flex; flex-direction: column; gap: 0.85rem; }
.drop {
  display: flex; align-items: center; gap: 10px; padding: 22px; border: 1.5px dashed var(--border-strong);
  border-radius: 10px; cursor: pointer; color: var(--text-muted); font-size: 13px;
}
.drop:hover, .drop.chosen { border-color: var(--brand); color: var(--text-strong); }
.drop input { display: none; }
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.rows li { padding: 6px 10px; border-radius: 6px; }
.ok { background: var(--success-subtle); color: var(--success-text); }
.error { background: var(--danger-subtle); color: var(--danger-text); }
.foot { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
