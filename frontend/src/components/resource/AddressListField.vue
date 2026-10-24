<script setup lang="ts">
/**
 * Endereços de entrega do cliente (trabalhamos com entrega): um cartão por endereço,
 * com nome ("Casa", "Trabalho"), o CEP que preenche rua/bairro/cidade/UF, número,
 * complemento e ponto de referência para o entregador. Um só é o padrão (a estrela).
 * A lista inteira vai no salvar do cliente; o que sai daqui é apagado.
 */
import Button from "primevue/button";
import InputMask from "primevue/inputmask";
import InputText from "primevue/inputtext";
import { ref } from "vue";

import { lookupCep, MASKS } from "@/utils/masks";

export type Address = {
  id?: string;
  label: string;
  zip_code: string;
  street: string;
  number: string;
  complement: string;
  district: string;
  city: string;
  state: string;
  city_ibge?: string;
  reference: string;
  is_default: boolean;
};

const model = defineModel<Address[]>({ default: () => [] });
defineProps<{ disabled?: boolean }>();
const notes = ref<Record<number, string>>({});

const blank = (first: boolean): Address => ({
  label: first ? "Casa" : "", zip_code: "", street: "", number: "", complement: "", district: "", city: "", state: "",
  reference: "", is_default: first,
});

function add() {
  model.value = [...model.value, blank(!model.value.length)];
}
function update(index: number, patch: Partial<Address>) {
  model.value = model.value.map((a, i) => (i === index ? { ...a, ...patch } : a));
}
function makeDefault(index: number) {
  model.value = model.value.map((a, i) => ({ ...a, is_default: i === index }));
}
function remove(index: number) {
  const removed = model.value[index];
  const rest = model.value.filter((_, i) => i !== index);
  // Saiu o padrão: o primeiro que sobrou vira o padrão.
  model.value = removed?.is_default && rest.length ? rest.map((a, i) => ({ ...a, is_default: i === 0 })) : rest;
}
async function cep(index: number, event: Event) {
  notes.value = { ...notes.value, [index]: "Buscando o endereço…" };
  const found = await lookupCep((event.target as HTMLInputElement).value);
  notes.value = { ...notes.value, [index]: found ? "Endereço preenchido pelo CEP." : "CEP não encontrado: preencha à mão." };
  if (found) {
    const rest = { ...found };
    delete rest.complement; // complemento é da casa, não do CEP
    update(index, rest);
  }
}
</script>

<template>
  <div class="addresses">
    <article v-for="(a, i) in model" :key="a.id ?? `new-${i}`" class="addr" :class="{ 'addr--default': a.is_default }">
      <header class="addr__head">
        <InputText :model-value="a.label" placeholder="Nome (Casa, Trabalho…)" size="small" class="addr__label"
                   :disabled="disabled" :aria-label="`Nome do endereço ${i + 1}`" @update:model-value="update(i, { label: String($event ?? '') })" />
        <button type="button" class="star" :class="{ on: a.is_default }" :disabled="disabled"
                :title="a.is_default ? 'Endereço padrão' : 'Tornar padrão'" @click="makeDefault(i)">
          <i :class="a.is_default ? 'pi pi-star-fill' : 'pi pi-star'" /> {{ a.is_default ? "Padrão" : "Tornar padrão" }}
        </button>
        <Button icon="pi pi-trash" text rounded severity="danger" size="small" :disabled="disabled"
                :aria-label="`Remover endereço ${a.label || i + 1}`" @click="remove(i)" />
      </header>
      <div class="addr__grid">
        <label class="c3">CEP
          <InputMask :model-value="a.zip_code" :mask="MASKS.cep" unmask :auto-clear="false" placeholder="00000-000" fluid
                     :disabled="disabled" @update:model-value="update(i, { zip_code: String($event ?? '') })" @complete="cep(i, $event)" />
        </label>
        <label class="c7">Logradouro
          <InputText :model-value="a.street" fluid :disabled="disabled" @update:model-value="update(i, { street: String($event ?? '') })" />
        </label>
        <label class="c2">Número
          <InputText :model-value="a.number" fluid :disabled="disabled" @update:model-value="update(i, { number: String($event ?? '') })" />
        </label>
        <label class="c5">Complemento
          <InputText :model-value="a.complement" placeholder="Apto, bloco, fundos…" fluid :disabled="disabled"
                     @update:model-value="update(i, { complement: String($event ?? '') })" />
        </label>
        <label class="c4">Bairro
          <InputText :model-value="a.district" fluid :disabled="disabled" @update:model-value="update(i, { district: String($event ?? '') })" />
        </label>
        <label class="c3">Cidade / UF
          <span class="city">
            <InputText :model-value="a.city" fluid :disabled="disabled" @update:model-value="update(i, { city: String($event ?? '') })" />
            <InputText :model-value="a.state" maxlength="2" class="uf" :disabled="disabled" aria-label="UF"
                       @update:model-value="update(i, { state: String($event ?? '').toUpperCase() })" />
          </span>
        </label>
        <label class="c12">Ponto de referência (para o entregador)
          <InputText :model-value="a.reference" placeholder="Portão azul, ao lado da padaria…" fluid :disabled="disabled"
                     @update:model-value="update(i, { reference: String($event ?? '') })" />
        </label>
      </div>
      <small v-if="notes[i]" class="note"><i class="pi pi-map-marker" /> {{ notes[i] }}</small>
    </article>
    <Button :label="model.length ? 'Adicionar outro endereço' : 'Adicionar endereço'" icon="pi pi-plus" severity="secondary"
            outlined size="small" class="add" :disabled="disabled" @click="add" />
    <p v-if="!model.length" class="empty">Sem endereço: o cliente só compra com retirada na loja.</p>
  </div>
</template>

<style scoped>
.addresses { display: flex; flex-direction: column; gap: 10px; }
.addr { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px 12px; background: var(--surface-card); }
.addr--default { border-color: var(--brand-border); box-shadow: inset 3px 0 0 var(--brand); }
.addr__head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.addr__label { flex: 1; max-width: 260px; font-weight: 600; }
.star { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; cursor: pointer; font: 600 12px/1 var(--font-sans); color: var(--text-muted); padding: 6px; border-radius: 6px; }
.star.on { color: var(--warning-text); }
.star:hover:enabled { background: var(--surface-hover); }
.addr__head :deep(.p-button) { margin-left: auto; }
.addr__grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 8px 10px; }
.addr__grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-muted); min-width: 0; }
.c2 { grid-column: span 2; } .c3 { grid-column: span 3; } .c4 { grid-column: span 4; } .c5 { grid-column: span 5; }
.c7 { grid-column: span 7; } .c12 { grid-column: span 12; }
.city { display: flex; gap: 6px; }
.uf { width: 52px; flex-shrink: 0; text-transform: uppercase; }
.note { display: flex; gap: 6px; align-items: center; margin-top: 6px; color: var(--text-muted); font-size: 12px; }
.add { align-self: flex-start; }
.empty { margin: 0; font-size: 13px; color: var(--text-muted); }
@media (max-width: 720px) { .addr__grid > * { grid-column: span 12; } }
</style>
