<script setup lang="ts">
/**
 * Editor da grade: eixos (Cor, Tamanho) e seus valores. No salvar, o backend
 * cria as combinações que faltam — as que já existem ficam como estão.
 * Ex.: Tamanho [P, M] × Cor [Azul, Preto] = 4 variantes.
 */
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import { computed, ref, watch } from "vue";

import TagsInput from "./TagsInput.vue";

type Grid = Record<string, string[]>;
type Axis = { name: string; values: string[] };

const model = defineModel<Grid | null | undefined>();
const props = defineProps<{ existing?: { attribute: string; value: string }[][] }>();

const axes = ref<Axis[]>([]);
/** Valores que as variantes já usam, por eixo: viram sugestão no campo. */
const known = computed(() => {
  const map: Record<string, string[]> = {};
  for (const options of props.existing ?? []) {
    for (const o of options) map[o.attribute] = [...new Set([...(map[o.attribute] ?? []), o.value])];
  }
  return map;
});

/** Começa pelos eixos que as variantes já usam: fica claro o que existe. */
function seed() {
  const found = new Map<string, Set<string>>();
  for (const options of props.existing ?? []) {
    for (const option of options) found.set(option.attribute, (found.get(option.attribute) ?? new Set()).add(option.value));
  }
  axes.value = found.size
    ? [...found.entries()].map(([name, values]) => ({ name, values: [...values] }))
    : [{ name: "", values: [] }];
}
seed();
watch(() => props.existing, () => { if (model.value === undefined) seed(); });

function emit() {
  const grid: Grid = {};
  for (const axis of axes.value) {
    const name = axis.name.trim();
    const values = axis.values.map((v) => v.trim()).filter(Boolean);
    if (name && values.length) grid[name] = values;
  }
  // {} também vai: "tirei todos os eixos" é uma mudança (as variantes viram uma só).
  model.value = grid;
}

const combos = computed(() => {
  const counts = axes.value.map((a) => a.values.length).filter(Boolean);
  return counts.length ? counts.reduce((a, b) => a * b, 1) : 0;
});

function addAxis() {
  axes.value = [...axes.value, { name: "", values: [] }];
}

function removeAxis(index: number) {
  axes.value = axes.value.filter((_, i) => i !== index);
  emit();
}
</script>

<template>
  <div class="grid-editor">
    <div v-for="(axis, index) in axes" :key="index" class="axis">
      <InputText v-model="axis.name" placeholder="Eixo (ex.: Cor)" class="axis__name" @update:model-value="emit" />
      <TagsInput v-model="axis.values" placeholder="P, M, G… (Enter ou vírgula)" class="axis__values"
                 :suggestions="known[axis.name.trim()] ?? []" @update:model-value="emit" />
      <Button icon="pi pi-times" text rounded severity="secondary" aria-label="Remover eixo" @click="removeAxis(index)" />
    </div>
    <div class="footer">
      <Button label="Adicionar eixo" icon="pi pi-plus" severity="secondary" outlined size="small" @click="addAxis" />
      <span v-if="combos" class="muted">
        <i class="pi pi-th-large" /> {{ combos }} {{ combos === 1 ? "combinação" : "combinações" }} — veja nas variantes abaixo o que entra e o que sai
      </span>
    </div>
  </div>
</template>

<style scoped>
.grid-editor { display: flex; flex-direction: column; gap: 0.6rem; }
.axis { display: grid; grid-template-columns: minmax(140px, 220px) 1fr auto; gap: 0.5rem; align-items: start; }
.footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; font-size: 13px; }
.footer i { margin-right: 0.25rem; }
@media (max-width: 640px) { .axis { grid-template-columns: 1fr auto; } .axis__values { grid-column: 1 / -1; grid-row: 2; } }
</style>
