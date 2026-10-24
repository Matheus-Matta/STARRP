<script setup lang="ts">
/** Lista de códigos de barras do produto (vários por item, um principal). */
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import RadioButton from "primevue/radiobutton";
import { ref } from "vue";

type Barcode = { code: string; is_primary: boolean };
const model = defineModel<Barcode[]>({ default: () => [] });
const draft = ref("");

function add() {
  const code = draft.value.trim();
  if (!code || model.value.some((b) => b.code === code)) return;
  model.value = [...model.value, { code, is_primary: model.value.length === 0 }];
  draft.value = "";
}

function remove(code: string) {
  const rest = model.value.filter((b) => b.code !== code);
  if (rest.length && !rest.some((b) => b.is_primary)) rest[0]!.is_primary = true;
  model.value = rest;
}

function makePrimary(code: string) {
  model.value = model.value.map((b) => ({ ...b, is_primary: b.code === code }));
}
</script>

<template>
  <div class="barcodes">
    <div class="add">
      <InputText v-model="draft" placeholder="Leia ou digite o código e tecle Enter" @keydown.enter.prevent="add" />
      <Button icon="pi pi-plus" severity="secondary" aria-label="Adicionar código" @click="add" />
    </div>
    <ul v-if="model.length">
      <li v-for="item in model" :key="item.code">
        <RadioButton :model-value="item.is_primary" :value="true" @update:model-value="makePrimary(item.code)" />
        <code>{{ item.code }}</code>
        <span v-if="item.is_primary" class="muted">principal</span>
        <Button icon="pi pi-trash" text severity="danger" aria-label="Remover" @click="remove(item.code)" />
      </li>
    </ul>
  </div>
</template>

<style scoped>
.barcodes { display: flex; flex-direction: column; gap: 0.5rem; }
.add { display: flex; gap: 0.5rem; }
.add :deep(input) { flex: 1; }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; }
li { display: flex; align-items: center; gap: 0.75rem; }
code { font-size: 0.95rem; }
</style>
