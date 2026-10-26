<script setup lang="ts">
/** Balão flutuante (fora do fluxo, segue o ponteiro); textos entram como texto, nunca HTML. */
import { computed } from "vue";

import type { TipRow } from "./useTooltip";

const props = defineProps<{ tip: { show: boolean; x: number; y: number; title: string; rows: TipRow[] } }>();
/** Perto da borda direita, o balão abre para a esquerda do ponteiro. */
const left = computed(() => Math.min(props.tip.x + 14, window.innerWidth - 236));
</script>

<template>
  <Teleport to="body">
    <div v-if="tip.show" class="ctip" role="tooltip" :style="{ left: `${left}px`, top: `${tip.y + 14}px` }">
      <p class="ctip__title">{{ tip.title }}</p>
      <p v-for="row in tip.rows" :key="row.label" class="ctip__row">
        <span v-if="row.color" class="ctip__key" :style="{ background: row.color }" />
        <strong>{{ row.value }}</strong><span class="ctip__label">{{ row.label }}</span>
      </p>
    </div>
  </Teleport>
</template>

<style scoped>
.ctip { position: fixed; z-index: 2000; pointer-events: none; min-width: 140px; max-width: 220px; padding: 8px 10px;
        border-radius: 8px; border: 1px solid var(--border); background: var(--surface-raised); box-shadow: var(--shadow-md); }
.ctip__title { margin: 0 0 4px; font-size: 11.5px; color: var(--text-muted); }
.ctip__row { margin: 2px 0 0; display: flex; align-items: center; gap: 6px; font-size: 13px; }
.ctip__row strong { color: var(--text-strong); font-variant-numeric: tabular-nums; }
.ctip__label { color: var(--text-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ctip__key { width: 12px; height: 2px; border-radius: 1px; flex: none; }
</style>
