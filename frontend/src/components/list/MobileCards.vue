<script setup lang="ts">
/**
 * Lista em cartões para o celular (no lugar da tabela). Cada linha vira um cartão:
 * foto e título no topo, etiquetas (situação, ativo...) logo abaixo e as outras colunas
 * em "rótulo: valor". Toque abre; segurar marca para as ações em massa (com algo
 * marcado, o toque só marca/desmarca). "⋯" abre o mesmo menu da linha da tabela.
 */
import Checkbox from "primevue/checkbox";
import { computed } from "vue";

import type { Row } from "@/api/resource";
import CellValue from "@/components/resource/CellValue.vue";
import type { ColumnDef } from "@/resources/types";

const props = defineProps<{
  rows: Row[]; columns: ColumnDef[]; titleKey?: string; selected: (id: string) => boolean; selecting: boolean;
}>();
const emit = defineEmits<{ open: [Row]; toggle: [string]; menu: [Event, Row]; warm: [Row] }>();

const shown = computed(() => props.columns.filter((c) => c.mobile !== false));
const image = computed(() => shown.value.find((c) => c.type === "image"));
const chips = computed(() => shown.value.filter((c) => (c.type === "tag" || c.type === "boolean") && c.key !== props.titleKey));
/** Até 6 campos no cartão: o resto fica no registro (um toque). */
const fields = computed(() => shown.value.filter((c) => c.key !== props.titleKey && c.type !== "image"
  && c.type !== "tag" && c.type !== "boolean").slice(0, 6));
const titleColumn = computed(() => shown.value.find((c) => c.key === props.titleKey));
const empty = (v: unknown) => v === null || v === undefined || v === "";

let press: ReturnType<typeof setTimeout> | undefined;
let held = false;
function down(row: Row) {
  held = false;
  emit("warm", row);
  press = setTimeout(() => {
    held = true;
    navigator.vibrate?.(30);
    emit("toggle", String(row.id));
  }, 450);
}
const up = () => clearTimeout(press);
function tap(row: Row) {
  if (held) return;
  if (props.selecting) emit("toggle", String(row.id));
  else emit("open", row);
}
</script>

<template>
  <ul class="cards">
    <li v-for="row in rows" :key="String(row.id)" class="card" :class="{ selected: selected(String(row.id)) }"
        @touchstart.passive="down(row)" @touchend="up" @touchmove.passive="up" @click="tap(row)" @contextmenu.prevent>
      <div class="card__top">
        <span v-if="selecting" class="card__check" @click.stop="emit('toggle', String(row.id))">
          <Checkbox :model-value="selected(String(row.id))" binary :tabindex="-1" />
        </span>
        <CellValue v-if="image" :column="image" :value="row[image.key]" />
        <strong class="card__title">
          <CellValue v-if="titleColumn" :column="titleColumn" :value="row[titleColumn.key]" />
        </strong>
        <button type="button" class="card__menu" aria-label="Ações" @click.stop="emit('menu', $event, row)">
          <i class="pi pi-ellipsis-v" />
        </button>
      </div>
      <div v-if="chips.some((c) => !empty(row[c.key]))" class="card__chips">
        <template v-for="column in chips" :key="column.key">
          <CellValue v-if="!empty(row[column.key])" :column="column" :value="row[column.key]" />
        </template>
      </div>
      <dl v-if="fields.length" class="card__fields">
        <div v-for="column in fields" :key="column.key" :class="{ num: ['money', 'quantity', 'percent'].includes(column.type ?? '') }">
          <dt>{{ column.label }}</dt>
          <dd><CellValue :column="column" :value="row[column.key]" /></dd>
        </div>
      </dl>
    </li>
  </ul>
</template>

<style scoped>
.cards { list-style: none; margin: 0; padding: 8px; display: flex; flex-direction: column; gap: 8px; }
.card {
  padding: 12px 12px 10px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-card);
  cursor: pointer; -webkit-tap-highlight-color: transparent; user-select: none; transition: background-color var(--dur-fast) ease;
}
.card:active { background: var(--surface-hover); }
.card.selected { border-color: var(--brand-border); background: var(--brand-subtle); }
.card__top { display: flex; align-items: center; gap: 10px; min-width: 0; }
.card__check { display: inline-flex; }
.card__title { flex: 1; min-width: 0; font-size: 15px; font-weight: 700; color: var(--text-strong);
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card__title :deep(.cell) { font-weight: 700; }
.card__menu { width: 36px; height: 36px; margin: -6px -6px -6px 0; display: grid; place-items: center; border: 0; border-radius: 8px;
              background: transparent; color: var(--text-muted); flex: none; }
.card__menu:active { background: var(--surface-active); }
.card__chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.card__fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px; margin: 10px 0 0; }
.card__fields div { min-width: 0; }
.card__fields dt { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-subtle); }
.card__fields dd { margin: 1px 0 0; font-size: 13.5px; color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
