<script setup lang="ts">
import Skeleton from "primevue/skeleton";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { type AppNotification, notificationsApi } from "@/api/notifications";
import PageHeader from "@/components/common/PageHeader.vue";
import { buildNavigation } from "@/components/layout/navigation";
import { useSession } from "@/stores/session";
import { NOTIFICATION_CATEGORIES, NOTIFICATION_LEVELS, notificationRelative } from "@/utils/notifications";

const session = useSession();
const router = useRouter();
const loading = ref(true);
const updates = ref<AppNotification[]>([]);
const activityFilter = ref<"all" | "unread">("all");
const unreadUpdates = computed(() => updates.value.filter((item) => !item.read_at).length);
const visibleUpdates = computed(() => activityFilter.value === "unread" ? updates.value.filter((item) => !item.read_at) : updates.value);
const shortcuts = computed(() => buildNavigation(session.can, session.hasModule)
  .flatMap((group) => group.items.map((item) => ({ ...item, group: group.label })))
  .filter((item) => item.to !== "/").slice(0, 12));

onMounted(async () => {
  const page = await notificationsApi.list().catch(() => null);
  updates.value = page?.results.slice(0, 6) ?? [];
  loading.value = false;
});

async function openUpdate(item: AppNotification) {
  if (!item.read_at) item.read_at = (await notificationsApi.read(item.id)).read_at;
  if (item.url) await router.push(item.url);
}

async function readAllUpdates() {
  await notificationsApi.readAll();
  const now = new Date().toISOString();
  updates.value.forEach((item) => (item.read_at ??= now));
}
</script>

<template>
  <section class="page dashboard">
    <PageHeader title="Olá, seja bem-vindo" icon="pi pi-th-large"
                :subtitle="`${session.me?.name ?? 'Usuário'} · ${session.activeStore?.name ?? 'Todas as minhas filiais'}`" />

    <section class="dashboard-section">
      <div class="section-heading">
        <div><span>ACESSO RÁPIDO</span><h2>O que você pode fazer</h2></div>
        <p>Os atalhos acompanham seu cargo, módulos e permissões.</p>
      </div>
      <div class="shortcuts">
        <button v-for="item in shortcuts" :key="item.to" type="button" class="shortcut" @click="router.push(item.to)">
          <span class="shortcut-icon"><i :class="item.icon" /></span>
          <span><strong>{{ item.label }}</strong><small>{{ item.group }}</small></span>
          <i class="pi pi-arrow-right" />
        </button>
        <div v-if="!shortcuts.length" class="empty">Seu administrador ainda não liberou atalhos para este perfil.</div>
      </div>
    </section>

    <section class="dashboard-section">
      <div class="section-heading">
        <div><span>ATIVIDADE</span><h2>Últimas atualizações para você</h2></div>
        <p>Somente eventos das áreas que fazem parte do seu perfil.</p>
      </div>
      <div class="activity-card">
        <header class="activity-toolbar">
          <div class="activity-tabs" role="tablist" aria-label="Filtrar atividades">
            <button type="button" :class="{ active: activityFilter === 'all' }" role="tab" :aria-selected="activityFilter === 'all'"
                    @click="activityFilter = 'all'">Todas <span>{{ updates.length }}</span></button>
            <button type="button" :class="{ active: activityFilter === 'unread' }" role="tab" :aria-selected="activityFilter === 'unread'"
                    @click="activityFilter = 'unread'">Não lidas <span>{{ unreadUpdates }}</span></button>
          </div>
          <button v-if="unreadUpdates" type="button" class="activity-read" @click="readAllUpdates">
            <i class="pi pi-check-circle" /> Marcar todas como lidas
          </button>
          <span v-else class="activity-ok"><i class="pi pi-check" /> Tudo em dia</span>
        </header>
        <div v-if="loading" class="updates updates--loading"><Skeleton v-for="n in 4" :key="n" height="86px" /></div>
        <div v-else-if="visibleUpdates.length" class="updates">
          <button v-for="item in visibleUpdates" :key="item.id" type="button" class="update"
                  :class="[{ unread: !item.read_at }, `level-${item.level}`]" @click="openUpdate(item)">
            <span class="update-icon" :class="item.level">
              <i :class="NOTIFICATION_CATEGORIES[item.category].icon" />
              <i class="update-level" :class="NOTIFICATION_LEVELS[item.level].icon" :title="NOTIFICATION_LEVELS[item.level].label" />
            </span>
            <span class="update-copy">
              <span class="update-meta">
                <span>{{ NOTIFICATION_CATEGORIES[item.category].label }}</span><i class="pi pi-circle-fill" />
                <time :datetime="item.created_at">{{ notificationRelative(item.created_at) }}</time>
              </span>
              <strong>{{ item.title }}</strong>
              <span>{{ item.body || "Nova atualização disponível." }}</span>
            </span>
            <span class="update-end">
              <span v-if="!item.read_at" class="update-new">Nova</span>
              <i v-if="item.url" class="pi pi-arrow-right" />
            </span>
          </button>
        </div>
        <div v-else class="activity-empty">
          <span><i :class="activityFilter === 'unread' ? 'pi pi-check' : 'pi pi-inbox'" /></span>
          <strong>{{ activityFilter === "unread" ? "Nenhuma notificação pendente" : "Nenhuma atividade recente" }}</strong>
          <small>{{ activityFilter === "unread" ? "Você já leu todas as atualizações." : "Novas atividades aparecerão aqui." }}</small>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.dashboard { gap: 28px; }
