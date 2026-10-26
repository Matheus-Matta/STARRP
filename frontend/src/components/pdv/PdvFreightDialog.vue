<script setup lang="ts">
/**
 * Conferir frete (Shift+F5), como a consulta de preço: o cliente pergunta "quanto fica para
 * entregar?" antes de comprar. Por CEP ou pelo endereço completo — aí o CEP sai da ViaCEP
 * (para as tabelas por faixa) e a coordenada do OpenStreetMap (as por distância medem até o
 * endereço exato). Só consulta: lançar a entrega na venda é em Entrega (F11).
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputMask from "primevue/inputmask";
import InputText from "primevue/inputtext";
import SelectButton from "primevue/selectbutton";
import { nextTick, ref, watch } from "vue";

import { http } from "@/api/http";
import { toApiError } from "@/api/errors";
import { money } from "@/utils/format";
import { applyMask, MASKS } from "@/utils/masks";

type Quote = { table: string; table_name: string; value: string | null; lead_days: number | null; detail: string;
               error: string };
type Estimate = { zip_code: string | null; address: Record<string, string> | null; point: [string, string] | null;
                  quotes: Quote[] };

const props = defineProps<{ visible: boolean }>();
const emit = defineEmits<{ close: [] }>();

const mode = ref<"zip" | "address">("zip");
const zip = ref("");
const address = ref({ street: "", number: "", district: "", city: "", state: "" });
const loading = ref(false);
const error = ref("");
const result = ref<Estimate | null>(null);

watch(() => props.visible, async (open) => {
  if (!open) return;
  result.value = null;
  error.value = "";
  await nextTick();
  document.getElementById(mode.value === "zip" ? "pdv-freight-zip" : "pdv-freight-street")?.focus();
});

async function check() {
  error.value = "";
  const params = mode.value === "zip" ? { zip: zip.value } : address.value;
  if (mode.value === "zip" && zip.value.length !== 8) {
    error.value = "Digite o CEP com 8 dígitos.";
    return;
  }
  if (mode.value === "address" && (!address.value.street || !address.value.city || address.value.state.length !== 2)) {
    error.value = "Informe logradouro, cidade e UF (o número ajuda a medir a distância exata).";
    return;
  }
  loading.value = true;
  try {
    result.value = (await http.get<Estimate>("/logistics/freight-tables/estimate/", { params })).data;
  } catch (failure) {
    result.value = null;
    error.value = toApiError(failure).message;
  } finally {
    loading.value = false;
  }
}

const place = (a: Record<string, string>) =>
  [a.street, a.district, [a.city, a.state].filter(Boolean).join(" - ")].filter(Boolean).join(" · ");
</script>

<template>
  <Dialog :visible="visible" modal header="Conferir frete" :style="{ width: 'min(640px, calc(100vw - 24px))' }"
          @update:visible="emit('close')">
    <form class="freight" @submit.prevent="check">
      <SelectButton v-model="mode" :options="[{ label: 'Por CEP', value: 'zip' }, { label: 'Endereço completo', value: 'address' }]"
                    option-label="label" option-value="value" :allow-empty="false" />
      <div v-if="mode === 'zip'" class="row">
        <InputMask id="pdv-freight-zip" v-model="zip" :mask="MASKS.cep" unmask :auto-clear="false" placeholder="00000-000"
                   class="zip" />
        <Button type="submit" label="Calcular" icon="pi pi-calculator" :loading="loading" />
      </div>
      <div v-else class="grid">
        <label class="c8">Logradouro<InputText id="pdv-freight-street" v-model="address.street" placeholder="Av. Paulista" fluid /></label>
        <label class="c4">Número<InputText v-model="address.number" placeholder="1578" fluid /></label>
        <label class="c5">Bairro<InputText v-model="address.district" fluid /></label>
        <label class="c5">Cidade<InputText v-model="address.city" fluid /></label>
        <label class="c2">UF<InputText v-model="address.state" maxlength="2" fluid
                                        @update:model-value="address.state = String($event ?? '').toUpperCase()" /></label>
        <Button type="submit" label="Calcular" icon="pi pi-calculator" :loading="loading" class="c12" />
      </div>
      <p v-if="error" class="error"><i class="pi pi-exclamation-circle" /> {{ error }}</p>

      <div v-if="result" class="result">
        <p class="found">
          <i class="pi pi-map-marker" />
          <span v-if="result.address">{{ place(result.address) }} · CEP {{ applyMask(result.zip_code, MASKS.cep) }}</span>
          <span v-else-if="result.zip_code">CEP {{ applyMask(result.zip_code, MASKS.cep) }}</span>
          <span v-else>CEP não encontrado (as tabelas por faixa não atendem)</span>
          <small v-if="result.point" class="exact">distância até o endereço exato</small>
        </p>
        <ul class="quotes">
          <li v-for="q in result.quotes" :key="q.table" :class="{ off: q.value === null }">
            <span class="quotes__name"><i class="pi pi-truck" /> {{ q.table_name }}</span>
            <template v-if="q.value !== null">
              <strong>{{ Number(q.value) ? money(q.value) : "Grátis" }}</strong>
              <small>{{ q.lead_days === 0 ? "no mesmo dia" : `${q.lead_days} dia(s) útil(eis)` }}<template v-if="q.detail"> · {{ q.detail }}</template></small>
            </template>
            <small v-else class="why">{{ q.error }}</small>
          </li>
          <li v-if="!result.quotes.length" class="off">Nenhuma tabela de frete ativa.</li>
        </ul>
        <small class="hint">Para cobrar na venda, vincule o cliente e use Entrega (F11).</small>
      </div>
    </form>
  </Dialog>
</template>

<style scoped>
.freight { display: flex; flex-direction: column; gap: 12px; }
.row { display: flex; gap: 8px; }
.zip { flex: 1; font-size: 18px; }
.grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 8px 10px; }
.grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.c2 { grid-column: span 2; } .c4 { grid-column: span 4; } .c5 { grid-column: span 5; } .c8 { grid-column: span 8; }
.c12 { grid-column: span 12; justify-content: center; }
.error { margin: 0; color: var(--danger-text); font-size: 13px; font-weight: 600; display: flex; gap: 6px; align-items: center; }
.result { display: flex; flex-direction: column; gap: 8px; }
.found { margin: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; color: var(--text-strong); }
.found i { color: var(--brand); }
.exact { color: var(--text-muted); }
.quotes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.quotes li { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 10px 12px; border-radius: 10px;
             border: 1px solid var(--border); background: var(--surface-card); }
.quotes li.off { opacity: 0.6; border-style: dashed; }
.quotes__name { font-weight: 700; color: var(--text-strong); display: flex; gap: 6px; align-items: center; }
.quotes__name i { color: var(--brand); }
.quotes strong { font: 800 18px/1.1 var(--font-sans); color: var(--text-strong); text-align: right; }
.quotes small { grid-column: 1 / -1; color: var(--text-muted); font-size: 12px; }
.why { color: var(--text-muted); }
.hint { color: var(--text-muted); font-size: 12px; }
@media (max-width: 560px) { .grid > * { grid-column: span 12; } }
</style>
