<script setup lang="ts">
/**
 * Menu lateral escuro e compacto (nos dois temas): marca, loja ativa, grupos
 * recolhíveis e o usuário no rodapé. Passar o mouse num item já busca os dados
 * da tela (a lista abre pronta).
 */
import { useQueryClient } from "@tanstack/vue-query";
import TieredMenu from "primevue/tieredmenu";
import { computed, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { usePrefetch } from "@/composables/usePrefetch";
import { BRANDS, useTheme } from "@/composables/useTheme";
import { useSession } from "@/stores/session";

import { buildNavigation } from "./navigation";
import StorePicker from "./StorePicker.vue";

const props = defineProps<{ collapsed: boolean; mobileOpen: boolean }>();
const emit = defineEmits<{ close: []; search: [] }>();
const session = useSession();
const route = useRoute();
const router = useRouter();
const queryClient = useQueryClient();
const theme = useTheme();
const prefetch = usePrefetch();
const groups = computed(() => buildNavigation(session.can, session.hasModule));
const userMenu = ref<InstanceType<typeof TieredMenu>>();

const KEY = "starrp.nav.closed";
function readClosed(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}
const closedGroups = ref<string[]>(readClosed());
function toggleGroup(label: string) {
  closedGroups.value = closedGroups.value.includes(label)
    ? closedGroups.value.filter((g) => g !== label) : [...closedGroups.value, label];
  try {
    localStorage.setItem(KEY, JSON.stringify(closedGroups.value));
  } catch {
    // sem storage: vale só nesta aba
  }
}

function isActive(to: string) {
  return to === "/" ? route.path === "/" : route.path === to || route.path.startsWith(`${to}/`);
}
const mini = computed(() => props.collapsed && !props.mobileOpen);
const initials = computed(() => (session.me?.name ?? "?").split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase());

const userItems = computed(() => [
  { label: theme.resolved.value === "dark" ? "Tema claro" : "Tema escuro",
    icon: theme.resolved.value === "dark" ? "pi pi-sun" : "pi pi-moon", command: theme.toggle },
  { label: "Cor do sistema", icon: "pi pi-palette", items: BRANDS.map((b) => ({
    label: b.label, icon: theme.brand.value === b.value ? "pi pi-check" : "pi pi-circle-fill", swatch: b.swatch,
    command: () => theme.setBrand(b.value),
  })) },
  { label: "Abrir o PDV", icon: "pi pi-shopping-cart", command: () => router.push("/pdv") },
  { separator: true },
  { label: "Sair", icon: "pi pi-sign-out", command: async () => {
    await session.logout();
    queryClient.clear();
    router.push("/login");
  } },
]);
</script>

<template>
  <aside class="nav" :class="{ 'nav--mini': mini, 'nav--open': mobileOpen }">
    <div class="nav__brand">
      <!-- Logo do tema: menu branco = "Star" escuro; menu escuro = "Star" branco. Recolhido, só a marca "rp". -->
      <img v-if="mini" src="/brand/mark.png" alt="Starrp" class="nav__mark" width="30" height="30" />
      <img v-else :src="theme.resolved.value === 'dark' ? '/brand/logo-light.png' : '/brand/logo.png'" alt="Starrp"
           class="nav__logo" height="26" />
      <button type="button" class="nav__close" aria-label="Fechar menu" @click="emit('close')"><i class="pi pi-times" /></button>
    </div>
    <div class="nav__store"><StorePicker :collapsed="mini" /></div>
    <button type="button" class="nav__search" :title="mini ? 'Buscar (Ctrl+K)' : undefined" @click="emit('search')">
      <i class="pi pi-search" />
      <template v-if="!mini"><span>Buscar…</span><kbd>Ctrl K</kbd></template>
    </button>

    <nav class="nav__list">
      <div v-for="group in groups" :key="group.label" class="nav__group">
        <button v-if="!mini" type="button" class="nav__group-header" @click="toggleGroup(group.label)">
          <span>{{ group.label }}</span>
          <i :class="closedGroups.includes(group.label) ? 'pi pi-chevron-right' : 'pi pi-chevron-down'" />
        </button>
        <div v-show="mini || !closedGroups.includes(group.label)">
          <RouterLink v-for="item in group.items" :key="item.to" :to="item.to" class="nav__item"
                      :class="{ 'nav__item--active': isActive(item.to) }" :title="mini ? item.label : undefined"
                      @mouseenter="prefetch.route(item.to)" @focus="prefetch.route(item.to)" @click="emit('close')">
            <i :class="item.icon" />
            <span v-if="!mini">{{ item.label }}</span>
          </RouterLink>
        </div>
      </div>
    </nav>

    <button type="button" class="nav__user" aria-haspopup="menu" @click="userMenu?.toggle($event)">
      <span class="nav__avatar">{{ initials }}</span>
      <span v-if="!mini" class="nav__who"><strong>{{ session.me?.name }}</strong><small>{{ (session.me?.roles ?? []).map((r) => r.name).join(" + ") || session.me?.role?.name }}</small></span>
      <i v-if="!mini" class="pi pi-ellipsis-v" />
    </button>
    <TieredMenu ref="userMenu" :model="userItems" popup>
      <template #itemicon="{ item }">
        <i :class="item.icon" class="menu-icon" :style="item.swatch ? { color: item.swatch } : undefined" />
      </template>
    </TieredMenu>
  </aside>
</template>

<style scoped>
.nav {
  width: var(--sidebar-w); flex-shrink: 0; height: 100vh; position: sticky; top: 0; z-index: 30;
  display: flex; flex-direction: column; background: var(--nav-bg); color: var(--nav-text); border-right: 1px solid var(--nav-border);
  transition: width var(--dur-slow) var(--ease-out), transform var(--dur-slow) var(--ease-out);
}
.nav--mini { width: var(--sidebar-w-mini); }
.nav__brand { height: var(--topbar-h); display: flex; align-items: center; gap: 10px; padding: 0 16px; }
.nav--mini .nav__brand { justify-content: center; padding: 0; }
.nav__logo { height: 26px; width: auto; display: block; }
.nav__mark { width: 30px; height: 30px; display: block; }
.nav__close { display: none; margin-left: auto; border: 0; background: transparent; color: var(--nav-muted); cursor: pointer; padding: 6px; border-radius: 6px; }
.nav__close:hover { background: var(--nav-hover); color: var(--nav-strong); }
.nav__store { padding: 0 10px 8px; }
.nav__store :deep(.picker__current) { background: var(--nav-hover); border-color: var(--nav-border); }
.nav__store :deep(.picker__text strong) { color: var(--nav-strong); }
.nav__store :deep(.picker__text small), .nav__store :deep(.picker__current > .pi) { color: var(--nav-muted); }
.nav__store :deep(.picker__icon) { background: var(--nav-active); color: var(--nav-active-text); width: 28px; height: 28px; }
.nav__search {
  margin: 0 10px 6px; display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 10px; border-radius: 7px; cursor: pointer;
  border: 1px solid var(--nav-border); background: transparent; color: var(--nav-muted); font: 500 12.5px/1 var(--font-sans);
}
.nav__search:hover { color: var(--nav-text); border-color: var(--nav-border-strong); background: var(--nav-hover); }
.nav__search kbd { margin-left: auto; font: 600 10.5px/1 var(--font-mono); padding: 3px 5px; border-radius: 4px; border: 1px solid var(--nav-border); }
.nav--mini .nav__search { justify-content: center; padding: 0; }
.nav__list { flex: 1; overflow-y: auto; padding: 4px 10px 12px; scrollbar-color: var(--nav-border) transparent; }
.nav__group { margin-top: 10px; }
.nav__group-header {
  width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 4px 8px; margin-bottom: 2px;
  border: 0; background: transparent; border-radius: 6px; cursor: pointer;
  font: 700 10.5px/1.4 var(--font-sans); letter-spacing: 0.07em; text-transform: uppercase; color: var(--nav-muted);
}
.nav__group-header i { font-size: 9px; opacity: 0; transition: opacity var(--dur-fast) ease; }
.nav__group-header:hover { color: var(--nav-text); }
.nav__group-header:hover i { opacity: 1; }
.nav__item {
  display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 10px; border-radius: 7px;
  color: var(--nav-text); font: 500 13px/1 var(--font-sans); transition: background-color var(--dur-fast) ease, color var(--dur-fast) ease;
}
.nav--mini .nav__item { justify-content: center; padding: 0; height: 36px; }
.nav__item i { font-size: 14px; width: 16px; text-align: center; color: var(--nav-muted); transition: color var(--dur-fast) ease; }
.nav__item:hover { background: var(--nav-hover); color: var(--nav-strong); }
.nav__item:hover i { color: var(--nav-text); }
.nav__item--active, .nav__item--active:hover { background: var(--nav-active); color: var(--nav-active-text); font-weight: 600; }
.nav__item--active i, .nav__item--active:hover i { color: var(--nav-active-text); }
.nav__user {
  display: flex; align-items: center; gap: 10px; margin: 0; padding: 10px 14px; border: 0; border-top: 1px solid var(--nav-border);
  background: transparent; color: var(--nav-muted); cursor: pointer; text-align: left;
}
.nav__user:hover { background: var(--nav-hover); color: var(--nav-strong); }
.nav--mini .nav__user { justify-content: center; padding: 10px 0; }
.nav__avatar { width: 28px; height: 28px; flex-shrink: 0; border-radius: 50%; display: grid; place-items: center; font: 700 11px/1 var(--font-sans); color: var(--brand-950); background: var(--brand-300); }
.nav__who { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.2; }
.nav__who strong { font-size: 12.5px; color: var(--nav-strong); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nav__who small { font-size: 11px; color: var(--nav-muted); }

@media (max-width: 960px) {
  .nav { position: fixed; left: 0; transform: translateX(-100%); width: var(--sidebar-w); }
  .nav--open { transform: none; box-shadow: var(--shadow-lg); }
  .nav__close { display: inline-flex; }
}
</style>
