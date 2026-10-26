<script setup lang="ts">
/** Gráfico de barras leve (CSS puro): uma barra por ponto, dica no hover. */
import { computed } from "vue";

const props = defineProps<{ points: { label: string; value: number; hint: string }[] }>();
const max = computed(() => Math.max(1, ...props.points.map((p) => p.value)));
</script>

<template>
  <div class="chart" :class="{ dense: points.length > 20 }">
    <div v-if="!points.length" class="chart__empty muted">Sem vendas no período.</div>
    <div v-for="point in points" :key="point.label" class="chart__col">
      <div class="chart__track">
        <div class="chart__bar" :style="{ height: `${Math.max(3, (point.value / max) * 100)}%` }">
          <span class="chart__tip">{{ point.hint }}</span>
        </div>
      </div>
      <span class="chart__label">{{ point.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.chart { overflow-x: clip; height: 220px; display: flex; align-items: stretch; gap: 6px; padding-top: 28px; }
.chart.dense { gap: 3px; }
.chart__empty { margin: auto; }
.chart__col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.chart__track { flex: 1; display: flex; align-items: flex-end; justify-content: center; border-radius: 6px; background: var(--surface-sunken); transition: background-color var(--dur-fast) ease; }
.chart__col:hover .chart__track { background: var(--surface-hover); }
.chart__bar {
  position: relative; width: 100%; max-width: 44px; border-radius: 6px 6px 3px 3px;
  background: linear-gradient(180deg, var(--brand-400), var(--brand)); opacity: 0.85;
  transition: opacity var(--dur-fast) ease, filter var(--dur-fast) ease; animation: grow var(--dur-slow) var(--ease-out) both; transform-origin: bottom;
}
.chart__col:hover .chart__bar { opacity: 1; filter: drop-shadow(0 4px 10px color-mix(in srgb, var(--brand) 40%, transparent)); }
.chart__tip {
  position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%) translateY(4px); white-space: nowrap; pointer-events: none;
  padding: 4px 8px; border-radius: 6px; font: 600 11.5px/1.3 var(--font-sans); color: var(--surface-card); background: var(--text-strong);
  opacity: 0; transition: opacity var(--dur-fast) ease, transform var(--dur-base) var(--ease-spring); z-index: 2;
}
.chart__col:hover .chart__tip { opacity: 1; transform: translateX(-50%); }
.chart__label { font-size: 10.5px; color: var(--text-subtle); text-align: center; white-space: nowrap; overflow: hidden; }
.dense .chart__label { visibility: hidden; }
.dense .chart__col:nth-child(5n + 1) .chart__label { visibility: visible; }
@keyframes grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
</style>
