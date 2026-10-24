<script setup lang="ts">
/**
 * Abas do registro: "Dados" (o formulário) + as consultas declaradas no cadastro
 * (`views`). Cada aba é uma página própria — dá para abrir em nova aba e voltar.
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";

import type { ResourceDef } from "@/resources/types";
import { useSession } from "@/stores/session";

const props = defineProps<{ resource: ResourceDef; id: string; active: string }>();
const session = useSession();

const tabs = computed(() => [
  { name: "dados", label: "Dados", icon: "pi pi-pencil", to: `/cadastros/${props.resource.name}/${props.id}` },
  ...(props.resource.views ?? [])
    .filter((v) => session.can(v.permission) && session.hasModule(v.module))
    .map((v) => ({ name: v.name, label: v.label, icon: v.icon, to: `/cadastros/${props.resource.name}/${props.id}/${v.name}` })),
]);
</script>

<template>
  <nav v-if="tabs.length > 1" class="tabs" aria-label="Consultas do registro">
    <RouterLink v-for="tab in tabs" :key="tab.name" :to="tab.to" class="tab" :class="{ active: tab.name === active }">
      <i :class="tab.icon" /> {{ tab.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.tabs { display: flex; gap: 2px; overflow-x: auto; border-bottom: 1px solid var(--border); scrollbar-width: none; }
.tab {
  display: inline-flex; align-items: center; gap: 7px; padding: 9px 14px; margin-bottom: -1px; white-space: nowrap;
  border-bottom: 2px solid transparent; color: var(--text-muted); font: 600 13px/1 var(--font-sans);
  transition: color var(--dur-fast) ease, border-color var(--dur-fast) ease;
}
.tab i { font-size: 12.5px; }
.tab:hover { color: var(--text-strong); }
.tab.active { color: var(--text-brand); border-bottom-color: var(--brand); }
</style>
