<script setup lang="ts">
/**
 * Formulário de QUALQUER cadastro: criar, ver/editar e excluir.
 *
 * Cada seção: título e explicação em cima, campos embaixo numa grade de 6
 * colunas usando a largura toda. Atalhos: Ctrl+S
 * salva, Ctrl+Enter "salva e cria outro", Esc volta para a lista.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import Message from "primevue/message";
import Skeleton from "primevue/skeleton";
import { useConfirm } from "primevue/useconfirm";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate, type RouteLocationNormalized, useRoute, useRouter } from "vue-router";

import { resourceApi } from "@/api/resource";
import FormField from "@/components/resource/FormField.vue";
import { useNotify } from "@/composables/useNotify";
import { useResourceForm } from "@/composables/useResourceForm";
import { findResource } from "@/resources";
import FormActions from "@/components/resource/FormActions.vue";
import RecordTabs from "@/components/resource/RecordTabs.vue";
import RecordView from "@/components/resource/RecordView.vue";
import HistoryFeed from "@/components/view/HistoryFeed.vue";
import { type FieldDef, newLabel, type ResourceDef } from "@/resources/types";
import { useSession } from "@/stores/session";
import { type Draft, loadDraft, removeDraft, saveDraft } from "@/utils/drafts";
import { dateTime } from "@/utils/format";

const route = useRoute();
const router = useRouter();
const session = useSession();
const notify = useNotify();
const confirm = useConfirm();

const resource = computed(() => findResource(String(route.params.resource)) as ResourceDef);
const id = computed(() => (route.params.id === "novo" ? null : String(route.params.id)));
const { values, errors, loading, saving, isNew, load, save } = useResourceForm(resource, id);
const canWrite = computed(() => !resource.value.readOnly && session.can(`${resource.value.permission}.manage`)
  && (isNew.value || resource.value.editable !== false) && !resource.value.lockedWhen?.(values.value));
/** Sem edição (confirmado, só leitura, sem permissão): página de leitura em vez de campos desabilitados. */
const viewing = computed(() => !isNew.value && !canWrite.value);
const badges = computed(() => (loading.value || isNew.value ? []
  : (resource.value.display?.badges?.(values.value) ?? []).filter((b) => !!b)));
const snapshot = ref("");
const dirty = computed(() => canWrite.value && !loading.value && JSON.stringify(values.value) !== snapshot.value);
const errorCount = computed(() => Object.keys(errors.value).length);

/*
 * Rascunho: sair com alterações pergunta o que fazer — continuar editando,
 * descartar ou GUARDAR RASCUNHO (fica neste navegador para terminar depois).
 * Fechar/recarregar a aba no meio da edição guarda o rascunho sozinho.
 * Voltando ao registro, o aviso oferece "Continuar de onde parei".
 */
const draftScope = computed(() => `${session.me?.account?.id ?? "-"}:${session.me?.id ?? "-"}`);
const draftRecord = computed(() => id.value ?? "novo");
const draft = ref<Draft | null>(null);
const leaveTo = ref<string | null>(null);
let leaving = false;
function keepDraft() {
  saveDraft(draftScope.value, resource.value.name, draftRecord.value, values.value, title.value);
}
function dropDraft() {
  removeDraft(draftScope.value, resource.value.name, draftRecord.value);
  draft.value = null;
}
/** Volta para onde a pessoa ia, sem perguntar de novo. */
function go() {
  const to = leaveTo.value ?? listPath.value;
  leaveTo.value = null;
  leaving = true;
  void router.push(to).finally(() => (leaving = false));
}
function leaveKeepingDraft() {
  keepDraft();
  notify.success("Rascunho guardado: abra o cadastro de novo para continuar");
  go();
}
function leaveDiscarding() {
  dropDraft();
  go();
}
function restoreDraft() {
  if (!draft.value) return;
  values.value = { ...values.value, ...draft.value.values };
  draft.value = null;
  notify.success("Rascunho recuperado: revise e salve");
}
/** Sair (ou trocar de registro) com alterações abre o diálogo em vez de sair direto. */
function guard(to: RouteLocationNormalized) {
  if (leaving || !dirty.value) return true;
  leaveTo.value = to.fullPath;
  return false;
}
onBeforeRouteLeave(guard);
onBeforeRouteUpdate(guard);
function onUnload(event: BeforeUnloadEvent) {
  if (!dirty.value) return;
  keepDraft();
  event.preventDefault();
}
const listPath = computed(() => `/cadastros/${resource.value.name}`);
/** Título do registro: nome, descrição, código... ou "Documento 12" para o que só tem número. */
const title = computed(() => {
  if (isNew.value) return newLabel(resource.value);
  const v = values.value;
  const named = v.name ?? v.display_name ?? v.description ?? v.code ?? v.username ?? v.register_name ?? v.variant_name;
  if (named) return String(named);
  const singular = resource.value.singular;
  return v.number ? `${singular[0]!.toUpperCase()}${singular.slice(1)} ${v.number}` : resource.value.title;
});

