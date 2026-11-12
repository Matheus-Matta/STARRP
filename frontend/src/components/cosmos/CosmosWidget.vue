<script setup lang="ts">
/**
 * Widget da Cosmos no canto inferior direito: o balão abre o painel com as conversas anteriores
 * e o botão de nova conversa; dentro, a conversa e (para quem supervisiona) os alertas da equipe.
 * Alerta novo aparece num balãozinho sobre o botão, mesmo com o painel fechado.
 */
import Button from "primevue/button";
import { computed, onBeforeUnmount, onMounted } from "vue";

import { useCosmos } from "@/stores/cosmos";

import CosmosAlerts from "./CosmosAlerts.vue";
import CosmosAvatar from "./CosmosAvatar.vue";
import CosmosChat from "./CosmosChat.vue";
import CosmosHome from "./CosmosHome.vue";

const cosmos = useCosmos();
const alertsCount = computed(() => cosmos.status?.open_alerts ?? 0);
const title = computed(() => {
  if (cosmos.view === "alerts") return "Supervisão da equipe";
  if (cosmos.view === "chat") return cosmos.active?.title ?? "Nova conversa";
  return "Cosmos";
});
const subtitle = computed(() => {
  if (cosmos.connection === "on") return cosmos.busy[cosmos.key] ? "digitando…" : "online";
  return cosmos.connection === "connecting" ? "conectando…" : "reconectando…";
});

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape" && cosmos.open) cosmos.toggle(false);
}
onMounted(() => {
  void cosmos.boot();
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  cosmos.disconnect();
});
</script>

<template>
  <div v-if="cosmos.status?.can_use" class="cosmos no-print">
    <transition name="pop">
      <section v-if="cosmos.open" class="panel" role="dialog" aria-label="Cosmos, assistente de IA">
        <header class="panel__head">
          <Button v-if="cosmos.view !== 'home'" icon="pi pi-arrow-left" text rounded size="small" aria-label="Voltar"
                  @click="cosmos.view = 'home'" />
          <CosmosAvatar :size="32" />
          <div class="panel__title">
            <strong>{{ title }}</strong>
            <small><span class="dot" :class="`dot--${cosmos.connection}`" /> Cosmos · {{ subtitle }}</small>
          </div>
          <!-- O contador fica FORA do botão (o botão corta o que passa da borda dele). -->
          <span v-if="cosmos.status?.can_supervise" class="badge-host">
            <Button icon="pi pi-shield" text rounded size="small" aria-label="Alertas da equipe" title="Alertas da equipe"
                    @click="cosmos.view = 'alerts'" />
            <span v-if="alertsCount" class="badge">{{ alertsCount > 99 ? "99+" : alertsCount }}</span>
          </span>
          <Button icon="pi pi-pen-to-square" text rounded size="small" aria-label="Nova conversa"
                  title="Nova conversa" @click="cosmos.newConversation()" />
          <Button icon="pi pi-times" text rounded size="small" aria-label="Fechar"
                  @click="cosmos.toggle(false)" />
        </header>
        <div class="panel__body">
          <CosmosChat v-if="cosmos.view === 'chat'" />
          <CosmosAlerts v-else-if="cosmos.view === 'alerts'" />
          <CosmosHome v-else />
        </div>
      </section>
    </transition>

    <transition name="pop">
      <aside v-if="cosmos.peek && !cosmos.open" class="peek" :class="`peek--${cosmos.peek.severity}`">
        <button type="button" class="peek__close" aria-label="Fechar aviso" @click="cosmos.peek = null">
          <i class="pi pi-times" />
        </button>
        <div class="peek__head"><CosmosAvatar :size="22" /> <strong>Cosmos · supervisão</strong></div>
        <p :title="cosmos.peek.message ?? cosmos.peek.title">{{ cosmos.peek.message ?? cosmos.peek.title }}</p>
        <div class="peek__actions">
          <Button label="Ver alertas" size="small" text
                  @click="cosmos.toggle(true); cosmos.view = 'alerts'" />
          <Button label="Corrigir" icon="pi pi-sparkles" size="small" @click="cosmos.fixWithCosmos(cosmos.peek!)" />
        </div>
      </aside>
    </transition>

    <transition name="pop">
      <aside v-if="cosmos.digestPeek && !cosmos.open && !cosmos.peek" class="peek peek--info">
        <button type="button" class="peek__close" aria-label="Fechar aviso" @click="cosmos.digestPeek = null">
          <i class="pi pi-times" />
        </button>
        <div class="peek__head"><CosmosAvatar :size="22" /> <strong>Cosmos · resumo do dia</strong></div>
        <p>O resumo da equipe de ontem está pronto: quem fez o quê e o que precisa de correção.</p>
        <div class="peek__actions">
          <Button label="Abrir resumo" size="small" @click="cosmos.openDigest()" />
        </div>
      </aside>
    </transition>

    <button type="button" class="launcher" :class="{ 'launcher--open': cosmos.open }"
            :aria-label="cosmos.open ? 'Fechar a Cosmos' : 'Abrir a Cosmos'" @click="cosmos.toggle()">
      <i v-if="cosmos.open" class="pi pi-chevron-down" />
      <CosmosAvatar v-else :size="56" />
      <span v-if="!cosmos.open && alertsCount" class="launcher__badge">{{ alertsCount > 99 ? "99+" : alertsCount }}</span>
    </button>
  </div>