.dashboard-section { display: flex; flex-direction: column; gap: 14px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; }
.section-heading span { color: var(--brand); font-size: 10px; font-weight: 800; letter-spacing: .11em; }
.section-heading h2 { margin: 3px 0 0; color: var(--text-strong); font-size: 18px; }
.section-heading p { margin: 0; color: var(--text-muted); font-size: 12px; }
.shortcuts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(245px, 100%), 1fr)); gap: 10px; }
.shortcut { min-height: 78px; display: flex; align-items: center; gap: 12px; padding: 14px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface-card); color: var(--text); text-align: left; cursor: pointer; transition: border-color var(--dur-fast), transform var(--dur-fast), box-shadow var(--dur-fast); }
.shortcut:hover { transform: translateY(-1px); border-color: var(--border-strong); box-shadow: var(--shadow-sm); }
.shortcut-icon { width: 42px; height: 42px; flex: 0 0 42px; display: grid; place-items: center; border-radius: 10px; background: var(--brand-subtle); color: var(--brand); font-size: 17px; }
.shortcut > span:nth-child(2) { min-width: 0; display: flex; flex: 1; flex-direction: column; gap: 4px; }
.shortcut strong { overflow: hidden; color: var(--text-strong); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.shortcut small { color: var(--text-muted); font-size: 10.5px; }
.shortcut > .pi-arrow-right { color: var(--text-subtle); font-size: 11px; }
.activity-card { overflow: hidden; border: 1px solid var(--border); border-radius: 13px; background: var(--surface-card); box-shadow: var(--shadow-xs); }
.activity-toolbar { min-height: 49px; display: flex; align-items: center; gap: 12px; padding: 7px 11px; border-bottom: 1px solid var(--border-subtle); background: var(--surface-sunken); }
.activity-tabs { display: inline-flex; gap: 3px; padding: 3px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-card); }
.activity-tabs button { display: flex; align-items: center; gap: 6px; min-height: 28px; padding: 0 9px; border: 0; border-radius: 6px; background: transparent; color: var(--text-muted); cursor: pointer; font: 650 11.5px var(--font-sans); }
.activity-tabs button:hover { color: var(--text-strong); }
.activity-tabs button.active { background: var(--brand-subtle); color: var(--text-brand); }
.activity-tabs button span { min-width: 18px; padding: 1px 5px; border-radius: 999px; background: var(--surface-sunken); color: inherit; font-size: 9.5px; text-align: center; }
.activity-read { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 0 8px; border: 0; border-radius: 7px; background: transparent; color: var(--text-brand); cursor: pointer; font: 650 11px var(--font-sans); }
.activity-read:hover { background: var(--brand-subtle); }
.activity-ok { margin-left: auto; display: inline-flex; align-items: center; gap: 5px; color: var(--success-text); font-size: 10.5px; font-weight: 650; }
.updates { display: flex; flex-direction: column; }
.updates--loading { gap: 8px; padding: 10px; }
.update { position: relative; display: flex; align-items: center; gap: 13px; min-height: 84px; padding: 12px 14px; border: 0; border-bottom: 1px solid var(--border-subtle); background: var(--surface-card); color: var(--text-body); text-align: left; cursor: pointer; transition: background-color var(--dur-fast), transform var(--dur-fast); }
.update:last-child { border-bottom: 0; }
.update:hover { z-index: 1; background: var(--surface-hover); }
.update.unread { background: color-mix(in srgb, var(--brand) 4%, var(--surface-card)); }
.update.unread::before { content: ""; position: absolute; inset: 14px auto 14px 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--brand); }
.update-icon { position: relative; width: 42px; height: 42px; display: grid; place-items: center; flex: 0 0 42px; border-radius: 12px; background: var(--info-subtle); color: var(--info-text); font-size: 17px; }
.update-icon.success { background: var(--success-subtle); color: var(--success-text); }
.update-icon.warning { background: var(--warning-subtle); color: var(--warning-text); }
.update-icon.error { background: var(--danger-subtle); color: var(--danger-text); }
.update-level { position: absolute; right: -4px; bottom: -4px; width: 17px; height: 17px; display: grid; place-items: center; border: 2px solid var(--surface-card); border-radius: 50%; background: var(--surface-card); font-size: 12px; }
.update-copy { min-width: 0; display: flex; flex: 1; flex-direction: column; gap: 3px; }
.update-meta { display: flex; align-items: center; gap: 6px; color: var(--text-subtle); font-size: 9.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.update-meta i { font-size: 3px; }
.update-meta time { font-weight: 500; letter-spacing: 0; text-transform: none; }
.update-copy strong { color: var(--text-strong); font-size: 13px; line-height: 1.35; }
.update-copy > span:last-child { display: -webkit-box; overflow: hidden; color: var(--text-muted); font-size: 11.5px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.update-end { display: flex; align-items: center; gap: 10px; color: var(--text-subtle); font-size: 11px; }
.update-new { padding: 3px 7px; border-radius: 999px; background: var(--brand-subtle); color: var(--text-brand); font-size: 9.5px; font-weight: 750; text-transform: uppercase; }
.activity-empty { min-height: 210px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; padding: 28px; color: var(--text-muted); text-align: center; }
.activity-empty > span { width: 44px; height: 44px; display: grid; place-items: center; margin-bottom: 4px; border-radius: 13px; background: var(--success-subtle); color: var(--success-text); font-size: 18px; }
.activity-empty strong { color: var(--text-strong); font-size: 13.5px; }
.activity-empty small { font-size: 11.5px; }
.empty { grid-column: 1 / -1; padding: 28px; border: 1px dashed var(--border); border-radius: 10px; color: var(--text-muted); text-align: center; font-size: 12px; }
@media (max-width: 640px) {
  .section-heading { align-items: start; flex-direction: column; gap: 5px; }
  .activity-toolbar { align-items: stretch; flex-direction: column; }
  .activity-tabs { align-self: stretch; }
  .activity-tabs button { flex: 1; justify-content: center; }
  .activity-read, .activity-ok { align-self: flex-end; margin-left: 0; }
  .update { align-items: flex-start; padding-inline: 12px; }
  .update-end { align-self: center; }
  .update-new { display: none; }
}
</style>