const sections = computed(() => {
  const groups = new Map<string, FieldDef[]>();
  for (const field of resource.value.fields) {
    if (field.visible && !field.visible(values.value)) continue;
    if (field.createOnly && !isNew.value) continue;
    const name = field.section ?? "Dados";
    groups.set(name, [...(groups.get(name) ?? []), field]);
  }
  return [...groups.entries()];
});
/** Quantas seções e campos o skeleton desenha: o mesmo formato da tela pronta. */
const skeletonSections = computed(() => {
  const counts = new Map<string, number>();
  resource.value.fields.forEach((f) => counts.set(f.section ?? "Dados", (counts.get(f.section ?? "Dados") ?? 0) + 1));
  return [...counts.values()].slice(0, 4).map((n) => Math.min(n, 6));
});

/** Seção que é só um editor de texto: o editor vira o próprio cartão (sem caixa dentro de caixa). */
const isBare = (fields: FieldDef[]) => fields.length === 1 && fields[0]!.type === "richtext";

/** Valores que um campo trouxe (o CEP com o endereço): só entram os campos que este cadastro tem. */
function fill(patch: Record<string, string>) {
  const names = new Set(resource.value.fields.map((f) => f.name));
  values.value = { ...values.value, ...Object.fromEntries(Object.entries(patch).filter(([k, v]) => names.has(k) && v)) };
}

async function reload(force = false) {
  await load(force);
  // Cadastro novo aceita valores pela URL: ".../entradas-e-saidas/novo?kind=exit" já abre como saída.
  if (isNew.value) {
    const names = new Set(resource.value.fields.map((f) => f.name));
    for (const [key, value] of Object.entries(route.query)) if (names.has(key) && typeof value === "string") values.value[key] = value;
  }
  snapshot.value = JSON.stringify(values.value);
  draft.value = canWrite.value ? loadDraft(draftScope.value, resource.value.name, draftRecord.value) : null;
}

async function submit(another = false) {
  if (saving.value || !canWrite.value) return;
  if (another && !dirty.value && !isNew.value) return void router.push(`${listPath.value}/novo`);
  // Campo numérico só entrega o valor ao perder o foco: no Ctrl+S o cursor ainda está nele.
  (document.activeElement as HTMLElement | null)?.blur();
  await nextTick();
  try {
    const saved = await save();
    if (!saved) return notify.warn("Confira os campos destacados.");
    dropDraft();  // salvou de verdade: o rascunho não serve mais
    snapshot.value = JSON.stringify(values.value);
    notify.success(isNew.value ? "Cadastro criado" : "Alterações salvas");
    if (another) {
      if (isNew.value) await reload();
      else router.push(`${listPath.value}/novo`);
    } else if (isNew.value) {
      router.replace(`${listPath.value}/${saved.id}`);
    }
  } catch (error) {
    notify.error(error, "Não foi possível salvar");
  }
}

