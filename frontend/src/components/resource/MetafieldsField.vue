<script setup lang="ts">
/**
 * Metacampos do registro (padrão do StarHub), em duas partes:
 *
 * 1. Campos personalizados — as DEFINIÇÕES da conta para este tipo de registro
 *    (Configurações → Campos personalizados): "Tempo de montagem (h)", "Garantia",
 *    "Material"... com o tipo certo (número, sim/não, lista, data). No produto só
 *    entram as da categoria dele (e das de cima). São a ficha técnica do PDV.
 * 2. Outros metacampos — chave/valor livre (integração, anotação), como no StarHub.
 *
 * O valor é um objeto {chave: valor}; chaves com "_" no começo são do sistema
 * (ex.: `_entrega` no pedido): ficam guardadas, mas não aparecem aqui.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import DatePicker from "primevue/datepicker";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";
import { computed, ref, watch } from "vue";

import { resourceApi } from "@/api/resource";

type Definition = {
  id: string; key: string; name: string; type: "text" | "number" | "boolean" | "select" | "date"; unit: string;
  options: string[]; help_text: string; required: boolean; categories: string[]; show_in_specs: boolean;
};
type Category = { id: string; parent: string | null };

const props = defineProps<{ owner: "product" | "customer" | "sale"; context?: Record<string, unknown>; disabled?: boolean }>();
const model = defineModel<Record<string, unknown> | null>();
const values = computed(() => (model.value ?? {}) as Record<string, unknown>);

const defs = useQuery({
  queryKey: computed(() => ["metafield-definitions", props.owner]),
  queryFn: () => resourceApi.list<Definition>("/metafield-definitions/", { owner: props.owner, is_active: true, page_size: 200,
                                                                         ordering: "position" }),
  staleTime: 60_000,
});
const cats = useQuery({
  queryKey: ["metafield-categories"],
  queryFn: () => resourceApi.list<Category>("/catalog/categories/", { page_size: 500 }),
  enabled: computed(() => props.owner === "product"),
  staleTime: 5 * 60_000,
});

/** A categoria do produto e as de cima (a definição de "Móveis" vale para "Quarto"). */
const lineage = computed(() => {
  const all = cats.data.value?.results ?? [];
  const ids = new Set<string>();
  let current = all.find((c) => c.id === props.context?.category);
  for (let depth = 0; current && depth < 6; depth++) {
    ids.add(current.id);
    current = all.find((c) => c.id === current!.parent);
  }
  return ids;
});
const visible = computed(() => (defs.data.value?.results ?? []).filter((d) =>
  props.owner !== "product" || !d.categories?.length || d.categories.some((c) => lineage.value.has(c))));
const definedKeys = computed(() => new Set(visible.value.map((d) => d.key)));

function set(key: string, value: unknown) {
  const next = { ...values.value };
  if (value === null || value === undefined || value === "") delete next[key];
  else next[key] = value;
  model.value = next;
}

/* Campos livres: editados como lista (a ordem e a chave em edição não pulam). */
type Free = { key: string; value: string };
const free = ref<Free[]>([]);
const freeFromModel = () => Object.entries(values.value)
  .filter(([k]) => !k.startsWith("_") && !definedKeys.value.has(k))
  .map(([key, value]) => ({ key, value: typeof value === "object" ? JSON.stringify(value) : String(value) }));
// Só recarrega a lista quando o valor mudou DE FORA (abrir outro registro): a linha que está
// sendo digitada (chave sem valor ainda) não está no valor e não pode sumir.
watch([() => model.value, definedKeys], () => {
  const current = freeFromModel();
  const complete = free.value.filter((f) => slug(f.key) && f.value !== "");
  const same = current.length === complete.length
    && current.every((c) => complete.some((f) => slug(f.key) === c.key && f.value === c.value));
  if (!same) free.value = current;
}, { immediate: true });

function slug(text: string) {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim()
    .replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
}
function pushFree(rows: Free[]) {
  free.value = rows;
  const keep = Object.fromEntries(Object.entries(values.value).filter(([k]) => k.startsWith("_") || definedKeys.value.has(k)));
  for (const row of rows) {
    const key = slug(row.key);
    if (key && row.value !== "") keep[key] = row.value;
  }
  model.value = keep;
}
const editFree = (index: number, patch: Partial<Free>) => pushFree(free.value.map((f, i) => (i === index ? { ...f, ...patch } : f)));
const addFree = () => (free.value = [...free.value, { key: "", value: "" }]);
const removeFree = (index: number) => pushFree(free.value.filter((_, i) => i !== index));

const asDate = (v: unknown) => (v ? new Date(`${String(v).slice(0, 10)}T00:00:00`) : null);
const options = (d: Definition) => d.options.map((o) => ({ label: o, value: o }));
</script>

