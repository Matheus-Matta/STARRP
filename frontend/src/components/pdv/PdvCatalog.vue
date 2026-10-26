<script setup lang="ts">
/**
 * Catálogo do PDV: busca (Tab), chips de categoria e a grade de produtos — 20 por
 * vez, carregando mais ao rolar. Clique no cartão lança o item; Enter na busca
 * lança pelo código (leitor de código de barras, SKU, etiqueta de balança ou
 * "3*código" para 3 unidades).
 */
import Skeleton from "primevue/skeleton";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import EmptyState from "@/components/common/EmptyState.vue";
import type { CatalogProduct, usePdvCatalog } from "@/composables/usePdvCatalog";
import { money, quantity } from "@/utils/format";

/** `opening`: id do produto cujo clique ainda está carregando (spinner no cartão). */
const props = defineProps<{ catalog: ReturnType<typeof usePdvCatalog>; disabled: boolean; opening?: string | null }>();
const emit = defineEmits<{ pick: [product: CatalogProduct]; code: [value: string] }>();
const input = ref<HTMLInputElement>();
const grid = ref<HTMLElement>();
const sentinel = ref<HTMLElement>();
const search = props.catalog.search;
const category = props.catalog.category;

function onEnter() {
  const value = search.value.trim();
  if (!value) return;
  const only = props.catalog.visible.value;
  // Busca que achou um produto só: Enter lança ele. Senão, tenta como código lido.
  if (only.length === 1 && !/^\d{6,}$|\*/.test(value)) emit("pick", only[0]!);
  else emit("code", value);
  search.value = "";
}

/** Cartão sem foto: as iniciais na cor da marca (sólida, igual em todos). */
const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const TYPE_ICON: Record<string, string> = { service: "pi pi-wrench", kit: "pi pi-gift", variable: "pi pi-clone" };

/** Mais 20 sempre que o fim da grade está à vista (ou a menos de 300 px dele).
 *  Conta pela posição real na tela — vale para tela grande sem rolagem nenhuma,
 *  zoom do navegador e celular (onde quem rola é a página) — e é refeita a cada
 *  página que chega, ao rolar e ao redimensionar, até encher a tela. */
function fill() {
  const q = props.catalog.query;
  if (!sentinel.value || !grid.value || !q.hasNextPage.value || q.isFetching.value) return;
  const visibleBottom = Math.min(grid.value.getBoundingClientRect().bottom, window.innerHeight);
  if (sentinel.value.getBoundingClientRect().top - visibleBottom < 300) void props.catalog.more();
}
let resize: ResizeObserver | null = null;
onMounted(() => {
  document.addEventListener("scroll", fill, { capture: true, passive: true });
  window.addEventListener("resize", fill);
  resize = new ResizeObserver(fill);
  if (grid.value) resize.observe(grid.value);
});
watch(() => [props.catalog.visible.value.length, props.catalog.query.isFetching.value], () => fill(), { flush: "post" });
onBeforeUnmount(() => {
  document.removeEventListener("scroll", fill, { capture: true });
  window.removeEventListener("resize", fill);
  resize?.disconnect();
});

defineExpose({ focus: () => input.value?.focus() });
</script>

<template>
  <section class="catalog">
    <div class="search">
      <i class="pi pi-search" />
      <input id="pdv-scanner" ref="input" v-model="search" placeholder="Buscar produto, código ou categoria — ou leia o código de barras"
             autocomplete="off" :disabled="disabled" @keydown.enter.prevent="onEnter" />
      <kbd>Tab</kbd>
      <span class="count">{{ catalog.visible.value.length }} de {{ catalog.total.value }} produtos</span>
    </div>

    <div class="chips" role="tablist">
      <button type="button" class="chip" :class="{ active: category === null }" @click="category = null">Todos</button>
      <button v-for="c in catalog.roots.value" :key="c.id" type="button" class="chip"
              :class="{ active: catalog.activeRoot.value === c.id }" @click="category = c.id">{{ c.name }}</button>
    </div>
    <div v-if="catalog.children.value.length" class="chips chips--sub">
      <button type="button" class="chip chip--sub" :class="{ active: category === catalog.activeRoot.value }"
              @click="category = catalog.activeRoot.value">Tudo</button>
      <button v-for="c in catalog.children.value" :key="c.id" type="button" class="chip chip--sub"
              :class="{ active: category === c.id }" @click="category = c.id">{{ c.name }}</button>
    </div>

    <div ref="grid" class="grid-wrap">
      <div v-if="catalog.query.isPending.value" class="grid">
        <Skeleton v-for="n in 12" :key="n" height="96px" border-radius="10px" />
      </div>
      <EmptyState v-else-if="!catalog.visible.value.length" icon="pi pi-search"
                  :title="search || category ? 'Nada encontrado' : 'Nenhum produto ativo'"
                  :description="search || category ? 'Tente outro nome, código ou categoria.' : 'Cadastre produtos na retaguarda para vender aqui.'" />
      <div v-else class="grid" :class="{ refreshing: catalog.query.isFetching.value && !catalog.query.isFetchingNextPage.value }">
        <div v-for="p in catalog.visible.value" :key="p.id" class="card-wrap">
          <button type="button" class="card" :class="{ loading: opening === p.id }" :disabled="disabled" :title="p.name"
                  @click="emit('pick', p)">
            <span class="thumb" :class="{ 'thumb--photo': p.image }">
              <img v-if="p.image" :src="p.image" alt="" class="thumb__img" loading="lazy" />
              <template v-else>{{ initials(p.name) }}</template>
              <i v-if="TYPE_ICON[p.type]" :class="TYPE_ICON[p.type]" class="thumb__type" />
            </span>
            <span class="info">
              <strong class="name">{{ p.name }}</strong>
              <small class="meta meta--sku">{{ p.sku || "Sem SKU" }}</small>
              <small class="meta">{{ p.categoryName }}</small>
              <span class="bottom">
                <span class="price" :class="{ promo: p.promo }">
                  <small v-if="p.price !== p.priceMax">a partir de </small>{{ money(p.price) }}<small v-if="p.soldByWeight"> / kg</small>
                </span>
                <small v-if="p.stock !== null && p.type !== 'service'" class="stock" :class="{ low: p.stock <= 0 }">
                  {{ quantity(p.stock) }} {{ p.unit.toLowerCase() }}
                </small>
              </span>
            </span>
          </button>
        </div>
      </div>
      <div ref="sentinel" class="sentinel" />
      <p v-if="catalog.query.isFetchingNextPage.value" class="loading-more"><i class="pi pi-spin pi-spinner" /> Carregando mais…</p>
      <button v-else-if="catalog.query.hasNextPage.value && catalog.visible.value.length" type="button" class="load-more"
              @click="catalog.more()">
        Carregar mais ({{ catalog.total.value - catalog.visible.value.length }} restantes)
      </button>
    </div>
  </section>
