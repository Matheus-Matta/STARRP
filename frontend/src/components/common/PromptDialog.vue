<script setup lang="ts">
/**
 * Pergunta rápida com um campo (motivo, código de cupom, valor de desconto).
 * Com `options`, o motivo é um toque num dos botões fixos (padroniza o relatório e
 * evita "asdf" no motivo); "Outro motivo" abre o campo para escrever.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import SelectButton from "primevue/selectbutton";
import { computed, nextTick, ref, watch } from "vue";

export type PromptSpec = {
  title: string;
  label: string;
  kind: "text" | "discount";
  confirmLabel?: string;
  required?: boolean;
  /** Motivos fixos (botões). */
  options?: string[];
  /** Ação destrutiva (cancelar, remover): botão de confirmar em vermelho. */
  danger?: boolean;
};
export type PromptAnswer = { text?: string; amount?: string; percent?: string };

const OTHER = "__other__";
const props = defineProps<{ spec: PromptSpec | null }>();
const emit = defineEmits<{ answer: [value: PromptAnswer | null] }>();

const text = ref("");
const choice = ref<string | null>(null);
const number = ref<number | null>(null);
const unit = ref<"percent" | "amount">("percent");
const error = ref("");

const presets = computed(() => props.spec?.options ?? []);
const typing = computed(() => !presets.value.length || choice.value === OTHER);

watch(() => props.spec, () => {
  text.value = "";
  choice.value = null;
  number.value = null;
  error.value = "";
});

function pick(option: string) {
  choice.value = option;
  error.value = "";
  if (option === OTHER) void nextTick(() => document.getElementById("prompt-text")?.focus());
}

function confirm() {
  if (props.spec?.kind === "discount") {
    if (number.value === null) return;
    emit("answer", unit.value === "percent" ? { percent: number.value.toFixed(2) } : { amount: number.value.toFixed(2) });
    return;
  }
  const value = typing.value ? text.value.trim() : (choice.value ?? "");
  if (presets.value.length && !choice.value) {
    error.value = "Escolha um motivo.";
    return;
  }
  if ((props.spec?.required || choice.value === OTHER) && !value) {
    error.value = "Escreva o motivo.";
    return;
  }
  emit("answer", { text: value });
}
</script>

<template>
  <Dialog :visible="spec !== null" modal :header="spec?.title" :style="{ width: presets.length ? '30rem' : '24rem' }"
          :breakpoints="{ '560px': '96vw' }" @update:visible="emit('answer', null)">
    <form class="form" @submit.prevent="confirm">
      <label>{{ spec?.label }}</label>
      <template v-if="spec?.kind === 'discount'">
        <SelectButton v-model="unit" :options="[{ label: '%', value: 'percent' }, { label: 'R$', value: 'amount' }]"
                      option-label="label" option-value="value" :allow-empty="false" />
        <InputNumber v-model="number" :min-fraction-digits="2" :max-fraction-digits="2" :suffix="unit === 'percent' ? ' %' : ''"
                     :prefix="unit === 'amount' ? 'R$ ' : ''" locale="pt-BR" autofocus fluid />
      </template>
      <template v-else>
        <div v-if="presets.length" class="presets" role="radiogroup">
          <button v-for="option in presets" :key="option" type="button" class="preset" role="radio"
                  :aria-checked="choice === option" :class="{ active: choice === option }" @click="pick(option)">
            <i :class="choice === option ? 'pi pi-check-circle' : 'pi pi-circle'" /> {{ option }}
          </button>
          <button type="button" class="preset" role="radio" :aria-checked="choice === OTHER"
                  :class="{ active: choice === OTHER }" @click="pick(OTHER)">
            <i class="pi pi-pencil" /> Outro motivo
          </button>
        </div>
        <InputText v-if="typing" id="prompt-text" v-model="text" :autofocus="!presets.length" fluid
                   :placeholder="presets.length ? 'Escreva o motivo' : undefined" :invalid="!!error" />
      </template>
      <small v-if="error" class="error"><i class="pi pi-exclamation-circle" /> {{ error }}</small>
      <div class="actions">
        <Button label="Voltar" severity="secondary" outlined @click="emit('answer', null)" />
        <Button type="submit" :label="spec?.confirmLabel ?? 'Confirmar'" :severity="spec?.danger ? 'danger' : undefined" />
      </div>
    </form>
  </Dialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 0.75rem; }
.actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
.presets { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.preset {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px; text-align: left; cursor: pointer;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); color: var(--text-body);
  font: 600 13px/1.25 var(--font-sans); transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease;
}
.preset i { color: var(--text-muted); font-size: 14px; }
.preset:hover { border-color: var(--brand-border); background: var(--surface-hover); }
.preset.active { border-color: var(--brand); background: var(--brand-subtle); color: var(--text-brand); }
.preset.active i { color: var(--brand); }
.error { color: var(--danger-text); display: flex; gap: 6px; align-items: center; font-weight: 600; }
@media (max-width: 560px) { .presets { grid-template-columns: 1fr; } }
</style>