</template>

<style scoped>
.cosmos { position: fixed; right: 20px; bottom: 20px; z-index: 60; display: flex; flex-direction: column;
          align-items: flex-end; gap: 12px; pointer-events: none; }
.cosmos > * { pointer-events: auto; }
.launcher { position: relative; overflow: visible; width: 56px; height: 56px; border-radius: 50%; border: 0; padding: 0; cursor: pointer;
            display: grid; place-items: center; background: var(--surface-raised); color: var(--text-strong);
            box-shadow: var(--shadow-lg); transition: transform var(--dur-base) var(--ease-spring); }
.launcher:hover { transform: scale(1.06); }
.launcher--open { background: var(--surface-raised); color: var(--text-strong); border: 1px solid var(--border); }
.launcher__badge, .badge { position: absolute; z-index: 2; pointer-events: none; top: -2px; right: -2px; min-width: 18px; height: 18px; padding: 0 5px;
                           border-radius: 9px; background: var(--danger); color: #fff; font: 700 10.5px/18px var(--font-sans);
                           text-align: center; box-shadow: 0 0 0 2px var(--surface-card); }
.badge { top: 0; right: -2px; min-width: 16px; height: 16px; line-height: 16px; font-size: 9.5px; }
.panel { width: min(420px, calc(100vw - 24px)); height: min(680px, calc(100vh - 110px)); display: flex; flex-direction: column;
         border-radius: var(--radius-xl); overflow: hidden; background: var(--surface-card); border: 1px solid var(--border);
         box-shadow: var(--shadow-lg); }
.panel__head { display: flex; align-items: center; gap: 8px; padding: 10px 8px 10px 12px; color: var(--text-strong);
               background: var(--surface-card); border-bottom: 1px solid var(--border); }
.panel__title { flex: 1; min-width: 0; display: grid; }
.panel__title strong { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.panel__title small { font-size: 11.5px; color: var(--text-muted); display: inline-flex; gap: 5px; align-items: center; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--warning); }
.dot--on { background: var(--success); }
.badge-host { position: relative; display: inline-flex; }
.panel__body { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; }
.panel__body > * { flex: 1; min-height: 0; }
.peek { position: relative; width: min(320px, calc(100vw - 32px)); padding: 12px 14px; border-radius: var(--radius-lg);
        background: var(--surface-raised); border: 1px solid var(--border); border-left: 3px solid var(--warning);
        box-shadow: var(--shadow-lg); display: grid; gap: 6px; }
.peek--critical { border-left-color: var(--danger); }
.peek--info { border-left-color: var(--info); }
.peek__head { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--text-strong); }
.peek p { margin: 0; font-size: 13px; color: var(--text-body); line-height: 1.45; padding-right: 12px;
          display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.peek__actions { display: flex; justify-content: flex-end; gap: 4px; flex-wrap: nowrap; }
.peek__actions :deep(.p-button) { white-space: nowrap; }
.peek__close { position: absolute; top: 6px; right: 6px; border: 0; background: none; color: var(--text-subtle); cursor: pointer; }
.pop-enter-active, .pop-leave-active { transition: opacity var(--dur-base) ease, transform var(--dur-base) var(--ease-out); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(12px) scale(0.98); }
@media (max-width: 640px) {
  .cosmos { right: 12px; bottom: 12px; }
  .panel { position: fixed; inset: 0; width: 100vw; height: 100dvh; border-radius: 0; border: 0; }
}
@media print { .cosmos { display: none; } }
</style>
