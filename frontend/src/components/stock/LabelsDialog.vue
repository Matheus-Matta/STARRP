<script setup lang="ts">
/**
 * Etiquetas da entrada (ou transferência), escolhendo o modelo. Depois de confirmar / aprovar
 * a entrada ou concluir a conferência, só aparece quando a regra de logística da filial diz
 * "Pergunta o modelo" ("Imprime sozinho" imprime direto, `utils/labels.autoPrintLabels`).
 * Já vem marcado o modelo da regra: lote (data de entrada e validade) quando a entrada gerou
 * lotes, senão produto. A página de impressão abre numa aba nova.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import { computed, ref, watch } from "vue";

import { stockApi } from "@/api/operations";
import { resourceApi } from "@/api/resource";
import type { FormActionContext } from "@/resources/types";
import { date as formatDate } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ close: [] }>();
const SUBJECT: Record<string, string> = { product: "Produto / gôndola", lot: "Lote (entrada e validade)", volume: "Caixa (volume)" };
const COUNT: Record<string, string> = { product: "uma por unidade", lot: "uma por lote", volume: "uma por caixa" };

const options = useQuery({ queryKey: ["label-options", props.ctx.id], queryFn: () => stockApi.labelOptions(props.ctx.id) });
const templates = useQuery({
  queryKey: ["label-templates"],
  queryFn: () => resourceApi.list("/stock/label-templates/", { is_active: true, page_size: 100 }),
});
/** Lote só aparece quando a entrada gerou lotes; endereço sai pelo cadastro de endereços. */
const ORDER: Record<string, number> = { lot: 0, product: 1, volume: 2 };
const usable = computed(() => (templates.data.value?.results ?? [])
  .filter((t) => t.subject !== "bin" && (t.subject !== "lot" || (options.data.value?.lots ?? 0) > 0))
  // O padrão sugerido primeiro; depois lote, produto e caixa.
  .sort((a, b) => Number(b.id === options.data.value?.suggested) - Number(a.id === options.data.value?.suggested)
    || (ORDER[String(a.subject)] ?? 9) - (ORDER[String(b.subject)] ?? 9)));
const chosen = ref<string | null>(null);
watch([() => options.data.value, usable], () => {
  if (chosen.value && usable.value.some((t) => t.id === chosen.value)) return;
  const suggested = options.data.value?.suggested;
  chosen.value = usable.value.find((t) => t.id === suggested)?.id as string ?? null;
}, { immediate: true });

function print() {
  if (!chosen.value) return;
  window.open(stockApi.labelsUrl(props.ctx.id, chosen.value), "_blank");
  emit("close");
}
</script>

<template>
  <div class="labels">
    <p v-if="options.data.value" class="muted">
      Entrada de <b>{{ formatDate(options.data.value.received_at) }}</b>: a data vai na etiqueta.
      <template v-if="options.data.value.lots">{{ options.data.value.lots }} lote(s) gerado(s); a saída tira do mais
        antigo primeiro.</template>
    </p>
    <p v-if="templates.isSuccess.value && !usable.length" class="muted">
      Nenhum modelo de etiqueta ativo. Cadastre em Estoque → Modelos de etiqueta.
    </p>
    <div class="options">
      <button v-for="t in usable" :key="String(t.id)" type="button" class="option" :class="{ active: chosen === t.id }"
              @click="chosen = String(t.id)">
        <strong>{{ t.name }} <span v-if="t.id === options.data.value?.suggested" class="tag">padrão</span></strong>
        <small>{{ SUBJECT[String(t.subject)] }} · {{ t.width_mm }}×{{ t.height_mm }} mm · {{ COUNT[String(t.subject)] }}</small>
      </button>
    </div>
    <div class="foot">
      <Button label="Agora não" severity="secondary" text @click="emit('close')" />
      <Button label="Imprimir" icon="pi pi-print" :disabled="!chosen" @click="print" />
    </div>
  </div>
</template>

<style scoped>
.labels > p { margin: 0 0 0.75rem; font-size: 13px; }
.options { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr)); gap: 0.5rem; }
.option {
  display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface-card); cursor: pointer; text-align: left; font-family: var(--font-sans);
}
.option:hover { border-color: var(--border-strong); }
.option.active { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-subtle-2); }
.option strong { color: var(--text-strong); font-size: 13.5px; }
.option small { color: var(--text-muted); font-size: 12px; }
.tag { margin-left: 4px; padding: 1px 6px; border-radius: 6px; font-size: 11px; font-weight: 600; background: var(--brand-subtle);
       color: var(--text-brand); }
.foot { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem; }
</style>
