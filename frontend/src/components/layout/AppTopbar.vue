<script setup lang="ts">
/** Barra superior fina: menu, caminho da página, busca rápida e tema. */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { type AppNotification, notificationsApi } from "@/api/notifications";
import { useTheme } from "@/composables/useTheme";
import { findResource } from "@/resources";
import { NOTIFICATION_CATEGORIES, NOTIFICATION_LEVELS, notificationRelative } from "@/utils/notifications";

const emit = defineEmits<{ menu: []; search: [] }>();
const route = useRoute();
const router = useRouter();
const theme = useTheme();
const notificationHost = ref<HTMLElement | null>(null);
const notificationsOpen = ref(false);
const notifications = ref<AppNotification[]>([]);
const unread = ref(0);
const notificationsLoading = ref(false);
let notificationTimer: number | undefined;

async function loadNotifications(withList = notificationsOpen.value) {
  unread.value = await notificationsApi.unreadCount().catch(() => unread.value);
  if (!withList) return;
  notificationsLoading.value = true;
  const page = await notificationsApi.list().catch(() => null);
  if (page) notifications.value = page.results;
  notificationsLoading.value = false;
}

async function toggleNotifications() {
  notificationsOpen.value = !notificationsOpen.value;
  if (notificationsOpen.value) await loadNotifications(true);
}

async function openNotification(item: AppNotification) {
  if (!item.read_at) {
    item.read_at = (await notificationsApi.read(item.id)).read_at;
    unread.value = Math.max(0, unread.value - 1);
  }
  notificationsOpen.value = false;
  if (item.url) await router.push(item.url);
}

async function readAll() {
  await notificationsApi.readAll();
  unread.value = 0;
  const now = new Date().toISOString();
  notifications.value.forEach((item) => (item.read_at ??= now));
}

function closeNotifications(event: MouseEvent) {
  if (!notificationHost.value?.contains(event.target as Node)) notificationsOpen.value = false;
}

function closeNotificationsOnEscape(event: KeyboardEvent) {
  if (event.key === "Escape") notificationsOpen.value = false;
}

async function openActivityPanel() {
  notificationsOpen.value = false;
  await router.push("/");
}