function remove() {
  confirm.require({
    message: `Excluir este ${resource.value.singular}? A ação fica registrada na auditoria.`,
    header: "Confirmar exclusão", icon: "pi pi-exclamation-triangle",
    acceptProps: { label: "Excluir", severity: "danger" },
    rejectProps: { label: "Cancelar", severity: "secondary", outlined: true },
    accept: async () => {
      try {
        await resourceApi.remove(resource.value.endpoint, id.value!);
        snapshot.value = JSON.stringify(values.value);
        notify.success("Excluído");
        router.push(listPath.value);
      } catch (error) {
        notify.error(error, "Não foi possível excluir");
      }
    },
  });
}

function onKey(event: KeyboardEvent) {
  const mod = event.ctrlKey || event.metaKey;
  if (mod && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void submit();
  } else if (mod && event.key === "Enter") {
    event.preventDefault();
    void submit(true);
  } else if (event.key === "Escape" && !document.querySelector(".p-dialog, .p-select-overlay, .p-multiselect-overlay")) {
    router.push(listPath.value);
  }
}

onMounted(() => {
  void reload();
  window.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", onUnload);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("beforeunload", onUnload);
});
watch([resource, id], () => reload());
</script>

<template>
  <form class="page form-page" @submit.prevent="submit()">
    <header class="head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" size="small" :aria-label="`Voltar para ${resource.title}`"
              @click="router.push(listPath)" />
      <div class="head__text">
        <div class="head__title">
          <h1>{{ title }}</h1>
          <span v-if="!isNew && values.is_active === false" class="pill pill--neutral">Inativo</span>
          <span v-for="badge in badges" :key="badge.label" class="pill" :class="`pill--${badge.tone ?? 'brand'}`">
            <i v-if="badge.icon" :class="badge.icon" /> {{ badge.label }}
          </span>
        </div>
        <p>{{ isNew ? `Preencha os dados do ${resource.singular}` : `${resource.group} · ${resource.title}` }}</p>
      </div>
      <FormActions v-if="!isNew && !loading && resource.formActions?.length" :actions="resource.formActions"
                   :ctx="{ id: id!, values, reload: () => reload(true) }" class="head__actions" />
    </header>

    <RecordTabs v-if="!isNew && resource.views?.length" :resource="resource" :id="id!" active="dados" />

    <div v-if="draft && !loading" class="draft-banner" role="status">
      <i class="pi pi-file-edit" />
      <p><b>Você tem um rascunho {{ resource.feminine ? "desta" : "deste" }} {{ resource.singular }}</b>, guardado em {{ dateTime(draft.savedAt) }}.
        Continue de onde parou ou descarte para começar do que está salvo.</p>
      <Button label="Continuar de onde parei" icon="pi pi-replay" size="small" @click="restoreDraft" />
      <Button label="Descartar rascunho" severity="secondary" text size="small" @click="dropDraft" />
    </div>

    <Message v-if="errorCount" severity="error" :closable="false">
      {{ errorCount === 1 ? "1 campo precisa de atenção." : `${errorCount} campos precisam de atenção.` }}
      <span v-if="errors.non_field_errors || errors.detail"> {{ errors.non_field_errors || errors.detail }}</span>
    </Message>

    <div v-if="loading" class="sections" aria-busy="true" aria-label="Carregando">
      <section v-for="(count, index) in skeletonSections" :key="index" class="fsec">
        <div class="fsec__aside"><Skeleton width="7rem" height="0.9rem" /><Skeleton width="16rem" height="0.7rem" /></div>
        <div class="fsec__card grid-form">
          <div v-for="n in count" :key="n" class="field">
            <Skeleton width="40%" height="0.7rem" /><Skeleton height="2.25rem" border-radius="7px" />
          </div>
        </div>
      </section>
    </div>
    <component :is="resource.summary" v-if="!isNew && !loading && resource.summary"
               :ctx="{ id: id!, values, reload: () => reload(true) }" />
    <RecordView v-if="!loading && viewing" :resource="resource" :ctx="{ id: id!, values, reload: () => reload(true) }" />
    <fieldset v-else-if="!loading && sections.length" :disabled="!canWrite" class="sections">
      <section v-for="[name, fields] in sections" :key="name" class="fsec">
        <div class="fsec__aside">
          <h2><i v-if="resource.sections?.[name]?.icon" :class="resource.sections?.[name]?.icon" /> {{ name }}</h2>
          <p v-if="resource.sections?.[name]?.description">{{ resource.sections?.[name]?.description }}</p>
        </div>
        <div class="fsec__card grid-form" :class="{ 'fsec__card--bare': isBare(fields) }">
          <FormField v-for="field in fields" :key="field.name" v-model="values[field.name]" :field="field" :bare="isBare(fields)"
                     :error="errors[field.name]" :context="values"
                     :disabled="!canWrite || (field.readOnly && !session.me?.is_superuser)" @reload="reload(true)" @fill="fill" />
        </div>
      </section>
    </fieldset>

    <!-- Histórico sempre no fim da página, em qualquer registro já salvo (feed com rolagem própria). -->
    <HistoryFeed v-if="!isNew && !loading" :resource="resource" :id="id!" :version="values.updated_at" />

    <div v-if="canWrite" class="actionbar" :class="{ 'actionbar--dirty': dirty }">
      <span class="actionbar__status">
        <i :class="dirty ? 'pi pi-circle-fill' : 'pi pi-check-circle'" />
        <span>{{ dirty ? "Alterações não salvas" : isNew ? "Novo cadastro" : "Tudo salvo" }}</span>
        <span class="hint"><kbd class="kbd">Ctrl S</kbd> salva</span>
      </span>
      <div class="actionbar__buttons">
        <Button v-if="!isNew && resource.deletable !== false && !(resource.systemData && !session.me?.is_superuser)"
                icon="pi pi-trash" severity="danger" text size="small"
                aria-label="Excluir" title="Excluir" @click="remove" />
        <Button v-if="dirty" label="Guardar rascunho" icon="pi pi-bookmark" severity="secondary" text size="small"
                title="Guarda as alterações neste navegador para terminar depois" class="another" :disabled="saving"
                @click="leaveKeepingDraft" />
        <Button label="Salvar e novo" severity="secondary" outlined size="small" title="Ctrl+Enter" class="another"
                :disabled="saving" @click="submit(true)" />
        <Button type="submit" label="Salvar" icon="pi pi-check" size="small" :loading="saving" :disabled="!dirty && !isNew" />
      </div>
    </div>
    <!-- Sair com alterações não salvas: continuar, descartar ou guardar rascunho. -->
    <Dialog :visible="leaveTo !== null" modal header="Alterações não salvas" :closable="true" :draggable="false"
            :style="{ width: 'min(580px, calc(100vw - 24px))' }" @update:visible="leaveTo = null">
      <div class="leave">
        <span class="leave__icon"><i class="pi pi-exclamation-triangle" /></span>
        <p>Você mudou {{ resource.feminine ? "esta" : "este" }} {{ resource.singular }} e ainda não salvou. O que fazer com as alterações?</p>
      </div>
      <ul class="leave__options">
        <li><b>Guardar rascunho</b> — ficam neste navegador; ao voltar, você continua de onde parou.</li>
        <li><b>Descartar</b> — volta para o que está salvo; as alterações se perdem.</li>
      </ul>
      <template #footer>
        <Button label="Continuar editando" severity="secondary" text @click="leaveTo = null" />
        <Button label="Descartar" icon="pi pi-trash" severity="danger" outlined @click="leaveDiscarding" />
        <Button label="Guardar rascunho" icon="pi pi-bookmark" autofocus @click="leaveKeepingDraft" />
      </template>
    </Dialog>
  </form>
