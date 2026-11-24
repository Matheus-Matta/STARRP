<script setup lang="ts">
/**
 * Indicador do relatório: o número em destaque e a variação contra o período anterior.
 * Com `link`, o card inteiro leva à tela de onde o número vem (já filtrada pelo período).
 * `tone` pinta o valor (resultado positivo em verde, negativo em vermelho).
 * A variação nunca é só cor: seta + texto ("▲ 12,3% vs. anterior"); verde quando o movimento
 * é bom para o negócio (subir faturamento, cair despesa), vermelho quando é ruim.
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";

import { fmt, type Format } from "./chart";

const props = defineProps<{ label: string; value: string | number; format: Format; delta?: string | number | null;
                            good?: "up" | "down"; hint?: string; accent: number; icon?: string;
                            tone?: "good" | "bad" | "neutral"; link?: { path: string; query?: Record<string, string> };
                            count?: string }>();
const delta = computed(() => (props.delta === null || props.delta === undefined ? null : Number(props.delta)));
const tone = computed(() => {
  if (delta.value === null || delta.value === 0) return "flat";
  const up = delta.value > 0;
  return (up && props.good !== "down") || (!up && props.good === "down") ? "good" : "bad";
});
const deltaText = computed(() => `${Math.abs(delta.value ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`);
</script>

<template>
  <component :is="link ? RouterLink : 'div'" :to="link" class="kpi" :class="{ 'kpi--link': link }"
             :style="{ '--accent': `var(--series-${(accent % 8) + 1})` }">
    <span class="kpi__label"><i v-if="icon" :class="icon" class="kpi__icon" />{{ label }}
      <i v-if="link" class="pi pi-arrow-up-right kpi__go" aria-hidden="true" /></span>
    <strong class="kpi__value" :class="tone && `kpi__value--${tone}`" :title="fmt(value, format)">{{ fmt(value, format) }}</strong>
    <span v-if="count" class="kpi__count">{{ count }}</span>
    <span v-if="delta !== null" class="kpi__delta" :class="`kpi__delta--${tone}`">
      <i :class="delta > 0 ? 'pi pi-arrow-up' : delta < 0 ? 'pi pi-arrow-down' : 'pi pi-minus'" />
      {{ deltaText }} <span class="kpi__vs">vs. período anterior</span>
    </span>
    <small v-if="hint" class="kpi__hint">{{ hint }}</small>
  </component>
</template>

<style scoped>
.kpi { position: relative; display: flex; flex-direction: column; gap: 6px; padding: 16px 16px 14px; min-width: 0;
       border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-card); overflow: hidden;
       container-type: inline-size; }
.kpi::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--accent); }
.kpi__label { display: flex; align-items: center; gap: 6px; font: 600 12.5px/1.2 var(--font-sans); color: var(--text-muted); }
.kpi__icon { font-size: 13px; color: var(--accent); }
.kpi__go { margin-left: auto; font-size: 11px; opacity: 0; transition: opacity var(--dur-fast) ease; }
.kpi--link { text-decoration: none; cursor: pointer; transition: border-color var(--dur-fast) ease, transform var(--dur-fast) ease,
             box-shadow var(--dur-fast) ease; }
.kpi--link:hover, .kpi--link:focus-visible { border-color: var(--accent); box-shadow: var(--shadow-sm, 0 2px 8px rgb(0 0 0 / 0.06));
                                             transform: translateY(-1px); }
.kpi--link:hover .kpi__go, .kpi--link:focus-visible .kpi__go { opacity: 1; }
.kpi__value--good { color: var(--success-text); }
.kpi__count { align-self: flex-start; max-width: 100%; padding: 2px 8px; border-radius: 999px; background: var(--surface-sunken);
              border: 1px solid var(--border-subtle); font: 650 12px/1.4 var(--font-sans); color: var(--text-body);
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi__value--bad { color: var(--danger-text); }
.kpi__value { font: 800 clamp(16px, 11cqi, 26px)/1.1 var(--font-sans); letter-spacing: -0.02em; color: var(--text-strong);
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi__delta { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 700; }
.kpi__delta i { font-size: 10px; }
.kpi__delta--good { color: var(--success-text); }
.kpi__delta--bad { color: var(--danger-text); }
.kpi__delta--flat { color: var(--text-muted); }
.kpi__vs { font-weight: 500; color: var(--text-subtle); }
.kpi__hint { font-size: 12px; color: var(--text-subtle); }
</style>