onMounted(() => {
  void loadNotifications(false);
  // Aba escondida não consulta (várias abas abertas o dia todo não somam chamadas à toa).
  notificationTimer = window.setInterval(() => document.hidden || void loadNotifications(false), 60_000);
  document.addEventListener("click", closeNotifications);
  document.addEventListener("keydown", closeNotificationsOnEscape);
});
onBeforeUnmount(() => {
  window.clearInterval(notificationTimer);
  document.removeEventListener("click", closeNotifications);
  document.removeEventListener("keydown", closeNotificationsOnEscape);
});

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
      <div ref="notificationHost" class="notification-host">
        <button type="button" class="icon-btn notification-button" aria-label="Notificações" title="Notificações"
                :aria-expanded="notificationsOpen" aria-controls="notification-panel" @click.stop="toggleNotifications">
          <i class="pi pi-bell" />
          <span v-if="unread" class="notification-badge">{{ unread > 99 ? "99+" : unread }}</span>
        </button>
        <section v-if="notificationsOpen" id="notification-panel" class="notification-panel" aria-label="Notificações recentes" @click.stop>
          <header class="notification-head">
            <span class="notification-head__icon"><i class="pi pi-bell" /></span>
            <span class="notification-head__copy">
              <strong>Notificações</strong>
              <small>{{ unread ? `${unread} ${unread === 1 ? "não lida" : "não lidas"}` : "Tudo em dia" }}</small>
            </span>
            <button v-if="unread" type="button" class="notification-read-all" title="Marcar todas como lidas" @click="readAll">
              <i class="pi pi-check-circle" /><span>Marcar como lidas</span>
            </button>
          </header>
          <div class="notification-list">
            <div v-if="notificationsLoading && !notifications.length" class="notification-empty">
              <span class="notification-empty__icon"><i class="pi pi-spin pi-spinner" /></span>
              <strong>Carregando notificações</strong><small>Buscando as atualizações mais recentes…</small>
            </div>
            <button v-for="item in notifications" :key="item.id" type="button" class="notification-item"
                    :class="[{ unread: !item.read_at }, `level-${item.level}`]" @click="openNotification(item)">
              <span class="notification-item__icon" :class="item.level">
                <i :class="NOTIFICATION_CATEGORIES[item.category].icon" />
                <i class="notification-item__level" :class="NOTIFICATION_LEVELS[item.level].icon"
                   :title="NOTIFICATION_LEVELS[item.level].label" />
              </span>
              <span class="notification-copy">
                <span class="notification-meta">
                  <span>{{ NOTIFICATION_CATEGORIES[item.category].label }}</span>
                  <i class="pi pi-circle-fill" />
                  <time :datetime="item.created_at">{{ notificationRelative(item.created_at) }}</time>
                </span>
                <strong>{{ item.title }}</strong>
                <span v-if="item.body" class="notification-body">{{ item.body }}</span>
              </span>
              <span class="notification-item__end">
                <i v-if="!item.read_at" class="notification-unread" title="Não lida" />
                <i v-if="item.url" class="pi pi-angle-right" />
              </span>
            </button>
            <div v-if="!notificationsLoading && !notifications.length" class="notification-empty">
              <span class="notification-empty__icon success"><i class="pi pi-check" /></span>
              <strong>Você está em dia</strong><small>Novas atividades aparecerão aqui.</small>
            </div>
          </div>
          <footer class="notification-footer">
            <button type="button" @click="openActivityPanel"><i class="pi pi-th-large" /> Ver painel de atividades <i class="pi pi-arrow-right" /></button>
          </footer>
        </section>
      </div>
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
.notification-host { position: relative; }
.notification-button { position: relative; }
.notification-button[aria-expanded="true"] { background: var(--brand-subtle); color: var(--text-brand); }
.notification-badge {
  position: absolute; top: -3px; right: -5px; min-width: 17px; height: 17px; padding: 0 4px; display: grid; place-items: center;
  border: 2px solid var(--surface-ground); border-radius: 9px; background: var(--danger); color: white; font-size: 9px; font-weight: 800;
}
.notification-panel {
  position: absolute; top: 42px; right: 0; z-index: 80; width: min(430px, calc(100vw - 24px));
  overflow: hidden; border: 1px solid var(--border); border-radius: 16px; background: var(--surface-raised); box-shadow: var(--shadow-lg);
  transform-origin: top right; animation: notification-in var(--dur-base) var(--ease-out);
}
@keyframes notification-in { from { opacity: 0; transform: translateY(-6px) scale(.98); } to { opacity: 1; transform: none; } }
.notification-head { display: flex; align-items: center; gap: 10px; padding: 14px 15px; border-bottom: 1px solid var(--border-subtle); background: color-mix(in srgb, var(--brand-subtle) 55%, var(--surface-raised)); }
.notification-head__icon { width: 34px; height: 34px; display: grid; place-items: center; flex: 0 0 34px; border-radius: 10px; background: var(--brand-subtle-2); color: var(--text-brand); font-size: 14px; }
.notification-head__copy { min-width: 0; display: flex; flex: 1; flex-direction: column; gap: 1px; }
.notification-head__copy strong { color: var(--text-strong); font-size: 14px; }
.notification-head__copy small { color: var(--text-muted); font-size: 10.5px; }
.notification-read-all { display: inline-flex; align-items: center; gap: 5px; padding: 6px 8px; border: 0; border-radius: 7px; background: transparent; color: var(--text-brand); cursor: pointer; font: 650 10.5px var(--font-sans); }
.notification-read-all:hover { background: var(--brand-subtle-2); }
.notification-list { max-height: min(475px, calc(100vh - 180px)); overflow-y: auto; overscroll-behavior: contain; }
.notification-item { position: relative; width: 100%; display: flex; align-items: flex-start; gap: 11px; padding: 12px 14px; border: 0; border-bottom: 1px solid var(--border-subtle); background: var(--surface-raised); color: var(--text-body); text-align: left; cursor: pointer; transition: background-color var(--dur-fast); }
.notification-item:last-child { border-bottom: 0; }
.notification-item:hover { background: var(--surface-hover); }
.notification-item.unread { background: color-mix(in srgb, var(--brand) 6%, var(--surface-raised)); }
.notification-item.unread::before { content: ""; position: absolute; inset: 9px auto 9px 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--brand); }
.notification-item__icon { position: relative; width: 38px; height: 38px; display: grid; place-items: center; flex: 0 0 38px; border-radius: 11px; background: var(--info-subtle); color: var(--info-text); font-size: 15px; }
.notification-item__icon.success { background: var(--success-subtle); color: var(--success-text); }
.notification-item__icon.warning { background: var(--warning-subtle); color: var(--warning-text); }
.notification-item__icon.error { background: var(--danger-subtle); color: var(--danger-text); }
.notification-item__level { position: absolute; right: -3px; bottom: -3px; display: grid; place-items: center; width: 15px; height: 15px; border: 2px solid var(--surface-raised); border-radius: 50%; background: var(--surface-raised); font-size: 11px; }
.notification-copy { min-width: 0; display: flex; flex: 1; flex-direction: column; gap: 3px; }
.notification-copy strong { overflow: hidden; color: var(--text-strong); font-size: 12.5px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.notification-meta { display: flex; align-items: center; gap: 5px; color: var(--text-subtle); font-size: 9.5px; font-weight: 650; text-transform: uppercase; letter-spacing: .045em; }
.notification-meta > i { font-size: 3px; }
.notification-meta time { font-weight: 500; text-transform: none; letter-spacing: 0; }
.notification-body { display: -webkit-box; overflow: hidden; color: var(--text-muted); font-size: 11.5px; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.notification-item__end { min-height: 38px; display: flex; align-items: center; gap: 6px; color: var(--text-subtle); font-size: 10px; }
.notification-unread { width: 7px; height: 7px; border-radius: 50%; background: var(--brand); box-shadow: 0 0 0 3px var(--brand-subtle); }
.notification-empty { min-height: 190px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; padding: 28px 16px; color: var(--text-muted); text-align: center; }
.notification-empty__icon { width: 42px; height: 42px; display: grid; place-items: center; margin-bottom: 3px; border-radius: 12px; background: var(--brand-subtle); color: var(--text-brand); font-size: 17px; }
.notification-empty__icon.success { background: var(--success-subtle); color: var(--success-text); }
.notification-empty strong { color: var(--text-strong); font-size: 13px; }
.notification-empty small { font-size: 11px; }
.notification-footer { padding: 7px; border-top: 1px solid var(--border-subtle); background: var(--surface-sunken); }
.notification-footer button { width: 100%; display: flex; align-items: center; justify-content: center; gap: 7px; min-height: 32px; border: 0; border-radius: 8px; background: transparent; color: var(--text-brand); cursor: pointer; font: 650 11.5px var(--font-sans); }
.notification-footer button:hover { background: var(--brand-subtle); }
.notification-footer .pi-arrow-right { font-size: 9px; }
/* Celular: só a página atual (o caminho inteiro não cabe e vira reticências). */
@media (max-width: 640px) {
  .crumbs > i, .crumbs > span:not(.current) { display: none; }
  .crumbs .current { font-size: 14px; }
  .notification-panel { position: fixed; top: calc(var(--topbar-h) + 8px); right: 8px; left: 8px; width: auto; }
  .notification-read-all span { display: none; }
}
@media (max-width: 760px) { .search { width: 32px; padding: 0; justify-content: center; } .search span, .search kbd { display: none; } }
</style>