</template>

<style scoped>
.form-page { padding-bottom: 5rem; }
.draft-banner {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 14px; border-radius: 10px;
  background: var(--warning-subtle); color: var(--warning-text); border: 1px solid color-mix(in srgb, var(--warning) 35%, transparent);
}
.draft-banner > i { font-size: 18px; }
.draft-banner p { margin: 0; flex: 1; min-width: 240px; font-size: 13.5px; color: var(--text-body); }
.draft-banner p b { color: var(--text-strong); }
.leave { display: flex; gap: 12px; align-items: flex-start; }
.leave__icon {
  flex: none; width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center;
  background: var(--warning-subtle); color: var(--warning-text);
}
.leave p { margin: 6px 0 0; font-size: 14px; color: var(--text-body); }
.leave__options { margin: 12px 0 0 48px; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px;
                  font-size: 13px; color: var(--text-muted); }
.leave__options b { color: var(--text-strong); }
.head { display: flex; align-items: center; gap: 0.5rem; }
.head__text { min-width: 0; }
.head__title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.head__title .pill i { font-size: 11px; }
.head__actions { margin-left: auto; }
h1 { font: 700 19px/1.2 var(--font-sans); letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.head__text p { font-size: 12.5px; color: var(--text-muted); }
.sections { border: 0; padding: 0; margin: 0; min-width: 0; display: flex; flex-direction: column; }
/* Seção = coluna explicativa (esquerda) + cartão com os campos (direita). */
/* Seção = título com explicação em cima + cartão com os campos embaixo (largura toda). */
.fsec { display: flex; flex-direction: column; gap: 0.6rem; padding: 1rem 0 0; }
.fsec:first-child { padding-top: 0.25rem; }
.fsec__aside { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; padding: 0 2px; }
.fsec__aside h2 { display: flex; align-items: center; gap: 0.45rem; font: 600 14px/1.3 var(--font-sans); }
.fsec__aside h2 i { font-size: 13px; color: var(--brand); }
.fsec__aside p { font-size: 12.5px; line-height: 1.5; color: var(--text-muted); }
.fsec__card { background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; padding: 1rem 1.1rem; box-shadow: var(--shadow-xs); }
.fsec__card--bare { padding: 0; display: block; }
.actionbar {
  position: sticky; bottom: 12px; z-index: 10; display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding: 8px 8px 8px 14px; border-radius: 10px; border: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface-raised) 92%, transparent); backdrop-filter: blur(8px); box-shadow: var(--shadow-md);
}
.actionbar--dirty { border-color: var(--brand-border); }
.actionbar__status { display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 600; color: var(--text-muted); min-width: 0; }
.actionbar__status > i { font-size: 9px; color: var(--success); }
.actionbar--dirty .actionbar__status { color: var(--text-strong); }
.actionbar--dirty .actionbar__status > i { color: var(--accent); }
.actionbar__status .hint { font-weight: 500; color: var(--text-subtle); margin-left: 6px; }
.actionbar__buttons { display: flex; gap: 0.4rem; }
@media (max-width: 640px) {
  /* Celular: as ações descem para uma linha própria que rola para o lado (não esmagam o título). */
  .head { flex-wrap: wrap; row-gap: 10px; }
  .head__text { flex: 1; }
  .head__title { gap: 6px; }
  h1 { font-size: 18px; white-space: normal; }
  .head__actions { order: 3; flex: 1 1 100%; margin: 0 -16px; padding: 0 16px 2px; flex-wrap: nowrap; overflow-x: auto;
                   justify-content: flex-start; scrollbar-width: none; }
  .head__actions :deep(.p-button) { flex: none; }
}
@media (max-width: 560px) {
  .actionbar { padding: 6px; gap: 0.4rem; }
  .actionbar__status > span, .another { display: none; }
  .actionbar__buttons { flex: 1; justify-content: flex-end; }
  .fsec__card { padding: 0.85rem; }
}
</style>