</template>

<style scoped>
.catalog { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; padding: 12px; }
.search {
  display: flex; align-items: center; gap: 10px; height: 46px; padding: 0 12px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface-card); transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease;
}
.search:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 20%, transparent); }
.search > i { color: var(--text-muted); }
.search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; font: 500 15px/1 var(--font-sans); color: var(--text-strong); }
.search input::placeholder { color: var(--text-subtle); }
kbd { font: 600 10.5px/1 var(--font-mono); padding: 3px 6px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-muted); }
.count { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.chips { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.chips--sub { margin-top: -4px; }
.chip {
  flex-shrink: 0; height: 32px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-card);
  color: var(--text-body); font: 600 12.5px/1 var(--font-sans); cursor: pointer; white-space: nowrap;
  transition: background-color var(--dur-fast) ease, border-color var(--dur-fast) ease, color var(--dur-fast) ease;
}
.chip:hover { border-color: var(--border-strong); color: var(--text-strong); }
.chip.active { background: var(--brand); border-color: var(--brand); color: var(--on-brand); }
.chip--sub { height: 28px; padding: 0 12px; font-size: 12px; background: transparent; }
.chip--sub.active { background: var(--brand-subtle); border-color: var(--brand-border); color: var(--text-brand); }
.grid-wrap { flex: 1; min-height: 0; overflow-y: auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(250px, 100%), 1fr)); gap: 8px; transition: opacity var(--dur-fast) ease; }
.grid.refreshing { opacity: 0.6; }
.card {
  display: flex; gap: 12px; align-items: center; padding: 10px; text-align: left; cursor: pointer; height: 98px; min-width: 0; overflow: hidden;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); font-family: var(--font-sans);
  transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease, transform var(--dur-fast) ease;
}
.card:hover:enabled { border-color: var(--brand); box-shadow: var(--shadow-sm); }
.card:active:enabled { transform: scale(0.985); }
.card:disabled { opacity: 0.5; cursor: not-allowed; }
/* Quadrado (mesma altura e largura), na cor sólida da marca quando não há foto. */
.thumb {
  position: relative; width: 76px; height: 76px; flex-shrink: 0; border-radius: 10px; display: grid; place-items: center; overflow: hidden;
  background: var(--brand-subtle); color: var(--text-brand); border: 1px solid var(--brand-border);
  font: 800 20px/1 var(--font-sans); letter-spacing: 0.02em;
}
.thumb--photo { background: var(--surface-sunken); border-color: var(--border-subtle); }
.thumb__img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.thumb__type {
  position: absolute; right: 4px; bottom: 4px; font-size: 10px; padding: 3px; border-radius: 4px;
  background: var(--surface-card); color: var(--text-brand); box-shadow: var(--shadow-xs);
}
.info { flex: 1; min-width: 0; align-self: stretch; display: flex; flex-direction: column; gap: 3px; }
/* Cartão de altura fixa: cada texto numa linha só, cortado com "…" (o nome inteiro fica no title). */
.name { font-size: 13.5px; font-weight: 700; color: var(--text-strong); line-height: 1.25; text-transform: uppercase;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { font-size: 11.5px; line-height: 1.2; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta--sku { font-family: var(--font-mono); font-size: 11px; }
.bottom { margin-top: auto; display: flex; align-items: baseline; justify-content: space-between; gap: 6px; min-width: 0; white-space: nowrap; }
.price { font: 800 16px/1 var(--font-sans); color: var(--brand); }
.price small { font-size: 11px; font-weight: 600; }
.price.promo { color: var(--accent); }
.stock { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.stock.low { color: var(--danger-text); font-weight: 600; }
.sentinel { height: 1px; }
.card-wrap { position: relative; display: flex; min-width: 0; }
.card-wrap > .card { flex: 1; }
.card.loading { opacity: 0.6; cursor: progress; }
.load-more {
  display: block; margin: 10px auto; padding: 8px 16px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer;
  background: var(--surface-card); color: var(--text-brand); font: 600 13px/1 var(--font-sans);
}
.load-more:hover { border-color: var(--brand); }
.loading-more { margin: 10px 0; text-align: center; font-size: 12.5px; color: var(--text-muted); }
@media (max-width: 860px) { .grid-wrap { padding-bottom: 120px; } /* espaço da gaveta da venda */ }
@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } .count { display: none; } .thumb { width: 64px; height: 64px; } }
</style>
