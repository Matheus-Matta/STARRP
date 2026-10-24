<script setup lang="ts">
/**
 * Barra de status do PDV (fina, no topo): loja e situação do caixa, operador,
 * desde quando o turno está aberto, conexão e tema.
 */
import { onBeforeUnmount, onMounted, ref } from "vue";

import { useTheme } from "@/composables/useTheme";

defineProps<{ store: string; cashOpen: boolean; operator: string; since: string | null; terminal: string;
               seller?: boolean }>();
const emit = defineEmits<{ lock: []; cash: [] }>();
const theme = useTheme();
const online = ref(navigator.onLine);
const update = () => (online.value = navigator.onLine);
onMounted(() => { window.addEventListener("online", update); window.addEventListener("offline", update); });
onBeforeUnmount(() => { window.removeEventListener("online", update); window.removeEventListener("offline", update); });
const hour = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
</script>

<template>
  <header class="status">
    <img src="/brand/mark.png" alt="Starrp" class="logo" width="26" height="26" />
    <strong class="store">{{ store }}</strong>
    <span v-if="seller" class="state state--seller"><i class="pi pi-shopping-bag" /> Modo vendedor</span>
    <span v-else-if="cashOpen" class="state state--on">Caixa aberto</span>
    <button v-else type="button" class="state state--off state--btn" title="Abrir o caixa" @click="emit('cash')">
      <i class="pi pi-lock" /> Caixa fechado</button>
    <span class="sep" />
    <span class="info"><i class="pi pi-user" /> {{ operator }}</span>
    <span v-if="since && !seller" class="info"><i class="pi pi-clock" /> Turno desde {{ hour(since) }}</span>
    <span v-if="terminal" class="info hide-sm"><i class="pi pi-desktop" /> {{ terminal }}</span>
    <div class="right">
      <span class="net" :class="online ? 'net--on' : 'net--off'"><i :class="online ? 'pi pi-wifi' : 'pi pi-exclamation-triangle'" />
        {{ online ? "Online" : "Sem conexão" }}</span>
      <button v-if="!seller" type="button" class="icon" title="Bloquear a tela (F12)" aria-label="Bloquear a tela"
              @click="emit('lock')"><i class="pi pi-lock" /></button>
      <button type="button" class="icon" :title="theme.resolved.value === 'dark' ? 'Tema claro' : 'Tema escuro'" @click="theme.toggle">
        <i :class="theme.resolved.value === 'dark' ? 'pi pi-sun' : 'pi pi-moon'" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.status {
  height: 44px; flex-shrink: 0; display: flex; align-items: center; gap: 12px; padding: 0 14px;
  background: var(--nav-bg); color: var(--nav-text); border-bottom: 1px solid var(--nav-border); font-size: 12.5px;
}
.logo { width: 26px; height: 26px; display: block; }
.store { color: var(--nav-strong); font-size: 13.5px; white-space: nowrap; }
.state { font-weight: 700; font-size: 12px; }
.state--on { color: var(--success-text); }
.state--off { color: var(--warning-text); }
.state--btn { border: 0; background: transparent; cursor: pointer; display: inline-flex; gap: 5px; align-items: center;
              font: inherit; padding: 2px 6px; border-radius: 6px; }
.state--btn:hover { background: color-mix(in srgb, var(--warning) 14%, transparent); }
.state--seller { color: var(--text-brand); display: inline-flex; gap: 6px; align-items: center; }
.sep { width: 1px; height: 18px; background: var(--nav-border); }
.info { display: inline-flex; align-items: center; gap: 6px; color: var(--nav-text); white-space: nowrap; }
.info i { font-size: 11px; color: var(--nav-muted); }
.right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.net { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }
.net--on { color: var(--success-text); }
.net--off { color: var(--danger-text); }
.icon { width: 30px; height: 30px; border: 0; border-radius: 7px; background: transparent; color: var(--nav-muted); cursor: pointer; display: grid; place-items: center; }
.icon:hover { background: var(--nav-hover); color: var(--nav-strong); }
@media (max-width: 900px) { .hide-sm, .sep { display: none; } }
@media (max-width: 640px) { .info { display: none; } }
</style>
