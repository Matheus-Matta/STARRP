<script setup lang="ts">
/**
 * Etiquetas do documento: escolhe o modelo (gôndola, lote ou caixa/volume) e
 * abre a página de impressão numa aba nova (o navegador imprime direto na térmica).
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import { computed, ref } from "vue";

import { stockApi } from "@/api/operations";
import { resourceApi } from "@/api/resource";
import type { FormActionContext } from "@/resources/types";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ close: [] }>();
const SUBJECT: Record<string, string> = { product: "Produto / gôndola", lot: "Lote (validade)", bin: "Endereço", volume: "Caixa (volume)" };

const templates = useQuery({
  queryKey: ["label-templates"],
  queryFn: () => resourceApi.list("/stock/label-templates/", { is_active: true, page_size: 100 }),
});
const usable = computed(() => (templates.data.value?.results ?? []).filter((t) => t.subject !== "bin"));
const chosen = ref<string | null>(null);

function print() {
  if (!chosen.value) return;
  window.open(stockApi.labelsUrl(props.ctx.id, chosen.value), "_blank");
  emit("close");
}
</script>

<template>
  <div class="labels">
    <p class="muted">Produto: uma por unidade. Lote: uma por lote gerado. Volume: uma por caixa de cada unidade.</p>
    <p v-if="templates.isSuccess.value && !usable.length" class="muted">
      Nenhum modelo de etiqueta. Cadastre em Estoque → Modelos de etiqueta.
    </p>
    <div class="options">
      <button v-for="t in usable" :key="String(t.id)" type="button" class="option" :class="{ active: chosen === t.id }"
              @click="chosen = String(t.id)">
        <strong>{{ t.name }}</strong>
        <small>{{ SUBJECT[String(t.subject)] }} · {{ t.width_mm }}×{{ t.height_mm }} mm</small>
      </button>
    </div>
    <div class="foot">
      <Button label="Imprimir" icon="pi pi-print" :disabled="!chosen" @click="print" />
    </div>
  </div>
</template>

<style scoped>
.labels > p { margin: 0 0 0.75rem; font-size: 13px; }
.options { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(200px, 100%), 1fr)); gap: 0.5rem; }
.option {
  display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface-card); cursor: pointer; text-align: left; font-family: var(--font-sans);
}
.option:hover { border-color: var(--border-strong); }
.option.active { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-subtle-2); }
.option strong { color: var(--text-strong); font-size: 13.5px; }
.option small { color: var(--text-muted); font-size: 12px; }
.foot { display: flex; justify-content: flex-end; margin-top: 1rem; }
</style>
