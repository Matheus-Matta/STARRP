<script setup lang="ts">
/**
 * Histórico do registro em "feed" (Timeline do PrimeVue), sempre no fim da página:
 * quem fez o quê e quando — criado, alterado (com o que mudou), conferido,
 * confirmado, cancelado... Carrega 10 por vez e busca mais sozinho quando a
 * rolagem DESTE quadro chega perto do fim.
 *
 * Fonte: GET <cadastro>/<id>/history/ (backend `services/history.py`).
 */
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";
import Timeline from "primevue/timeline";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { resourceApi } from "@/api/resource";
import FieldValue, { type ViewField } from "@/components/view/FieldValue.vue";
import type { ResourceDef } from "@/resources/types";
import { dateTime } from "@/utils/format";

type Change = { key?: string; field: string; from: string; to: string };
type Event = { id: string; kind: string; label: string; tone: string; icon: string; at: string; by: string; note: string;
               changes: Change[] };

/** `version` muda quando o registro é salvo/recarregado: o feed começa de novo. */
const props = defineProps<{ resource: ResourceDef; id: string; version?: unknown }>();
const PAGE = 10;
const rows = ref<Event[]>([]);
const total = ref(0);
const page = ref(0);
const loading = ref(false);
const failed = ref(false);
const done = computed(() => page.value > 0 && rows.value.length >= total.value);
const box = ref<HTMLElement>();
const sentinel = ref<HTMLElement>();
let observer: IntersectionObserver | null = null;

async function more() {
  if (loading.value || done.value) return;
  loading.value = true;
  failed.value = false;
  try {
    const next = page.value + 1;
    const data = await resourceApi.list<Event>(`${props.resource.endpoint}${props.id}/history/`, { page: next, page_size: PAGE });
    rows.value = next === 1 ? data.results : [...rows.value, ...data.results];
    total.value = data.count;
    page.value = next;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

function restart() {
  rows.value = [];
  page.value = 0;
  total.value = 0;
  void more();
}

/** Rolou este quadro até perto do fim: busca a próxima página. */
onMounted(() => {
  restart();
  observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) void more();
  }, { root: box.value, rootMargin: "0px 0px 80px 0px" });
  if (sentinel.value) observer.observe(sentinel.value);
});
onBeforeUnmount(() => observer?.disconnect());
watch(() => [props.id, props.version], restart);

/** O nome do campo como no formulário ("Preço de venda"), não o da coluna no banco. */
const fieldDefs = computed(() => new Map(props.resource.fields.map((f) => [f.name, f])));
function fieldOf(change: Change): ViewField | undefined {
  const key = (change.key ?? "").replace(/_id$/, "");
  return fieldDefs.value.get(key);
}
const labelOf = (change: Change) => fieldOf(change)?.label ?? change.field;
/** Formata o valor com o tipo do campo (dinheiro, opção, nome do relacionado) quando ele é conhecido. */
const asValues = (change: Change, side: "from" | "to") => {
  const field = fieldOf(change);
  return field ? { [field.name]: change[side] === "—" ? null : change[side] } : {};
};

