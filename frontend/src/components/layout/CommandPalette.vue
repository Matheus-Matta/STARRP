<script setup lang="ts">
/**
 * Busca rápida (Ctrl+K): vai para qualquer tela, cria um cadastro ou abre um
 * produto/cliente sem passar pelo menu. Setas escolhem, Enter abre, Esc fecha.
 *
 * Ex.: "nov prod" → "Novo produto"; "7891000" → o produto com esse código.
 */
import Dialog from "primevue/dialog";
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { resourceApi } from "@/api/resource";
import { usePrefetch } from "@/composables/usePrefetch";
import { findResource, resources } from "@/resources";
import { newLabel } from "@/resources/types";
import { useSession } from "@/stores/session";

import { buildNavigation } from "./navigation";

type Hit = { key: string; group: string; label: string; hint?: string; icon: string; to: string };

const open = defineModel<boolean>("open", { default: false });
const router = useRouter();
const session = useSession();
const prefetch = usePrefetch();
const term = ref("");
const active = ref(0);
const records = ref<Hit[]>([]);
const searching = ref(false);
const input = ref<HTMLInputElement>();
let timer: ReturnType<typeof setTimeout> | undefined;
let ticket = 0;

const normalize = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
/** Todas as palavras digitadas precisam aparecer ("nov prod" acha "Novo produto"). */
const matches = (text: string, query: string) => normalize(query).split(/\s+/).filter(Boolean)
  .every((word) => normalize(text).includes(word));

const screens = computed<Hit[]>(() => buildNavigation(session.can, session.hasModule).flatMap((group) =>
  group.items.map((item) => ({ key: item.to, group: "Ir para", label: item.label, hint: group.label, icon: item.icon, to: item.to }))));

const actions = computed<Hit[]>(() => resources
  .filter((r) => !r.readOnly && r.creatable !== false && session.can(`${r.permission}.manage`) && session.hasModule(r.module))
  .map((r) => ({ key: `new-${r.name}`, group: "Criar", label: newLabel(r), icon: "pi pi-plus", to: `/cadastros/${r.name}/novo` })));

const hits = computed<Hit[]>(() => {
  const query = term.value.trim();
  if (!query) return screens.value.slice(0, 8);
  const local = [...screens.value, ...actions.value].filter((hit) => matches(`${hit.label} ${hit.hint ?? ""}`, query));
  return [...local.slice(0, 8), ...records.value];
});

const groups = computed(() => {
  const map = new Map<string, Hit[]>();
  hits.value.forEach((hit) => map.set(hit.group, [...(map.get(hit.group) ?? []), hit]));
  return [...map.entries()];
});

/** Registros vêm do servidor (debounce curto); a resposta velha é descartada. */
const SOURCES = [
  { resource: "produtos", group: "Produtos", icon: "pi pi-box", hint: (r: Record<string, unknown>) => String(r.sku ?? "") },
  { resource: "clientes", group: "Clientes", icon: "pi pi-user", hint: (r: Record<string, unknown>) => String(r.document ?? r.phone ?? "") },
];

async function searchRecords(query: string) {
  const mine = ++ticket;
  const usable = SOURCES.map((s) => ({ ...s, def: findResource(s.resource) }))
    .filter((s) => s.def && session.can(`${s.def.permission}.view`));
  if (query.length < 2 || !usable.length) {
    records.value = [];
    return;
  }
  searching.value = true;
  try {
    const pages = await Promise.all(usable.map((s) => resourceApi.list(s.def!.endpoint, { search: query, page_size: 5 })
      .catch(() => ({ results: [] as Record<string, unknown>[] }))));
    if (mine !== ticket) return;
    records.value = pages.flatMap((page, index) => page.results.map((row) => ({
      key: `${usable[index]!.resource}-${row.id}`, group: usable[index]!.group, label: String(row.name ?? row.id),
      hint: usable[index]!.hint(row), icon: usable[index]!.icon, to: `/cadastros/${usable[index]!.resource}/${row.id}`,
    })));
  } finally {
    if (mine === ticket) searching.value = false;
  }
}

watch(term, (value) => {
  active.value = 0;
  clearTimeout(timer);
  timer = setTimeout(() => searchRecords(value.trim()), 200);
});

watch(open, async (isOpen) => {
  if (!isOpen) return;
  term.value = "";
  records.value = [];
  active.value = 0;
  await nextTick();
  input.value?.focus();
});

