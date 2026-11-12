<script setup lang="ts">
/**
 * O cartão de confirmação: o que a Cosmos quer gravar, campo a campo (com o "de → para" numa
 * alteração), e os botões. Nada é gravado antes do Confirmar; depois, o cartão mostra o resultado
 * e o atalho para o cadastro.
 */
import Button from "primevue/button";
import { computed } from "vue";
import { useRouter } from "vue-router";

import type { CosmosAction } from "@/api/cosmos";

import { recordLabel, recordLink } from "./links";

const props = defineProps<{ action: CosmosAction; busy?: boolean }>();
const emit = defineEmits<{ decide: [approve: boolean] }>();
const router = useRouter();

const VERBS: Record<string, { label: string; icon: string; tone: string }> = {
  POST: { label: "Criar", icon: "pi pi-plus", tone: "brand" },
  PUT: { label: "Alterar", icon: "pi pi-pencil", tone: "warning" },
  PATCH: { label: "Alterar", icon: "pi pi-pencil", tone: "warning" },
  DELETE: { label: "Excluir", icon: "pi pi-trash", tone: "danger" },
};
const STATES: Record<string, { label: string; icon: string; tone: string }> = {
  executed: { label: "Gravado", icon: "pi pi-check-circle", tone: "success" },
  failed: { label: "Não gravou", icon: "pi pi-times-circle", tone: "danger" },
  rejected: { label: "Cancelado", icon: "pi pi-ban", tone: "muted" },
  expired: { label: "Expirado", icon: "pi pi-clock", tone: "muted" },
};
const verb = computed(() => VERBS[props.action.method] ?? VERBS.POST!);
const state = computed(() => STATES[props.action.status]);
const link = computed(() => (props.action.status === "executed" && props.action.method !== "DELETE"
  ? recordLink(props.action.result?.endpoint, props.action.result?.id) : null));
</script>

<template>
  <article class="card" :class="[`card--${verb.tone}`, `card--${action.status}`]">
    <header class="card__head">
      <span class="card__icon"><i :class="verb.icon" /></span>
      <div class="card__titles">
        <small>{{ action.status === "pending" ? "Confirme para gravar" : "Proposta" }} · {{ verb.label }}</small>
        <strong>{{ action.title }}</strong>
      </div>
      <span v-if="state" class="card__state" :class="`state--${state.tone}`"><i :class="state.icon" /> {{ state.label }}</span>
    </header>
    <p v-if="action.summary" class="card__summary">{{ action.summary }}</p>
    <dl v-if="action.preview.length" class="card__fields">
      <template v-for="(row, i) in action.preview" :key="i">
        <dt>{{ row.label }}</dt>
        <dd>
          <template v-if="row.from !== undefined">
            <s>{{ row.from }}</s> <i class="pi pi-arrow-right" /> <b>{{ row.value }}</b>
          </template>
          <template v-else>{{ row.value }}</template>
        </dd>
      </template>
    </dl>
    <p v-if="action.status === 'failed' && action.result?.message" class="card__error">
      <i class="pi pi-exclamation-triangle" /> {{ typeof action.result.message === "string" ? action.result.message : "Erro de validação" }}
    </p>
    <footer v-if="action.status === 'pending'" class="card__actions">
      <Button label="Cancelar" icon="pi pi-times" severity="secondary" text size="small" :disabled="busy"
              @click="emit('decide', false)" />
      <Button :label="action.method === 'DELETE' ? 'Confirmar exclusão' : 'Confirmar'" icon="pi pi-check" size="small"
              :severity="action.method === 'DELETE' ? 'danger' : undefined" :loading="busy" @click="emit('decide', true)" />
    </footer>
    <footer v-else-if="link" class="card__actions">
      <Button :label="`Abrir ${recordLabel(action.result?.endpoint)}`" icon="pi pi-external-link" size="small" outlined
              @click="router.push(link)" />
    </footer>
  </article>
</template>

<style scoped>
.card { border: 1px solid var(--border); border-left: 3px solid var(--brand); border-radius: var(--radius-md);
        background: var(--surface-card); padding: 10px 12px; display: grid; gap: 8px; }
.card--warning { border-left-color: var(--warning); }
.card--danger { border-left-color: var(--danger); }
.card--rejected, .card--expired { opacity: 0.7; }
.card__head { display: flex; gap: 10px; align-items: center; }
.card__icon { width: 28px; height: 28px; flex: none; display: grid; place-items: center; border-radius: 8px;
              background: var(--brand-subtle); color: var(--text-brand); font-size: 12px; }
.card--warning .card__icon { background: var(--warning-subtle); color: var(--warning-text); }
.card--danger .card__icon { background: var(--danger-subtle); color: var(--danger-text); }
.card__titles { min-width: 0; flex: 1; display: grid; }
.card__titles small { font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-subtle); }
.card__titles strong { font-size: 13.5px; color: var(--text-strong); line-height: 1.3; }
.card__state { font-size: 11.5px; font-weight: 700; white-space: nowrap; display: inline-flex; gap: 4px; align-items: center; }
.state--success { color: var(--success-text); }
.state--danger { color: var(--danger-text); }
.state--muted { color: var(--text-muted); }
.card__summary { margin: 0; font-size: 12.5px; color: var(--text-body); }
.card__fields { margin: 0; display: grid; grid-template-columns: minmax(80px, auto) 1fr; gap: 4px 12px; font-size: 12.5px;
                padding: 8px 10px; border-radius: var(--radius-sm); background: var(--surface-sunken); }
.card__fields dt { color: var(--text-muted); }
.card__fields dd { margin: 0; color: var(--text-strong); word-break: break-word; }
.card__fields s { color: var(--text-subtle); }
.card__fields .pi { font-size: 9px; color: var(--text-subtle); margin: 0 2px; }
.card__error { margin: 0; font-size: 12.5px; color: var(--danger-text); display: flex; gap: 6px; }
.card__actions { display: flex; justify-content: flex-end; gap: 6px; }
</style>
