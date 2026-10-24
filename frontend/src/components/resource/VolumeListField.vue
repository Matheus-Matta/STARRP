<script setup lang="ts">
/**
 * Volumes (caixas) da variante: um guarda-roupa que chega em 3 caixas tem 3 linhas.
 * A ordem da lista é o número da caixa (1ª = Vol 1). Cubagem e peso total
 * aparecem na hora, para conferir com a nota do fabricante.
 */
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import { computed } from "vue";

import { quantity } from "@/utils/format";

export type Volume = {
  id?: string;
  description: string;
  barcode: string;
  gross_weight: string | null;
  height_cm: string | null;
  width_cm: string | null;
  length_cm: string | null;
};

const model = defineModel<Volume[]>({ default: () => [] });

const num = (v: string | null) => (v === null || v === "" ? null : Number(v));
const text = (v: number | null, places: number) => (v === null ? null : v.toFixed(places));

function cubic(v: Volume) {
  const [h, w, l] = [num(v.height_cm), num(v.width_cm), num(v.length_cm)];
  return h && w && l ? (h * w * l) / 1_000_000 : 0;
}

const totals = computed(() => ({
  weight: model.value.reduce((sum, v) => sum + (num(v.gross_weight) ?? 0), 0),
  cubic: model.value.reduce((sum, v) => sum + cubic(v), 0),
}));

function add() {
  model.value = [...model.value, {
    description: "", barcode: "", gross_weight: null, height_cm: null, width_cm: null, length_cm: null,
  }];
}

function update(index: number, patch: Partial<Volume>) {
  model.value = model.value.map((v, i) => (i === index ? { ...v, ...patch } : v));
}

function remove(index: number) {
  model.value = model.value.filter((_, i) => i !== index);
}

function move(index: number, step: -1 | 1) {
  const list = [...model.value];
  const target = index + step;
  if (target < 0 || target >= list.length) return;
  [list[index], list[target]] = [list[target]!, list[index]!];
  model.value = list;
}
</script>

<template>
  <div class="volumes">
    <p v-if="!model.length" class="empty muted">
      Vende montado e entrega em caixas? Cadastre cada caixa: etiqueta, conferência e frete passam a contar por volume.
    </p>
    <div v-for="(volume, index) in model" :key="volume.id ?? index" class="volume">
      <div class="volume__badge">
        <strong>Vol {{ index + 1 }}</strong>
        <small>de {{ model.length }}</small>
      </div>
      <div class="volume__fields">
        <InputText :model-value="volume.description" placeholder="Conteúdo (ex.: Portas)" fluid
                   @update:model-value="update(index, { description: String($event ?? '') })" />
        <InputText :model-value="volume.barcode" placeholder="Código da caixa" fluid
                   @update:model-value="update(index, { barcode: String($event ?? '') })" />
        <InputNumber :model-value="num(volume.gross_weight)" placeholder="Peso (kg)" suffix=" kg" :max-fraction-digits="3"
                     locale="pt-BR" fluid @update:model-value="update(index, { gross_weight: text($event, 3) })" />
        <div class="dims">
          <InputNumber v-for="key in (['height_cm', 'width_cm', 'length_cm'] as const)" :key="key"
                       :model-value="num(volume[key])" :placeholder="{ height_cm: 'Alt.', width_cm: 'Larg.', length_cm: 'Comp.' }[key]"
                       :max-fraction-digits="1" locale="pt-BR" fluid
                       @update:model-value="update(index, { [key]: text($event, 1) })" />
          <span class="unit">cm</span>
        </div>
      </div>
      <div class="volume__actions">
        <Button icon="pi pi-arrow-up" text rounded size="small" aria-label="Subir" :disabled="index === 0" @click="move(index, -1)" />
        <Button icon="pi pi-arrow-down" text rounded size="small" aria-label="Descer" :disabled="index === model.length - 1"
                @click="move(index, 1)" />
        <Button icon="pi pi-trash" text rounded size="small" severity="danger" aria-label="Remover caixa" @click="remove(index)" />
      </div>
    </div>
    <div class="footer">
      <Button label="Adicionar caixa" icon="pi pi-plus" severity="secondary" outlined size="small" @click="add" />
      <span v-if="model.length" class="muted">
        {{ model.length }} {{ model.length === 1 ? "caixa" : "caixas" }} · {{ quantity(totals.weight) }} kg ·
        {{ totals.cubic.toLocaleString("pt-BR", { maximumFractionDigits: 4 }) }} m³
      </span>
    </div>
  </div>
</template>

<style scoped>
.volumes { display: flex; flex-direction: column; gap: 0.6rem; }
.empty { margin: 0; font-size: 13px; }
.volume {
  display: grid; grid-template-columns: auto 1fr auto; gap: 0.75rem; align-items: center; padding: 0.6rem 0.75rem;
  border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-sunken);
  transition: border-color var(--dur-fast) ease;
}
.volume:hover { border-color: var(--brand-border); }
.volume__badge {
  display: flex; flex-direction: column; align-items: center; justify-content: center; width: 3.4rem; height: 3.4rem;
  border-radius: var(--radius-sm); background: var(--brand-subtle); color: var(--text-brand); line-height: 1.1;
}
.volume__badge strong { font-size: 13px; }
.volume__badge small { font-size: 11px; color: var(--text-muted); }
.volume__fields { display: grid; grid-template-columns: 1.4fr 1fr 0.8fr 1.6fr; gap: 0.5rem; min-width: 0; }
.dims { display: flex; gap: 0.35rem; align-items: center; }
.unit { font-size: 12px; color: var(--text-muted); }
.volume__actions { display: flex; gap: 0.1rem; }
.footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; font-size: 13px; }
@media (max-width: 900px) {
  .volume { grid-template-columns: 1fr; }
  .volume__badge { flex-direction: row; gap: 0.35rem; width: auto; height: auto; padding: 0.25rem 0.6rem; justify-self: start; }
  .volume__fields { grid-template-columns: 1fr 1fr; }
  .dims { grid-column: 1 / -1; }
}
</style>
