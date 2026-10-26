<script setup lang="ts">
import { computed } from "vue";

import type { ColumnDef } from "@/resources/types";
import { date, dateTime, money, percent, quantity } from "@/utils/format";

const props = defineProps<{ column: ColumnDef; value: unknown }>();

const text = computed(() => {
  const v = props.value;
  switch (props.column.type) {
    case "money": return money(v);
    case "quantity": return quantity(v);
    case "percent": return percent(v);
    case "date": return date(v);
    case "datetime": return dateTime(v);
    case "tag": return props.column.map?.[String(v)] ?? String(v ?? "—");
    default: return v === null || v === undefined || v === "" ? "—" : String(v);
  }
});

/** "Ativo/Inativo" para o campo de ativo; "Sim/Não" para o resto. */
const booleanLabel = computed(() => {
  const active = props.column.key.startsWith("is_active");
  if (props.value) return active ? "Ativo" : "Sim";
  return active ? "Inativo" : "Não";
});
const numeric = computed(() => ["money", "quantity", "percent"].includes(props.column.type ?? ""));
</script>

<template>
  <span v-if="column.type === 'boolean'" class="pill" :class="value ? 'pill--success' : 'pill--neutral'">
    {{ booleanLabel }}
  </span>
  <span v-else-if="column.type === 'image'" class="thumb">
    <img v-if="value" :src="String(value)" alt="" loading="lazy" /><i v-else class="pi pi-image" />
  </span>
  <span v-else-if="column.type === 'stars'" class="stars" :aria-label="`Nota ${value} de 5`">
    <i v-for="n in 5" :key="n" :class="n <= Number(value) ? 'on' : ''">★</i>
  </span>
  <span v-else-if="column.type === 'tag'" class="pill" :class="`pill--${column.tones?.[String(value)] ?? 'brand'}`">{{ text }}</span>
  <span v-else :class="{ num: numeric, cell: true, empty: text === '—' }">{{ text }}</span>
</template>

<style scoped>
.cell { color: inherit; }
.num { font-weight: 600; color: var(--text-strong); }
.empty { color: var(--text-subtle); }
.thumb {
  width: 38px; height: 38px; border-radius: 8px; overflow: hidden; display: grid; place-items: center; flex: none;
  background: var(--surface-sunken); border: 1px solid var(--border-subtle); color: var(--text-subtle); font-size: 14px;
}
.stars { white-space: nowrap; letter-spacing: 1px; font-size: 14px; color: var(--border-strong, #c7cbd1); }
.stars .on { color: #f5a524; font-style: normal; }
.stars i { font-style: normal; }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
</style>