<template>
  <div class="meta">
    <div v-if="visible.length" class="meta__grid">
      <div v-for="d in visible" :key="d.id" class="mf" :class="{ 'mf--wide': d.type === 'text' }">
        <label :for="`mf-${d.key}`">{{ d.name }}<span v-if="d.unit" class="unit"> ({{ d.unit }})</span><span v-if="d.required" class="req">*</span>
          <i v-if="d.show_in_specs && owner === 'product'" class="pi pi-list-check spec" title="Aparece na ficha técnica" /></label>
        <div v-if="d.type === 'boolean'" class="switch">
          <ToggleSwitch :model-value="values[d.key] === true" :input-id="`mf-${d.key}`" :disabled="disabled"
                        @update:model-value="set(d.key, $event ? true : null)" />
          <span>{{ values[d.key] === true ? "Sim" : "Não" }}</span>
        </div>
        <InputNumber v-else-if="d.type === 'number'" :model-value="values[d.key] === undefined ? null : Number(values[d.key])"
                     :input-id="`mf-${d.key}`" :max-fraction-digits="3" locale="pt-BR" :suffix="d.unit ? ` ${d.unit}` : undefined"
                     fluid :disabled="disabled" @update:model-value="set(d.key, $event)" />
        <Select v-else-if="d.type === 'select'" :model-value="values[d.key] ?? null" :options="options(d)" option-label="label"
                option-value="value" :input-id="`mf-${d.key}`" show-clear placeholder="Escolha" fluid :disabled="disabled"
                @update:model-value="set(d.key, $event)" />
        <DatePicker v-else-if="d.type === 'date'" :model-value="asDate(values[d.key])" :input-id="`mf-${d.key}`" date-format="dd/mm/yy"
                    show-icon fluid :disabled="disabled"
                    @update:model-value="set(d.key, $event ? ($event as Date).toLocaleDateString('sv-SE') : null)" />
        <InputText v-else :id="`mf-${d.key}`" :model-value="String(values[d.key] ?? '')" fluid :disabled="disabled"
                   @update:model-value="set(d.key, $event)" />
        <small v-if="d.help_text" class="hint">{{ d.help_text }}</small>
      </div>
    </div>
    <p v-else-if="!defs.isPending.value" class="muted">
      Nenhum campo personalizado{{ owner === "product" ? " para esta categoria" : "" }}. Crie em
      <b>Configurações → Campos personalizados</b> (ex.: tempo de montagem, garantia).
    </p>

    <div class="free">
      <span class="free__title">Outros metacampos <small>chave e valor livres (integrações, anotações)</small></span>
      <div v-for="(f, i) in free" :key="i" class="free__row">
        <InputText :model-value="f.key" placeholder="chave" class="free__key" :disabled="disabled" aria-label="Chave"
                   @update:model-value="editFree(i, { key: String($event ?? '') })" />
        <InputText :model-value="f.value" placeholder="valor" fluid :disabled="disabled" aria-label="Valor"
                   @update:model-value="editFree(i, { value: String($event ?? '') })" />
        <Button icon="pi pi-trash" text rounded severity="danger" size="small" :disabled="disabled" aria-label="Remover metacampo"
                @click="removeFree(i)" />
      </div>
      <Button label="Adicionar metacampo" icon="pi pi-plus" severity="secondary" text size="small" class="free__add"
              :disabled="disabled" @click="addFree" />
    </div>
  </div>
</template>

<style scoped>
.meta { display: flex; flex-direction: column; gap: 16px; }
.meta__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr)); gap: 12px 14px; }
.mf { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.mf label { font-size: 13px; font-weight: 600; color: var(--text-strong); display: flex; gap: 4px; align-items: center; }
.unit { color: var(--text-muted); font-weight: 500; }
.req { color: var(--danger-text); }
.spec { margin-left: auto; font-size: 12px; color: var(--brand); }
.switch { display: flex; align-items: center; gap: 10px; height: var(--control-h); padding: 0 10px; border: 1px solid var(--border); border-radius: 7px; }
.hint { font-size: 12px; color: var(--text-muted); }
.muted { margin: 0; font-size: 13px; color: var(--text-muted); }
.free { display: flex; flex-direction: column; gap: 6px; padding-top: 12px; border-top: 1px dashed var(--border); }
.free__title { font-size: 13px; font-weight: 600; color: var(--text-strong); }
.free__title small { font-weight: 400; color: var(--text-muted); margin-left: 6px; }
.free__row { display: flex; gap: 8px; align-items: center; }
.free__key { width: 220px; flex-shrink: 0; font-family: var(--font-mono); font-size: 13px; }
.free__add { align-self: flex-start; }
</style>
