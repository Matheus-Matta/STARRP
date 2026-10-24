<script setup lang="ts">
/**
 * Seleção de registro relacionado (FK ou N:N) com busca no servidor.
 *
 * Carrega a primeira página de opções e, ao digitar, pede ao backend com
 * `search=`. As opções já escolhidas ficam guardadas para o rótulo não sumir
 * quando a busca não as traz.
 *
 * `creatable`: digitou "Bebidas" e não existe? Aparece "Criar “Bebidas”" no fim
 * da lista e o cadastro nasce ali mesmo, já selecionado (sem sair do formulário).
 */
import Button from "primevue/button";
import MultiSelect from "primevue/multiselect";
import Select from "primevue/select";
import { computed, onMounted, ref, watch } from "vue";

import { resourceApi, type Row } from "@/api/resource";
import { useNotify } from "@/composables/useNotify";
import type { Relation } from "@/resources/types";

const props = defineProps<{
  relation: Relation; multiple?: boolean; invalid?: boolean; placeholder?: string; creatable?: boolean; inputId?: string; disabled?: boolean;
  /** "small" = filtro de lista (largura própria); sem ele ocupa a coluna do formulário. */
  size?: "small";
}>();
const model = defineModel<unknown>();
const notify = useNotify();

const labelKey = computed(() => props.relation.labelKey ?? "name");
const valueKey = computed(() => props.relation.valueKey ?? "id");
const known = ref(new Map<unknown, Row>());
const loading = ref(false);
const creating = ref(false);
const found = ref<Row[]>([]);
const term = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;

const options = computed(() => {
  const merged = new Map(found.value.map((row) => [row[valueKey.value], row]));
  for (const [key, row] of known.value) if (!merged.has(key)) merged.set(key, row);
  return [...merged.values()];
});
const canCreate = computed(() => {
  const text = term.value.trim().toLocaleLowerCase("pt-BR");
  return props.creatable && text.length > 0 && !loading.value
    && !options.value.some((row) => String(row[labelKey.value]).toLocaleLowerCase("pt-BR") === text);
});

async function search(text = "") {
  loading.value = true;
  try {
    const page = await resourceApi.list(props.relation.endpoint, { ...props.relation.params, search: text, page_size: 50 });
    found.value = page.results;
  } finally {
    loading.value = false;
  }
}

/** Garante o rótulo do valor atual (edição de um registro já salvo). */
async function ensureKnown() {
  const values = props.multiple ? ((model.value as unknown[]) ?? []) : [model.value];
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    if (options.value.some((row) => row[valueKey.value] === value)) continue;
    if (valueKey.value !== "id") continue; // por código não há detalhe: vem na busca
    const row = await resourceApi.get(props.relation.endpoint, String(value)).catch(() => null);
    if (row) known.value.set(value, row);
  }
}

function onFilter(event: { value: string }) {
  term.value = event.value;
  clearTimeout(timer);
  timer = setTimeout(() => search(event.value), 250);
}

async function create() {
  const name = term.value.trim();
  creating.value = true;
  try {
    const row = await resourceApi.create(props.relation.endpoint, { ...props.relation.params, [labelKey.value]: name });
    known.value.set(row[valueKey.value], row);
    const value = row[valueKey.value];
    model.value = props.multiple ? [...((model.value as unknown[]) ?? []), value] : value;
    notify.success(`“${name}” criado`);
    term.value = "";
  } catch (error) {
    notify.error(error, "Não foi possível criar");
  } finally {
    creating.value = false;
  }
}

watch(found, (rows) => rows.forEach((row) => known.value.set(row[valueKey.value], row)));
watch(model, ensureKnown);
onMounted(async () => {
  await search();
  await ensureKnown();
});
</script>

<template>
  <MultiSelect
    v-if="multiple" v-model="model" :options="options" :option-label="labelKey" :option-value="valueKey" :input-id="inputId"
    :loading="loading" :invalid="invalid" filter display="chip" :placeholder="placeholder ?? 'Selecione'"
    :max-selected-labels="4" selected-items-label="{0} selecionados" :size="size" :fluid="!size" :disabled="disabled"
    @filter="onFilter"
  >
    <template v-if="creatable" #footer>
      <div v-if="canCreate" class="create">
        <Button :label="`Criar “${term.trim()}”`" icon="pi pi-plus" text size="small" :loading="creating" @click="create" />
      </div>
    </template>
  </MultiSelect>
  <Select
    v-else v-model="model" :options="options" :option-label="labelKey" :option-value="valueKey" :input-id="inputId"
    :loading="loading" :invalid="invalid" filter show-clear :placeholder="placeholder ?? 'Selecione'"
    :size="size" :fluid="!size" :disabled="disabled" @filter="onFilter"
  >
    <template v-if="creatable" #footer>
      <div v-if="canCreate" class="create">
        <Button :label="`Criar “${term.trim()}”`" icon="pi pi-plus" text size="small" :loading="creating" @click="create" />
      </div>
    </template>
  </Select>
</template>

<style scoped>
.create { padding: 4px 6px 6px; border-top: 1px solid var(--border-subtle); }
.create :deep(.p-button) { width: 100%; justify-content: flex-start; }
</style>
