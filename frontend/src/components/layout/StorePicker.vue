<script setup lang="ts">
/**
 * Seletor da loja ativa (topo do menu). "Todas as minhas lojas" só aparece para
 * quem tem mais de uma: vira `X-Store-ID: *` (visão consolidada).
 */
import { useQueryClient } from "@tanstack/vue-query";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ALL_STORES, useSession } from "@/stores/session";

defineProps<{ collapsed?: boolean }>();
const session = useSession();
const queryClient = useQueryClient();
const open = ref(false);
const root = ref<HTMLElement>();

const multi = computed(() => session.stores.length > 1);
const title = computed(() => session.activeStore?.name ?? (session.activeStoreId === ALL_STORES ? "Todas as lojas" : "Selecione a loja"));
const subtitle = computed(() => {
  if (!session.activeStore) return `${session.stores.length} lojas`;
  const account = session.me?.account?.name;
  return account && account !== session.activeStore.name ? account : multi.value ? "Trocar de loja" : "Loja ativa";
});

async function choose(id: string) {
  open.value = false;
  session.setActiveStore(id);
  await session.load();
  queryClient.invalidateQueries();
}

function onOutside(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false;
}
onMounted(() => document.addEventListener("click", onOutside));
onBeforeUnmount(() => document.removeEventListener("click", onOutside));
</script>

<template>
  <div ref="root" class="picker">
    <button type="button" class="picker__current" :class="{ 'picker__current--mini': collapsed }" :title="title"
            :aria-expanded="open" :disabled="!multi" @click="open = !open">
      <span class="picker__icon"><i class="pi pi-building" /></span>
      <span v-if="!collapsed" class="picker__text">
        <strong>{{ title }}</strong>
        <small>{{ subtitle }}</small>
      </span>
      <i v-if="!collapsed && multi" class="pi pi-sort" />
    </button>
    <Transition name="pop">
      <div v-if="open" class="picker__menu" role="menu">
        <button type="button" class="picker__option" :class="{ active: session.activeStoreId === ALL_STORES }"
                @click="choose(ALL_STORES)">
          <span>Todas as minhas lojas</span><small>Visão consolidada</small>
        </button>
        <button v-for="store in session.stores" :key="store.id" type="button" class="picker__option"
                :class="{ active: session.activeStoreId === store.id }" @click="choose(store.id)">
          <span>{{ store.name }}</span>
          <i v-if="session.activeStoreId === store.id" class="pi pi-check" />
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.picker { position: relative; }
.picker__current {
  width: 100%; display: flex; align-items: center; gap: 10px; padding: 9px 10px; cursor: pointer; text-align: left;
  background: var(--surface-sunken); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-muted);
}
.picker__current:enabled:hover { border-color: var(--brand-border); background: var(--nav-item-hover); }
.picker__current:disabled { cursor: default; }
.picker__current--mini { justify-content: center; padding: 8px; }
.picker__icon { width: 32px; height: 32px; flex-shrink: 0; border-radius: var(--radius-sm); display: grid; place-items: center; background: var(--brand-subtle); color: var(--brand); }
.picker__text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.picker__text strong { font-size: 13px; color: var(--text-strong); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.picker__text small { font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.picker__menu {
  position: absolute; top: calc(100% + 6px); left: 0; min-width: 100%; width: max-content; max-width: 300px; z-index: 40;
  padding: 6px; background: var(--surface-raised); border: 1px solid var(--border); border-radius: var(--radius-md); box-shadow: var(--shadow-lg);
}
.picker__option {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 10px; border: 0;
  border-radius: var(--radius-sm); background: transparent; color: var(--text-strong); font: 600 13px/1.2 var(--font-sans); cursor: pointer; text-align: left;
}
.picker__option small { color: var(--text-muted); font-weight: 500; font-size: 11px; }
.picker__option:hover { background: var(--nav-item-hover); }
.picker__option.active { background: var(--nav-item-active); color: var(--text-brand); }
.pop-enter-active, .pop-leave-active { transition: opacity var(--dur-fast) ease, transform var(--dur-base) var(--ease-spring); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-4px) scale(0.98); }
</style>
