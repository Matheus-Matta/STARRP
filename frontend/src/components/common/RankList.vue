<script setup lang="ts">
/** Ranking com barra de participação (mais vendidos, formas de pagamento...). */
import { computed } from "vue";

const props = defineProps<{ rows: { label: string; value: number; display: string; meta?: string }[]; empty?: string }>();
const max = computed(() => Math.max(1, ...props.rows.map((r) => r.value)));
</script>

<template>
  <ol class="rank">
    <li v-if="!rows.length" class="rank__empty muted">{{ empty ?? "Sem dados no período." }}</li>
    <li v-for="(row, index) in rows" :key="row.label" class="rank__row">
      <span class="rank__pos">{{ index + 1 }}</span>
      <div class="rank__body">
        <div class="rank__line">
          <span class="rank__label">{{ row.label }}</span>
          <strong class="num">{{ row.display }}</strong>
        </div>
        <div class="rank__bar"><span :style="{ width: `${(row.value / max) * 100}%` }" /></div>
        <small v-if="row.meta" class="muted">{{ row.meta }}</small>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.rank { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.rank__empty { padding: 1.5rem 0; text-align: center; }
.rank__row { display: flex; gap: 12px; align-items: flex-start; padding: 10px; border-radius: 10px; transition: background-color var(--dur-fast) ease; }
.rank__row:hover { background: var(--surface-hover); }
.rank__pos { width: 26px; height: 26px; flex-shrink: 0; border-radius: 8px; display: grid; place-items: center; font: 700 12px/1 var(--font-sans); color: var(--text-muted); background: var(--surface-sunken); }
.rank__row:first-child .rank__pos { color: var(--brand); background: var(--brand-subtle); }
.rank__body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.rank__line { display: flex; justify-content: space-between; gap: 12px; font-size: 13.5px; }
.rank__label { color: var(--text-strong); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rank__bar { height: 6px; border-radius: 999px; background: var(--surface-sunken); overflow: hidden; }
.rank__bar span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--brand-400), var(--brand)); transition: width var(--dur-slow) var(--ease-out); }
small { font-size: 11.5px; }
</style>
