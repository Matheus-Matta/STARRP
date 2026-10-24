<script setup lang="ts">
/**
 * Barra de ações em massa: aparece no lugar dos filtros quando há itens marcados,
 * na mesma cor do cabeçalho da tabela.
 *
 * À esquerda: escolher a ação (as que o backend libera para o cargo) + Executar.
 * À direita: "20 selecionados · Selecionar todos os 57 · Limpar".
 * Ação com parâmetro abre um diálogo com os campos; ação perigosa pede confirmação.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import Select from "primevue/select";
import { computed, ref } from "vue";

import { type BulkAction, type BulkTarget, bulkApi } from "@/api/bulk";
import type { ListParams } from "@/api/http";
import FormField from "@/components/resource/FormField.vue";
import { useNotify } from "@/composables/useNotify";
import type { ResourceDef } from "@/resources/types";

const props = defineProps<{
  resource: ResourceDef;
  count: number;
  total: number;
  all: boolean;
  target: (filters: ListParams) => BulkTarget;
  filters: ListParams;
}>();
const emit = defineEmits<{ selectAll: []; clear: []; done: [] }>();
const notify = useNotify();

const actions = useQuery({
  queryKey: computed(() => ["bulk-actions", props.resource.endpoint]),
  queryFn: () => bulkApi.actions(props.resource.endpoint),
  staleTime: 5 * 60_000,
});
const list = computed(() => actions.data.value ?? []);

const running = ref<string | null>(null);
const chosen = ref<string | null>(null);
const chosenAction = computed(() => list.value.find((a) => a.name === chosen.value) ?? null);
const dialog = ref<BulkAction | null>(null);
const values = ref<Record<string, unknown>>({});
const errors = ref<Record<string, string>>({});
const plural = (n: number) => `${n.toLocaleString("pt-BR")} ${n === 1 ? "item" : "itens"}`;

function start(action: BulkAction) {
  if (action.params.length || action.danger) {
    values.value = {};
    errors.value = {};
    dialog.value = action;
    return;
  }
  void run(action);
}

async function run(action: BulkAction) {
  const missing = action.params.filter((p) => p.required && !hasValue(values.value[p.name]));
  if (missing.length) {
    errors.value = Object.fromEntries(missing.map((p) => [p.name, "Campo obrigatório."]));
    return;
  }
  running.value = action.name;
  const target = props.target(props.filters);
  try {
    if (action.name === "export") {
      // Rótulo e tradução ("simple" → "Simples") iguais aos da tela.
      const columns = props.resource.columns.map((c) => ({ key: c.key, label: c.label, map: c.map }));
      await bulkApi.download(props.resource.endpoint, target, { columns }, `${props.resource.name}.csv`);
      notify.success("Exportação pronta", `${plural(props.count)} no arquivo CSV.`);
    } else {
      const result = await bulkApi.run(props.resource.endpoint, action.name, target, values.value);
      report(action, result);
      emit("done");
    }
    dialog.value = null;
    chosen.value = null;
  } catch (error) {
    notify.error(error, `Não foi possível: ${action.label.toLowerCase()}`);
  } finally {
    running.value = null;
  }
}

function report(action: BulkAction, result: { affected: number; skipped: { label: string; reason: string }[] }) {
  if (result.affected) notify.success(action.label, `${plural(result.affected)} concluído(s).`);
  if (result.skipped.length) {
    const first = result.skipped.slice(0, 3).map((s) => `${s.label}: ${s.reason}`).join(" · ");
    notify.warn(`${plural(result.skipped.length)} não ${result.skipped.length === 1 ? "pôde" : "puderam"}`, first);
  }
  if (!result.affected && !result.skipped.length) notify.success(action.label, "Nada a mudar: já estavam assim.");
}

const hasValue = (v: unknown) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length);
</script>

<template>
  <div class="bulk" role="toolbar" aria-label="Ações em massa">
    <div class="bulk__actions">
      <Select v-model="chosen" :options="list" option-label="label" option-value="name" size="small" class="bulk__select" scroll-height="22rem"
              :placeholder="actions.isPending.value ? 'Carregando ações…' : 'Escolha uma ação'" :loading="actions.isPending.value"
              aria-label="Ação em massa">
        <template #option="{ option }">
          <span class="option" :class="{ 'option--danger': option.danger }"><i :class="option.icon" /> {{ option.label }}</span>
        </template>
        <template #value="{ value, placeholder }">
          <span v-if="chosenAction && value" class="option" :class="{ 'option--danger': chosenAction.danger }">
            <i :class="chosenAction.icon" /> {{ chosenAction.label }}
          </span>
          <span v-else>{{ placeholder }}</span>
        </template>
      </Select>
      <Button label="Executar" icon="pi pi-play" size="small" :severity="chosenAction?.danger ? 'danger' : 'contrast'"
              :disabled="!chosenAction || running !== null" :loading="running !== null"
              @click="chosenAction && start(chosenAction)" />
    </div>
    <div class="bulk__count">
      <strong>{{ all ? `Todos os ${plural(total)}` : `${plural(count)} selecionado(s)` }}</strong>
      <button v-if="!all && total > count" type="button" class="link" @click="emit('selectAll')">
        Selecionar todos os {{ total.toLocaleString("pt-BR") }}
      </button>
      <button type="button" class="link link--muted" @click="emit('clear')">Limpar</button>
    </div>

    <Dialog :visible="dialog !== null" modal :header="dialog?.label" :style="{ width: 'min(460px, calc(100vw - 24px))' }"
            @update:visible="dialog = null">
      <p class="dialog__text">
        {{ dialog?.confirm || `Aplicar em ${all ? `todos os ${plural(total)}` : plural(count)}?` }}
      </p>
      <div v-if="dialog?.params.length" class="grid-form">
        <FormField v-for="field in dialog.params" :key="field.name" v-model="values[field.name]"
                   :field="{ ...field, full: true }" :error="errors[field.name]" />
      </div>
      <template #footer>
        <Button label="Cancelar" severity="secondary" text @click="dialog = null" />
        <Button :label="dialog?.danger ? 'Sim, aplicar' : 'Aplicar'" :severity="dialog?.danger ? 'danger' : undefined"
                :loading="running !== null" @click="dialog && run(dialog)" />
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
/* Mesma cor do cabeçalho da tabela (neutra), sem destaque de marca. */
.bulk {
  display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; min-height: 52px; padding: 8px 12px;
  background: var(--surface-sunken); border-bottom: 1px solid var(--border);
}
.bulk__actions { display: flex; align-items: center; gap: 0.5rem; }
.bulk__select { width: 240px; }
.bulk__count { margin-left: auto; display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; font-size: 13px; color: var(--text-strong); }
.link { border: 0; padding: 0; background: transparent; cursor: pointer; font: 600 13px/1.4 var(--font-sans); color: var(--text-strong); text-decoration: underline; text-underline-offset: 3px; text-decoration-color: var(--border-strong); }
.link:hover { text-decoration-color: currentColor; }
.link--muted { color: var(--text-muted); font-weight: 500; text-decoration: none; }
.link--muted:hover { color: var(--text-strong); }
.option { display: inline-flex; align-items: center; gap: 0.5rem; }
.option i { font-size: 13px; color: var(--text-muted); }
.option--danger, .option--danger i { color: var(--danger-text); }
.dialog__text { margin-bottom: 0.75rem; color: var(--text-body); }
@media (max-width: 760px) {
  .bulk__actions { width: 100%; }
  .bulk__select { flex: 1; width: auto; min-width: 0; }
  .bulk__count { margin-left: 0; }
}
</style>