function go(hit?: Hit) {
  if (!hit) return;
  open.value = false;
  router.push(hit.to);
}

function warm(hit: Hit) {
  const match = hit.to.match(/^\/cadastros\/([^/]+)\/([^/]+)$/);
  const def = match ? findResource(match[1]!) : undefined;
  if (def && match![2] !== "novo") prefetch.detail(def, match![2]!);
  else prefetch.route(hit.to);
}

function onKey(event: KeyboardEvent) {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const size = hits.value.length;
    if (!size) return;
    active.value = (active.value + (event.key === "ArrowDown" ? 1 : -1) + size) % size;
    warm(hits.value[active.value]!);
    document.querySelector(`[data-hit="${active.value}"]`)?.scrollIntoView({ block: "nearest" });
  } else if (event.key === "Enter") {
    event.preventDefault();
    go(hits.value[active.value]);
  }
}

const indexOf = (hit: Hit) => hits.value.indexOf(hit);
</script>

<template>
  <Dialog v-model:visible="open" modal :show-header="false" position="top" :dismissable-mask="true"
          class="palette" :pt="{ content: { class: 'palette__content' } }">
    <div class="palette__input">
      <i :class="searching ? 'pi pi-spin pi-spinner' : 'pi pi-search'" />
      <input ref="input" v-model="term" placeholder="Buscar telas, ações, produtos, clientes…" aria-label="Buscar"
             @keydown="onKey" />
      <kbd>Esc</kbd>
    </div>
    <div class="palette__results">
      <p v-if="!hits.length && !searching" class="palette__empty">Nada encontrado para “{{ term }}”.</p>
      <div v-for="[group, items] in groups" :key="group" class="palette__group">
        <h3>{{ group }}</h3>
        <button v-for="hit in items" :key="hit.key" type="button" class="palette__hit" :data-hit="indexOf(hit)"
                :class="{ active: indexOf(hit) === active }" @mouseenter="active = indexOf(hit); warm(hit)" @click="go(hit)">
          <i :class="hit.icon" />
          <span class="palette__label">{{ hit.label }}</span>
          <small v-if="hit.hint">{{ hit.hint }}</small>
          <i class="pi pi-arrow-right palette__go" />
        </button>
      </div>
    </div>
    <footer class="palette__footer">
      <span><kbd>↑</kbd><kbd>↓</kbd> escolher</span><span><kbd>Enter</kbd> abrir</span><span><kbd>Ctrl K</kbd> abre de qualquer tela</span>
    </footer>
  </Dialog>
</template>

<style scoped>
.palette__input { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--border); }
.palette__input i { color: var(--text-muted); }
.palette__input input { flex: 1; border: 0; outline: 0; background: transparent; font: 500 15px/1.4 var(--font-sans); color: var(--text-strong); }
.palette__input input::placeholder { color: var(--text-subtle); }
kbd { font: 600 10.5px/1 var(--font-mono); padding: 3px 5px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-muted); background: var(--surface-sunken); }
.palette__results { max-height: min(60vh, 440px); overflow-y: auto; padding: 6px; }
.palette__empty { padding: 24px; text-align: center; color: var(--text-muted); }
.palette__group h3 { margin: 8px 8px 4px; font: 700 10.5px/1 var(--font-sans); letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-subtle); }
.palette__hit {
  width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 0; border-radius: 7px; cursor: pointer;
  background: transparent; color: var(--text-body); font: 500 13.5px/1.2 var(--font-sans); text-align: left;
}
.palette__hit > i:first-child { width: 16px; text-align: center; color: var(--text-muted); }
.palette__label { flex: 0 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.palette__hit small { color: var(--text-subtle); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.palette__go { margin-left: auto; font-size: 11px; opacity: 0; color: var(--brand); }
.palette__hit.active { background: var(--brand-subtle); color: var(--text-strong); }
.palette__hit.active > i:first-child, .palette__hit.active .palette__go { color: var(--brand); opacity: 1; }
.palette__footer { display: flex; gap: 16px; padding: 8px 14px; border-top: 1px solid var(--border); font-size: 11.5px; color: var(--text-muted); }
.palette__footer kbd { margin-right: 3px; }
@media (max-width: 640px) { .palette__footer { display: none; } }
</style>

<style>
.palette { width: min(620px, calc(100vw - 24px)); margin-top: 10vh; overflow: hidden; }
.palette .palette__content { padding: 0; }
</style>
