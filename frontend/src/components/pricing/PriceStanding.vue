<script setup lang="ts">
/**
 * Onde o nosso preço fica no mercado: a régua do menor ao maior preço, com a média, a mediana e o nosso,
 * e a colocação entre os concorrentes. Com o mercado de R$ 1 mil a R$ 3 mil, só a mediana esconde isso.
 */
import { computed } from "vue";

import type { FormActionContext } from "@/resources/types";
import { money } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const v = computed(() => props.ctx.values);
const low = computed(() => Number(v.value.market_min));
const high = computed(() => Number(v.value.market_max));
const ours = computed(() => Number(v.value.current_price));
const ready = computed(() => Boolean(v.value.market_min && v.value.market_max) && !v.value.reading);
const hasRange = computed(() => high.value > low.value);

/** Posição na régua, de 0 a 100. Fora da faixa, o nosso preço fica na ponta. */
const at = (value: unknown) => (hasRange.value ? Math.min(100, Math.max(0, ((Number(value) - low.value) / (high.value - low.value)) * 100)) : 50);

const place = computed(() => {
  if (ours.value < low.value) return `${money(low.value - ours.value)} abaixo do menor preço do mercado`;
  if (ours.value > high.value) return `${money(ours.value - high.value)} acima do maior preço do mercado`;
  return hasRange.value ? `A ${Math.round(at(ours.value))}% do caminho entre o menor e o maior preço` : "No mesmo preço do mercado";
});
const rank = computed(() => {
  const position = Number(v.value.market_rank);
  const total = Number(v.value.competitors ?? 0) + 1;
  if (!position) return "";
  return position === 1 ? `O mais barato entre ${total} preços` : `${position}º mais barato entre ${total} preços`;
});
</script>

<template>
  <section v-if="ready" class="standing" aria-label="Onde o nosso preço fica no mercado">
    <header>
      <h2><i class="pi pi-sliders-h" /> Onde estamos no mercado</h2>
      <p><strong>{{ rank }}</strong><span v-if="rank"> · </span>{{ place }}</p>
    </header>
    <dl class="standing__numbers">
      <div><dt>Menor</dt><dd>{{ money(v.market_min) }}</dd></div>
      <div><dt>Média</dt><dd>{{ v.market_avg ? money(v.market_avg) : "—" }}</dd></div>
      <div><dt>Mediana</dt><dd>{{ money(v.market_median) }}</dd></div>
      <div><dt>Maior</dt><dd>{{ money(v.market_max) }}</dd></div>
      <div class="standing__ours"><dt>Nosso preço</dt><dd>{{ money(v.current_price) }}</dd></div>
    </dl>
    <div v-if="hasRange" class="ruler" role="img"
         :aria-label="`Nosso preço de ${money(v.current_price)} na faixa de ${money(v.market_min)} a ${money(v.market_max)}`">
      <span class="ruler__mark" :style="{ left: `${at(v.market_median)}%` }" title="Mediana" />
      <span v-if="v.market_avg" class="ruler__mark ruler__mark--avg" :style="{ left: `${at(v.market_avg)}%` }" title="Média" />
      <span class="ruler__ours" :style="{ left: `${at(ours)}%` }" :title="`Nosso preço: ${money(v.current_price)}`" />
    </div>
    <div v-if="hasRange" class="ruler__legend">
      <span><i class="dot dot--ours" /> Nosso preço</span>
      <span><i class="dot dot--median" /> Mediana</span>
      <span v-if="v.market_avg"><i class="dot dot--avg" /> Média</span>
    </div>
  </section>
</template>

<style scoped>
.standing {
  display: flex; flex-direction: column; gap: 0.75rem; padding: 14px 18px; border-radius: 10px;
  background: var(--surface-card); border: 1px solid var(--border); box-shadow: var(--shadow-xs);
}
header { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
h2 { margin: 0; display: flex; align-items: center; gap: 0.45rem; font: 600 14px/1.3 var(--font-sans); color: var(--text-strong); }
h2 i { font-size: 13px; color: var(--brand); }
header p { margin: 0; font-size: 13px; color: var(--text-muted); }
header strong { color: var(--text-strong); }
.standing__numbers { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 0.5rem; margin: 0; }
.standing__numbers dt { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.standing__numbers dd { margin: 2px 0 0; font-size: 15px; font-weight: 700; color: var(--text-strong); }
.standing__ours dt, .standing__ours dd { color: var(--text-brand); }
.ruler {
  position: relative; height: 10px; margin: 0.4rem 8px; border-radius: 999px;
  background: linear-gradient(90deg, var(--success-subtle), var(--surface-sunken) 50%, var(--danger-subtle));
  border: 1px solid var(--border-subtle);
}
.ruler__mark, .ruler__ours { position: absolute; top: 50%; transform: translate(-50%, -50%); }
.ruler__mark { width: 2px; height: 16px; background: var(--text-muted); }
.ruler__mark--avg { background: var(--text-subtle); height: 12px; }
.ruler__ours { width: 16px; height: 16px; border-radius: 50%; background: var(--brand); border: 2px solid var(--surface-card); box-shadow: var(--shadow-xs); }
.ruler__legend { display: flex; flex-wrap: wrap; gap: 0.9rem; font-size: 12px; color: var(--text-muted); }
.dot { display: inline-block; vertical-align: middle; margin-right: 0.3rem; }
.dot--ours { width: 10px; height: 10px; border-radius: 50%; background: var(--brand); }
.dot--median { width: 2px; height: 12px; background: var(--text-muted); }
.dot--avg { width: 2px; height: 9px; background: var(--text-subtle); }
</style>
