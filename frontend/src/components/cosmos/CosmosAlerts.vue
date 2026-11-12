<script setup lang="ts">
/** Alertas da supervisão: o que está errado, quem fez, e os atalhos para corrigir. */
import Button from "primevue/button";
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import type { CosmosFinding } from "@/api/cosmos";
import { useCosmos } from "@/stores/cosmos";
import { dateTime } from "@/utils/format";

import { recordLabel, recordLink } from "./links";

const cosmos = useCosmos();
const router = useRouter();
const ICONS = { critical: "pi pi-exclamation-circle", warning: "pi pi-exclamation-triangle", info: "pi pi-info-circle" };
const link = (f: CosmosFinding) => recordLink(f.endpoint, f.entity === "sale" && !f.object_id ? null : f.object_id || null);

onMounted(() => cosmos.loadAlerts());
</script>

<template>
  <div class="alerts">
    <p class="intro">Eu confiro o que a equipe grava e aviso aqui quando algo sai errado — sem você precisar perguntar.</p>
    <div v-if="!cosmos.alerts.length" class="empty"><i class="pi pi-check-circle" /> Nada fora do lugar agora.</div>
    <article v-for="f in cosmos.alerts" :key="f.id" class="alert" :class="`alert--${f.severity}`">
      <i class="alert__icon" :class="ICONS[f.severity]" />
      <div class="alert__body">
        <div class="alert__top">
          <strong class="alert__title" :title="f.title">{{ f.title }}</strong>
          <div class="alert__quick">
            <button type="button" title="Marcar como resolvido" aria-label="Marcar como resolvido"
                    @click="cosmos.resolveAlert(f, 'resolved')"><i class="pi pi-check" /></button>
            <button type="button" title="Descartar" aria-label="Descartar"
                    @click="cosmos.resolveAlert(f, 'dismissed')"><i class="pi pi-eye-slash" /></button>
          </div>
        </div>
        <small class="alert__meta">
          <span class="alert__who">{{ f.actor ?? "Autor não identificado" }}</span> · {{ dateTime(f.created_at) }}
        </small>
        <p v-if="f.detail" class="alert__detail">{{ f.detail }}</p>
        <div class="alert__actions">
          <Button label="Corrigir com a Cosmos" icon="pi pi-sparkles" size="small" @click="cosmos.fixWithCosmos(f)" />
          <Button v-if="link(f)" label="Abrir" icon="pi pi-arrow-up-right" icon-pos="right" size="small" text
                  :title="`Abrir ${recordLabel(f.endpoint)}`" @click="router.push(link(f)!)" />
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.alerts { padding: 12px; display: grid; gap: 8px; align-content: start; }
.intro { margin: 0 2px 2px; font-size: 12.5px; color: var(--text-muted); line-height: 1.45; }
.empty { padding: 24px; text-align: center; color: var(--success-text); font-size: 13px; display: flex; gap: 8px;
         justify-content: center; align-items: center; }
.alert { display: flex; gap: 10px; padding: 10px 10px 10px 12px; border: 1px solid var(--border);
         border-left: 3px solid var(--info); border-radius: var(--radius-md); background: var(--surface-card); }
.alert--warning { border-left-color: var(--warning); }
.alert--critical { border-left-color: var(--danger); }
.alert__icon { margin-top: 2px; font-size: 14px; color: var(--info-text); }
.alert--warning .alert__icon { color: var(--warning-text); }
.alert--critical .alert__icon { color: var(--danger-text); }
.alert__body { flex: 1; min-width: 0; display: grid; gap: 4px; }
.alert__top { display: flex; gap: 6px; align-items: flex-start; }
/* Título em até 2 linhas; o resto fica no detalhe. */
.alert__title { flex: 1; min-width: 0; font-size: 13px; line-height: 1.35; color: var(--text-strong);
                display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.alert__quick { display: flex; gap: 2px; margin: -4px -4px 0 0; flex-shrink: 0; }
.alert__quick button { width: 26px; height: 26px; display: grid; place-items: center; border: 0; border-radius: 6px;
                       background: transparent; color: var(--text-subtle); cursor: pointer; }
.alert__quick button:hover { background: var(--surface-hover); color: var(--text-strong); }
.alert__quick .pi { font-size: 12px; }
.alert__meta { font-size: 11.5px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.alert__who { font-weight: 600; color: var(--text-body); }
.alert__detail { margin: 0; font-size: 12.5px; line-height: 1.45; color: var(--text-body);
                 display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.alert__actions { display: flex; gap: 4px; align-items: center; margin-top: 2px; flex-wrap: nowrap; }
.alert__actions :deep(.p-button) { white-space: nowrap; }
</style>
