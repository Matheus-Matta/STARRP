<script setup lang="ts">
/**
 * Conferência por leitura: o conferente lê cada código (do produto ou da caixa)
 * e o sistema compara com o documento. Unidade em várias caixas só conta
 * quando TODAS as caixas foram lidas; as soltas aparecem para procurar.
 */
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import { nextTick, onMounted, ref } from "vue";

import { type Conference, stockApi } from "@/api/operations";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { quantity } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: [] }>();
/** Rascunho pode concluir: o contado vira a quantidade dos itens (entrada da NF-e exige isso para aprovar). */
const canFinish = props.ctx.values.status === "draft";
const finishing = ref(false);
const notify = useNotify();
const codes = ref<string[]>([]);
const code = ref("");
const result = ref<Conference | null>(null);
const checking = ref(false);
const input = ref<{ $el: HTMLInputElement }>();

async function check() {
  checking.value = true;
  try {
    result.value = await stockApi.conference(props.ctx.id, codes.value);
  } catch (error) {
    notify.error(error, "Não foi possível conferir");
  } finally {
    checking.value = false;
  }
}

async function add() {
  const value = code.value.trim();
  if (!value) return;
  codes.value = [...codes.value, value];
  code.value = "";
  await check();
  await nextTick();
  input.value?.$el.focus();
}

async function finish() {
  finishing.value = true;
  try {
    await stockApi.check(props.ctx.id, codes.value);
    notify.success(result.value?.ok ? "Conferência concluída: tudo confere" : "Conferência concluída com diferenças");
    emit("done");
  } catch (error) {
    notify.error(error, "Não foi possível concluir a conferência");
  } finally {
    finishing.value = false;
  }
}

function undo() {
  codes.value = codes.value.slice(0, -1);
  void check();
}

onMounted(() => {
  void check();
  input.value?.$el.focus();
});
</script>

<template>
  <div class="conference">
    <div class="scan">
      <InputText ref="input" v-model="code" placeholder="Leia o código e tecle Enter" fluid @keydown.enter.prevent="add" />
      <Button icon="pi pi-undo" label="Desfazer" severity="secondary" outlined size="small" :disabled="!codes.length" @click="undo" />
    </div>
    <p class="muted">{{ codes.length }} leitura(s)</p>
    <div v-if="result" class="status" :class="result.ok ? 'status--ok' : 'status--diff'">
      <i :class="result.ok ? 'pi pi-check-circle' : 'pi pi-exclamation-circle'" />
      {{ result.ok ? "Tudo confere com o documento." : "Há diferenças: confira abaixo." }}
    </div>
    <table v-if="result" class="list">
      <thead><tr><th>Produto</th><th class="right">Esperado</th><th class="right">Contado</th><th class="right">Diferença</th><th>Caixas</th></tr></thead>
      <tbody>
        <tr v-for="row in result.rows" :key="row.variant" :class="{ diff: Number(row.difference_quantity) !== 0 || row.loose_volumes.length }">
          <td><strong>{{ row.description }}</strong> <small class="muted">{{ row.sku }}</small>
            <span v-if="row.unexpected" class="pill pill--warning">fora do documento</span></td>
          <td class="right">{{ quantity(row.expected_quantity) }}</td>
          <td class="right"><strong>{{ quantity(row.counted_quantity) }}</strong></td>
          <td class="right">{{ Number(row.difference_quantity) > 0 ? "+" : "" }}{{ quantity(row.difference_quantity) }}</td>
          <td>
            <span v-if="row.loose_volumes.length" class="muted">soltas: {{ row.loose_volumes.join(", ") }}</span>
            <span v-if="row.missing_volumes.length" class="miss"> · falta: {{ row.missing_volumes.join(", ") }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="result?.unknown_codes.length" class="unknown"><i class="pi pi-question-circle" /> Não reconhecidos: {{ result.unknown_codes.join(", ") }}</p>
    <div v-if="canFinish" class="foot">
      <span class="muted">Ao concluir, o contado vira a quantidade de cada item.</span>
      <Button label="Concluir conferência" icon="pi pi-check" :loading="finishing" :disabled="!codes.length" @click="finish" />
    </div>
  </div>
</template>

<style scoped>
.scan { display: flex; gap: 0.5rem; }
.conference > p { margin: 0.4rem 0 0.6rem; font-size: 12.5px; }
.status { display: flex; align-items: center; gap: 0.5rem; padding: 8px 10px; border-radius: 8px; font-size: 13px; font-weight: 600; }
.status--ok { background: var(--success-subtle); color: var(--success-text); }
.status--diff { background: var(--warning-subtle); color: var(--warning-text); }
.list { width: 100%; border-collapse: collapse; margin-top: 0.75rem; font-size: 13.5px; }
.list th { text-align: left; padding: 8px; font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em;
           color: var(--text-muted); background: var(--surface-sunken); }
.list td { padding: 8px; border-top: 1px solid var(--border-subtle); }
.list tr.diff td { background: var(--warning-subtle); }
.right { text-align: right; }
.miss { color: var(--danger-text); }
.unknown { margin-top: 0.75rem; font-size: 13px; color: var(--danger-text); }
.foot { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-top: 1rem; font-size: 12.5px; }
</style>
