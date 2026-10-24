<script setup lang="ts">
/** Barra superior fina: menu, caminho da página, busca rápida e tema. */
import { computed } from "vue";
import { useRoute } from "vue-router";

import { useTheme } from "@/composables/useTheme";
import { findResource } from "@/resources";

const emit = defineEmits<{ menu: []; search: [] }>();
const route = useRoute();
const theme = useTheme();

const crumbs = computed(() => {
  const resource = route.params.resource ? findResource(String(route.params.resource)) : null;
  if (resource) {
    const view = resource.views?.find((v) => v.name === route.params.view);
    if (view) return [resource.group, resource.title, view.label];
    const isForm = Boolean(route.params.id);
    return [resource.group, resource.title, ...(isForm ? [route.params.id === "novo" ? "Novo" : "Editar"] : [])];
  }
  return [String(route.meta.title ?? "Painel")];
});
</script>

<template>
  <header class="topbar">
    <button type="button" class="icon-btn" aria-label="Menu" @click="emit('menu')"><i class="pi pi-bars" /></button>
    <nav class="crumbs" aria-label="Caminho">
      <template v-for="(crumb, index) in crumbs" :key="index">
        <i v-if="index" class="pi pi-angle-right" />
        <span :class="{ current: index === crumbs.length - 1 }">{{ crumb }}</span>
      </template>
    </nav>
    <div class="actions">
      <button type="button" class="search" @click="emit('search')">
        <i class="pi pi-search" /><span>Buscar telas, produtos, clientes…</span><kbd>Ctrl K</kbd>
      </button>
      <button type="button" class="icon-btn" :aria-label="theme.resolved.value === 'dark' ? 'Tema claro' : 'Tema escuro'"
              :title="theme.resolved.value === 'dark' ? 'Tema claro' : 'Tema escuro'" @click="theme.toggle">
        <i :class="theme.resolved.value === 'dark' ? 'pi pi-sun' : 'pi pi-moon'" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: var(--topbar-h); position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 10px; padding: 0 16px;
  background: color-mix(in srgb, var(--surface-ground) 88%, transparent); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border);
}
.icon-btn {
  width: 32px; height: 32px; display: grid; place-items: center; border-radius: 7px; border: 0;
  background: transparent; color: var(--text-muted); cursor: pointer;
}
.icon-btn:hover { background: var(--surface-hover); color: var(--text-strong); }
.crumbs { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 12.5px; color: var(--text-muted); }
.crumbs i { font-size: 10px; color: var(--text-subtle); }
.crumbs span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.crumbs .current { color: var(--text-strong); font-weight: 600; }
.actions { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.search {
  display: flex; align-items: center; gap: 8px; width: 300px; height: 32px; padding: 0 8px 0 10px; border-radius: 7px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface-card); color: var(--text-subtle); font: 500 12.5px/1 var(--font-sans);
}
.search:hover { border-color: var(--border-strong); color: var(--text-muted); }
.search span { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.search kbd { font: 600 10.5px/1 var(--font-mono); padding: 3px 5px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-muted); background: var(--surface-sunken); }
@media (max-width: 760px) { .search { width: 32px; padding: 0; justify-content: center; } .search span, .search kbd { display: none; } }
</style>
