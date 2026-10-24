<script setup lang="ts">
/** Entradas × saídas por dia (barras lado a lado), com dica no hover. CSS puro. */
import { computed } from "vue";

import { money } from "@/utils/format";

const props = defineProps<{ days: { label: string; inflow: number; outflow: number }[] }>();
const max = computed(() => Math.max(1, ...props.days.flatMap((d) => [d.inflow, d.outflow])));
const height = (v: number) => `${v ? Math.max(3, (v / max.value) * 100) : 0}%`;
</script>

<template>
  <div class="flow">
    <div class="legend"><span class="in" /> Entradas <span class="out" /> Saídas</div>
    <div class="bars" :class="{ dense: days.length > 20 }">
      <div v-for="day in days" :key="day.label" class="day" :title="`${day.label} · entrou ${money(day.inflow)} · saiu ${money(day.outflow)}`">
        <div class="track">
          <span class="bar in" :style="{ height: height(day.inflow) }" />
          <span class="bar out" :style="{ height: height(day.outflow) }" />
        </div>
        <small>{{ day.label }}</small>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legend { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }
.legend span { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.legend .out { margin-left: 10px; }
.bars { height: 200px; display: flex; gap: 6px; align-items: stretch; }
.bars.dense { gap: 2px; }
.day { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.track { flex: 1; display: flex; align-items: flex-end; justify-content: center; gap: 2px; border-radius: 6px; background: var(--surface-sunken); padding: 0 2px; }
.day:hover .track { background: var(--surface-hover); }
.bar { flex: 1; max-width: 18px; border-radius: 4px 4px 2px 2px; transition: height var(--dur-slow) var(--ease-out); }
.in { background: var(--success); }
.out { background: var(--danger); opacity: 0.8; }
small { font-size: 10.5px; color: var(--text-subtle); text-align: center; white-space: nowrap; overflow: hidden; }
.bars.dense small { visibility: hidden; }
.bars.dense .day:nth-child(5n + 1) small { visibility: visible; }
</style>
