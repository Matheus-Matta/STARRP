<script setup lang="ts">
/**
 * Campo de tags no estilo Tagify: digite e tecle Enter, vírgula ou Tab para virar
 * etiqueta; Backspace no vazio apaga a última; colar "a, b, c" cria as três.
 * Sugere o que já existe (do servidor ou de uma lista fixa) sem obrigar a escolher.
 *
 * "verão" e "Verão" são a mesma tag: a repetida não entra.
 */
import { computed, onMounted, ref } from "vue";

import { resourceApi } from "@/api/resource";

const props = defineProps<{
  suggestions?: string[];
  /** Busca sugestões no servidor: { endpoint: "/tags/", params: { scope: "product" } }. */
  source?: { endpoint: string; params?: Record<string, string>; labelKey?: string };
  placeholder?: string;
  invalid?: boolean;
  inputId?: string;
  maxLength?: number;
  disabled?: boolean;
}>();
const model = defineModel<string[] | null>({ default: () => [] });

const draft = ref("");
const focused = ref(false);
const active = ref(-1);
const remote = ref<string[]>([]);
const input = ref<HTMLInputElement>();
let timer: ReturnType<typeof setTimeout> | undefined;

const tags = computed(() => model.value ?? []);
const key = (text: string) => text.trim().toLocaleLowerCase("pt-BR");
const taken = computed(() => new Set(tags.value.map(key)));

const options = computed(() => {
  const term = key(draft.value);
  const pool = [...new Set([...(props.suggestions ?? []), ...remote.value])];
  return pool.filter((s) => !taken.value.has(key(s)) && (!term || key(s).includes(term))).slice(0, 8);
});
const showList = computed(() => focused.value && options.value.length > 0);

function add(raw: string) {
  const parts = raw.split(/[,;\n]/).map((p) => p.trim().replace(/\s+/g, " ").slice(0, props.maxLength ?? 40)).filter(Boolean);
  const next = [...tags.value];
  for (const part of parts) {
    if (!next.some((t) => key(t) === key(part))) next.push(part);
  }
  model.value = next;
  draft.value = "";
  active.value = -1;
}

function remove(index: number) {
  model.value = tags.value.filter((_, i) => i !== index);
}

async function fetchRemote(term = "") {
  if (!props.source) return;
  const page = await resourceApi.list(props.source.endpoint, { ...props.source.params, search: term, page_size: 30 })
    .catch(() => ({ results: [] as Record<string, unknown>[] }));
  remote.value = page.results.map((row) => String(row[props.source!.labelKey ?? "name"]));
}

function onInput() {
  active.value = -1;
  clearTimeout(timer);
  timer = setTimeout(() => fetchRemote(draft.value.trim()), 200);
}

function onKey(event: KeyboardEvent) {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    if (!options.value.length) return;
    event.preventDefault();
    const size = options.value.length;
    active.value = (active.value + (event.key === "ArrowDown" ? 1 : -1) + size) % size;
  } else if (event.key === "Enter" || event.key === "," || (event.key === "Tab" && draft.value.trim())) {
    const picked = active.value >= 0 ? options.value[active.value] : draft.value;
    if (!picked?.trim()) return;
    event.preventDefault();
    add(picked);
  } else if (event.key === "Backspace" && !draft.value && tags.value.length) {
    remove(tags.value.length - 1);
  } else if (event.key === "Escape") {
    active.value = -1;
    focused.value = false;
  }
}

function onPaste(event: ClipboardEvent) {
  const text = event.clipboardData?.getData("text") ?? "";
  if (/[,;\n]/.test(text)) {
    event.preventDefault();
    add(text);
  }
}

function onBlur() {
  // Espera o clique na sugestão chegar antes de fechar a lista.
  setTimeout(() => {
    focused.value = false;
    if (draft.value.trim()) add(draft.value);
  }, 120);
}

onMounted(() => fetchRemote());
</script>

<template>
  <div class="tags" :class="{ 'tags--focus': focused, 'tags--invalid': invalid, 'tags--disabled': disabled }" @click="input?.focus()">
    <span v-for="(tag, index) in tags" :key="tag" class="tag">
      {{ tag }}
      <button v-if="!disabled" type="button" :aria-label="`Remover ${tag}`" @click.stop="remove(index)"><i class="pi pi-times" /></button>
    </span>
    <input :id="inputId" ref="input" v-model="draft" :placeholder="tags.length ? '' : (placeholder ?? 'Digite e tecle Enter')"
           :maxlength="maxLength ?? 40" :disabled="disabled" autocomplete="off" @input="onInput" @keydown="onKey" @paste="onPaste"
           @focus="focused = true" @blur="onBlur" />
    <ul v-if="showList" class="tags__list" role="listbox">
      <li v-for="(option, index) in options" :key="option" role="option" :aria-selected="index === active"
          :class="{ active: index === active }" @mousedown.prevent="add(option)">
        <i class="pi pi-tag" /> {{ option }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.tags {
  position: relative; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-height: var(--control-h); padding: 3px 6px;
  border: 1px solid var(--p-form-field-border-color, var(--border-strong)); border-radius: 7px;
  background: var(--p-form-field-background, var(--surface-card)); cursor: text;
  transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease;
}
.tags:hover { border-color: var(--brand-border); }
.tags--focus { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 22%, transparent); }
.tags--invalid { border-color: var(--danger); }
.tags--disabled { cursor: default; background: var(--p-form-field-disabled-background); }
.tags--disabled:hover { border-color: var(--p-form-field-border-color, var(--border-strong)); }
.tag {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 4px 2px 8px; border-radius: 5px;
  background: var(--brand-subtle); color: var(--text-brand); font: 600 12.5px/1.5 var(--font-sans);
  animation: pop var(--dur-base) var(--ease-spring);
}
.tag button { display: grid; place-items: center; width: 16px; height: 16px; border: 0; border-radius: 4px; padding: 0; cursor: pointer; background: transparent; color: inherit; opacity: 0.6; }
.tag button:hover { opacity: 1; background: var(--brand-subtle-2); }
.tag button i { font-size: 9px; }
input { flex: 1; min-width: 90px; border: 0; outline: 0; background: transparent; padding: 4px 2px; font: 400 13.5px/1.4 var(--font-sans); color: var(--text-strong); }
input::placeholder { color: var(--text-subtle); }
.tags__list {
  position: absolute; z-index: 40; top: calc(100% + 4px); left: 0; right: 0; margin: 0; padding: 4px; list-style: none;
  background: var(--surface-raised); border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow-lg);
}
.tags__list li { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 13px; color: var(--text-body); }
.tags__list li i { font-size: 11px; color: var(--text-subtle); }
.tags__list li:hover, .tags__list li.active { background: var(--brand-subtle); color: var(--text-strong); }
@keyframes pop { from { transform: scale(0.85); opacity: 0; } to { transform: none; opacity: 1; } }
</style>
