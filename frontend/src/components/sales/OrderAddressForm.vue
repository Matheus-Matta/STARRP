<script setup lang="ts">
/**
 * Endereços do PEDIDO (entrega e cobrança), já herdados do cliente: confere e corrige ali
 * mesmo. O CEP preenche rua, bairro, cidade, UF e IBGE (vários serviços, um cobre o outro).
 * "Cobrança no mesmo endereço da entrega" esconde o segundo endereço.
 * Corrigir aqui muda só o pedido; o cadastro do cliente fica como está.
 */
import Checkbox from "primevue/checkbox";
import InputMask from "primevue/inputmask";
import InputText from "primevue/inputtext";
import { ref } from "vue";

import { blankAddress, type OrderAddress, type OrderAddresses } from "@/api/sales";
import { lookupCep, MASKS } from "@/utils/masks";

const model = defineModel<OrderAddresses>({ required: true });
defineProps<{ disabled?: boolean }>();
const notes = ref<Record<string, string>>({});

function patch(kind: "delivery" | "billing", values: Partial<OrderAddress>) {
  model.value = { ...model.value, [kind]: { ...(model.value[kind] ?? blankAddress()), ...values } };
}
function setSame(same: boolean) {
  // Separou a cobrança: começa como cópia da entrega (é só ajustar o que muda).
  model.value = { ...model.value, billing_same_as_delivery: same,
                  billing: same ? model.value.delivery : { ...(model.value.delivery ?? blankAddress()) } };
}
async function cep(kind: "delivery" | "billing", value: string) {
  notes.value = { ...notes.value, [kind]: "Buscando o endereço…" };
  const found = await lookupCep(value);
  notes.value = { ...notes.value, [kind]: found ? `Endereço preenchido pelo CEP (${found.source}).` : "CEP não encontrado: preencha à mão." };
  if (found) patch(kind, { street: found.street, district: found.district, city: found.city, state: found.state,
                           city_ibge: found.city_ibge });
}
const kinds = (same: boolean) => (same ? (["delivery"] as const) : (["delivery", "billing"] as const));
const TITLE = { delivery: "Endereço de entrega", billing: "Endereço de cobrança" };
</script>

<template>
  <div class="oa">
    <section v-for="kind in kinds(model.billing_same_as_delivery)" :key="kind" class="oa__box">
      <h4><i :class="kind === 'delivery' ? 'pi pi-truck' : 'pi pi-wallet'" /> {{ TITLE[kind] }}
        <small v-if="model[kind]?.from_customer" class="tag">do cadastro do cliente</small></h4>
      <div class="oa__grid">
        <label class="c3">CEP
          <InputMask :model-value="model[kind]?.zip_code ?? ''" :mask="MASKS.cep" unmask :auto-clear="false" placeholder="00000-000"
                     fluid :disabled="disabled" @update:model-value="patch(kind, { zip_code: String($event ?? '') })"
                     @complete="cep(kind, ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="c7">Logradouro
          <InputText :model-value="model[kind]?.street ?? ''" placeholder="Rua, avenida, travessa…" fluid :disabled="disabled"
                     @update:model-value="patch(kind, { street: String($event ?? '') })" />
        </label>
        <label class="c2">Número
          <InputText :model-value="model[kind]?.number ?? ''" placeholder="123 ou S/N" fluid :disabled="disabled"
                     @update:model-value="patch(kind, { number: String($event ?? '') })" />
        </label>
        <label class="c5">Complemento
          <InputText :model-value="model[kind]?.complement ?? ''" placeholder="Apto, bloco, fundos…" fluid :disabled="disabled"
                     @update:model-value="patch(kind, { complement: String($event ?? '') })" />
        </label>
        <label class="c4">Bairro
          <InputText :model-value="model[kind]?.district ?? ''" placeholder="Bairro" fluid :disabled="disabled"
                     @update:model-value="patch(kind, { district: String($event ?? '') })" />
        </label>
        <label class="c3">Cidade / UF
          <span class="city">
            <InputText :model-value="model[kind]?.city ?? ''" placeholder="Preenchida pelo CEP" fluid :disabled="disabled"
                       @update:model-value="patch(kind, { city: String($event ?? '') })" />
            <InputText :model-value="model[kind]?.state ?? ''" maxlength="2" placeholder="UF" class="uf" :disabled="disabled" aria-label="UF"
                       @update:model-value="patch(kind, { state: String($event ?? '').toUpperCase() })" />
          </span>
        </label>
        <label v-if="kind === 'delivery'" class="c6">Quem recebe
          <InputText :model-value="model.delivery?.recipient ?? ''" placeholder="Vazio = o próprio cliente" fluid :disabled="disabled"
                     @update:model-value="patch('delivery', { recipient: String($event ?? '') })" />
        </label>
        <label :class="kind === 'delivery' ? 'c6' : 'c12'">Ponto de referência
          <InputText :model-value="model[kind]?.reference ?? ''" placeholder="Portão azul, ao lado da padaria…" fluid :disabled="disabled"
                     @update:model-value="patch(kind, { reference: String($event ?? '') })" />
        </label>
      </div>
      <small v-if="notes[kind]" class="note"><i class="pi pi-map-marker" /> {{ notes[kind] }}</small>
    </section>
    <label class="same">
      <Checkbox :model-value="model.billing_same_as_delivery" binary :disabled="disabled" input-id="oa-same"
                @update:model-value="setSame(Boolean($event))" />
      <span>Cobrança no mesmo endereço da entrega</span>
    </label>
  </div>
</template>

<style scoped>
.oa { display: flex; flex-direction: column; gap: 12px; }
.oa__box { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--surface-card); }
.oa__box h4 { margin: 0 0 10px; display: flex; align-items: center; gap: 8px; font: 700 14px var(--font-sans); color: var(--text-strong); }
.oa__box h4 i { color: var(--text-brand); }
.tag { font: 600 11px var(--font-sans); color: var(--text-muted); background: var(--surface-sunken); border-radius: 999px; padding: 2px 8px; }
.oa__grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 8px 10px; }
.oa__grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-muted); min-width: 0; }
.c2 { grid-column: span 2; } .c3 { grid-column: span 3; } .c4 { grid-column: span 4; } .c5 { grid-column: span 5; }
.c6 { grid-column: span 6; } .c7 { grid-column: span 7; } .c12 { grid-column: span 12; }
.city { display: flex; gap: 6px; }
.uf { width: 52px; flex-shrink: 0; text-transform: uppercase; }
.note { display: flex; gap: 6px; align-items: center; margin-top: 8px; color: var(--text-muted); font-size: 12px; }
.same { display: flex; align-items: center; gap: 8px; font-size: 13.5px; color: var(--text-body); cursor: pointer; }
@media (max-width: 720px) { .oa__grid > * { grid-column: span 12; } }
</style>
