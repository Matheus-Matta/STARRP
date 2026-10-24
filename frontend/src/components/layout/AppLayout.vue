<script setup lang="ts">
/**
 * Casca da retaguarda: menu escuro compacto, barra fina e busca rápida (Ctrl+K).
 *
 * Troca de tela SEM animação de saída (ela só atrasava) e com o código das
 * telas principais baixado quando o navegador fica ocioso. A barra de
 * progresso só aparece se a rota demorar mais de 150 ms.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { RouterView, useRouter } from "vue-router";

import { usePrefetch } from "@/composables/usePrefetch";

import AppSidebar from "./AppSidebar.vue";
import AppTopbar from "./AppTopbar.vue";
import CommandPalette from "./CommandPalette.vue";

const KEY = "starrp.nav.mini";
const readMini = () => {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
};
const collapsed = ref(readMini());
const mobileOpen = ref(false);
const paletteOpen = ref(false);
const loading = ref(false);
const router = useRouter();
let slow: ReturnType<typeof setTimeout> | undefined;
const stopBefore = router.beforeEach(() => {
  slow = setTimeout(() => (loading.value = true), 150);
});
const stopAfter = router.afterEach(() => {
  clearTimeout(slow);
  loading.value = false;
});

function onKey(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    paletteOpen.value = !paletteOpen.value;
  }
}
onMounted(() => {
  window.addEventListener("keydown", onKey);
  usePrefetch().warmPages();
});
onBeforeUnmount(() => {
  stopBefore();
  stopAfter();
  window.removeEventListener("keydown", onKey);
});

function onMenu() {
  if (window.matchMedia("(max-width: 960px)").matches) {
    mobileOpen.value = !mobileOpen.value;
    return;
  }
  collapsed.value = !collapsed.value;
  try {
    localStorage.setItem(KEY, collapsed.value ? "1" : "0");
  } catch {
    // sem storage: vale só nesta aba
  }
}
</script>

<template>
  <div class="shell">
    <div v-if="loading" class="progress" />
    <AppSidebar :collapsed="collapsed" :mobile-open="mobileOpen" @close="mobileOpen = false" @search="paletteOpen = true" />
    <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false" />
    <div class="main">
      <AppTopbar @menu="onMenu" @search="paletteOpen = true" />
      <main>
        <RouterView v-slot="{ Component, route }">
          <component :is="Component" :key="route.fullPath" />
        </RouterView>
      </main>
    </div>
    <CommandPalette v-model:open="paletteOpen" />
  </div>
</template>

<style scoped>
.shell { display: flex; min-height: 100%; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
main { flex: 1; }
.scrim { position: fixed; inset: 0; z-index: 25; background: var(--surface-overlay); }
.progress {
  position: fixed; z-index: 100; top: 0; left: 0; height: 2px; width: 40%;
  background: var(--brand); animation: progress 900ms ease-in-out infinite;
}
@keyframes progress { from { transform: translateX(-100%); } to { transform: translateX(260%); } }
</style>
