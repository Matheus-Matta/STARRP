<script setup lang="ts">
/**
 * Faixas de CEP da tabela de frete (padrão do StarHub): CEP inicial e final, valor e
 * prazo próprio (vazio = o da tabela). Faixa dentro de faixa vale: a mais estreita
 * ganha ("Centro" dentro de "Capital").
 */
import Button from "primevue/button";
import InputMask from "primevue/inputmask";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";

import { MASKS } from "@/utils/masks";

export type ZipRange = { id?: string; zip_start: string; zip_end: string; value: string | null; lead_days: number | null; label: string };

const model = defineModel<ZipRange[]>({ default: () => [] });
defineProps<{ disabled?: boolean }>();

function add() {
  model.value = [...model.value, { zip_start: "", zip_end: "", value: null, lead_days: null, label: "" }];
}
function update(index: number, patch: Partial<ZipRange>) {
  model.value = model.value.map((r, i) => (i === index ? { ...r, ...patch } : r));
}
function remove(index: number) {
  model.value = model.value.filter((_, i) => i !== index);
}
const inverted = (r: ZipRange) => r.zip_start.length === 8 && r.zip_end.length === 8 && r.zip_start > r.zip_end;
</script>

<template>
  <div class="ranges">
    <div v-if="model.length" class="ranges__head" aria-hidden="true">
      <span>Nome da faixa</span><span>CEP inicial</span><span>CEP final</span><span>Valor</span><span>Prazo (dias)</span><span />
    </div>
    <div v-for="(r, i) in model" :key="r.id ?? `new-${i}`" class="row" :class="{ bad: inverted(r) }">
      <InputText :model-value="r.label" placeholder="Capital, Zona Sul…" fluid :disabled="disabled" aria-label="Nome da faixa"
                 @update:model-value="update(i, { label: String($event ?? '') })" />
      <InputMask :model-value="r.zip_start" :mask="MASKS.cep" unmask :auto-clear="false" placeholder="00000-000" fluid
                 :disabled="disabled" aria-label="CEP inicial" @update:model-value="update(i, { zip_start: String($event ?? '') })" />
      <InputMask :model-value="r.zip_end" :mask="MASKS.cep" unmask :auto-clear="false" placeholder="99999-999" fluid
                 :disabled="disabled" aria-label="CEP final" :invalid="inverted(r)"
                 @update:model-value="update(i, { zip_end: String($event ?? '') })" />
      <InputNumber :model-value="r.value === null ? null : Number(r.value)" mode="currency" currency="BRL" locale="pt-BR" fluid
                   :disabled="disabled" aria-label="Valor" @update:model-value="update(i, { value: $event === null ? null : Number($event).toFixed(2) })" />
      <InputNumber :model-value="r.lead_days" :min="0" placeholder="da tabela" fluid :disabled="disabled" aria-label="Prazo em dias"
                   @update:model-value="update(i, { lead_days: $event })" />
      <Button icon="pi pi-trash" text rounded severity="danger" size="small" :disabled="disabled" aria-label="Remover faixa"
              @click="remove(i)" />
      <small v-if="inverted(r)" class="err">O CEP final tem que ser maior que o inicial.</small>
    </div>
    <Button label="Adicionar faixa" icon="pi pi-plus" severity="secondary" outlined size="small" class="add" :disabled="disabled"
            @click="add" />
  </div>
</template>

<style scoped>
.ranges { display: flex; flex-direction: column; gap: 8px; }
.ranges__head, .row { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr 0.8fr 36px; gap: 8px; align-items: center; }
.ranges__head span { font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); }
.err { grid-column: 1 / -1; color: var(--danger-text); font-size: 12px; }
.add { align-self: flex-start; }
@media (max-width: 760px) {
  .ranges__head { display: none; }
  .row { grid-template-columns: 1fr 1fr; padding: 8px; border: 1px solid var(--border); border-radius: 8px; }
}
</style>