function ago(at: string) {
  const minutes = Math.round((Date.now() - new Date(at).getTime()) / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.round(hours / 24);
  return days < 31 ? `há ${days} ${days === 1 ? "dia" : "dias"}` : dateTime(at);
}
</script>

<template>
  <section class="hf">
    <header class="hf__head">
      <h2><i class="pi pi-history" /> Histórico <small v-if="total">{{ total }}</small></h2>
      <p>Quem fez o quê e quando: criação, alterações (com o que mudou) e cada etapa do registro.</p>
    </header>
    <div ref="box" class="hf__card">
      <div v-if="!page && loading" class="hf__skeleton">
        <div v-for="n in 3" :key="n" class="hf__ghost"><Skeleton shape="circle" size="2rem" /><div>
          <Skeleton width="10rem" height="0.9rem" /><Skeleton width="16rem" height="0.75rem" /></div></div>
      </div>
      <p v-else-if="!rows.length && !loading" class="hf__empty">{{ failed ? "Não foi possível carregar o histórico." : "Nada registrado ainda." }}</p>
      <Timeline v-else :value="rows" align="left" class="hf__timeline" data-key="id">
        <template #marker="{ item }">
          <span class="hf__marker" :class="`tone-${item.tone}`"><i :class="item.icon" /></span>
        </template>
        <template #content="{ item }">
          <article class="hf__event">
            <div class="hf__line">
              <strong>{{ item.label }}</strong>
              <span v-if="item.by" class="hf__by"><i class="pi pi-user" /> {{ item.by }}</span>
              <time :datetime="item.at" :title="dateTime(item.at)">{{ ago(item.at) }}</time>
            </div>
            <p v-if="item.note" class="hf__note">{{ item.note }}</p>
            <ul v-if="item.changes?.length" class="hf__changes">
              <li v-for="change in item.changes" :key="change.field">
                <span class="hf__field">{{ labelOf(change) }}</span>
                <span class="hf__from">
                  <FieldValue v-if="fieldOf(change)" :field="fieldOf(change)!" :values="asValues(change, 'from')" />
                  <template v-else>{{ change.from }}</template>
                </span>
                <i class="pi pi-arrow-right" />
                <span class="hf__to">
                  <FieldValue v-if="fieldOf(change)" :field="fieldOf(change)!" :values="asValues(change, 'to')" />
                  <template v-else>{{ change.to }}</template>
                </span>
              </li>
            </ul>
          </article>
        </template>
      </Timeline>
      <div ref="sentinel" class="hf__sentinel" />
      <div v-if="page" class="hf__foot">
        <span v-if="loading" class="muted"><i class="pi pi-spin pi-spinner" /> Carregando mais…</span>
        <Button v-else-if="failed" label="Tentar de novo" icon="pi pi-refresh" text size="small" @click="more" />
        <span v-else-if="done && rows.length" class="muted">Fim do histórico</span>
        <Button v-else-if="!done" label="Carregar mais" icon="pi pi-angle-down" text size="small" @click="more" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.hf { display: flex; flex-direction: column; gap: 0.55rem; padding-top: 1rem; }
.hf__head { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; padding: 0 2px; }
.hf__head h2 { margin: 0; display: flex; align-items: center; gap: 0.45rem; font: 600 14px/1.3 var(--font-sans); color: var(--text-strong); }
.hf__head h2 i { font-size: 13px; color: var(--brand); }
.hf__head h2 small { font-size: 12px; color: var(--text-muted); font-weight: 600; }
.hf__head p { margin: 0; font-size: 12.5px; color: var(--text-muted); }
/* O quadro rola sozinho: a página não cresce sem fim, e o fim dele pede mais. */
.hf__card { max-height: 460px; overflow-y: auto; padding: 10px 4px 4px; background: transparent; }
.hf__timeline :deep(.p-timeline-event-opposite) { display: none; }
.hf__timeline :deep(.p-timeline-event) { min-height: 0; }
.hf__timeline :deep(.p-timeline-event-content) { padding: 0 0 18px 12px; }
.hf__timeline :deep(.p-timeline-event-connector) { background: var(--border-subtle); width: 2px; }
.hf__marker {
  display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; font-size: 12px;
  background: color-mix(in srgb, var(--tone) 14%, var(--surface-card)); color: var(--tone);
  box-shadow: 0 0 0 4px var(--surface-ground);
}
.tone-success { --tone: var(--success-text); }
.tone-danger { --tone: var(--danger-text); }
.tone-warning { --tone: var(--warning-text); }
.tone-info { --tone: var(--info-text); }
.tone-brand { --tone: var(--text-brand); }
.tone-neutral { --tone: var(--text-muted); }
.hf__event { padding-top: 4px; }
.hf__line { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.hf__line strong { font-size: 14px; color: var(--text-strong); }
.hf__by { font-size: 12.5px; color: var(--text-body); display: inline-flex; gap: 4px; align-items: center; }
.hf__by i { font-size: 10px; color: var(--text-subtle); }
.hf__line time { margin-left: auto; font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.hf__note { margin: 4px 0 0; font-size: 13px; color: var(--text-body); }
.hf__changes {
  list-style: none; margin: 8px 0 0; padding: 8px 12px; display: flex; flex-direction: column; gap: 5px;
  border-radius: 8px; background: var(--surface-sunken, var(--surface-hover)); font-size: 13px;
}
.hf__changes li { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hf__changes i { font-size: 10px; color: var(--text-subtle); }
.hf__field { font-weight: 600; color: var(--text-muted); min-width: 120px; }
.hf__from { color: var(--text-muted); text-decoration: line-through; }
.hf__to { color: var(--text-strong); font-weight: 600; }
.hf__empty { margin: 0; padding: 12px 0 16px; color: var(--text-muted); font-size: 13px; }
.hf__skeleton { display: flex; flex-direction: column; gap: 16px; padding-bottom: 12px; }
.hf__ghost { display: flex; gap: 12px; align-items: center; }
.hf__ghost > div { display: flex; flex-direction: column; gap: 6px; }
.hf__sentinel { height: 1px; }
.hf__foot { display: flex; justify-content: center; padding: 4px 0 10px; font-size: 12.5px; }
@media (max-width: 640px) { .hf__line time { margin-left: 0; width: 100%; } }
</style>
