<script setup lang="ts">
/** A barra de progresso da tarefa. A tela relê sozinha enquanto ela está em andamento (`resource.poll`). */
import ProgressBar from "primevue/progressbar";
import { computed } from "vue";

import type { FormActionContext } from "@/resources/types";

const props = defineProps<{ ctx: FormActionContext }>();
const v = computed(() => props.ctx.values);
const percent = computed(() => Number(v.value.percent ?? 0));
</script>

<template>
  <section class="task" aria-label="Progresso da tarefa">
    <header>
      <h2><i class="pi pi-spinner" :class="{ 'pi-spin': v.status === 'running' }" /> {{ v.kind_display }}</h2>
      <p>{{ v.done ?? 0 }} de {{ v.total ?? 0 }} · {{ percent }}%</p>
    </header>
    <ProgressBar :value="percent" :show-value="false" style="height: 10px" :aria-label="`${percent}% concluído`" />
    <p v-if="v.status === 'running' && v.can_stop" class="task__hint">Ao parar, o lote em andamento termina e o próximo não começa. O que já foi feito fica salvo.</p>
  </section>
</template>

<style scoped>
.task {
  display: flex; flex-direction: column; gap: 0.6rem; padding: 14px 18px; border-radius: 10px;
  background: var(--surface-card); border: 1px solid var(--border); box-shadow: var(--shadow-xs);
}
header { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
h2 { margin: 0; display: flex; align-items: center; gap: 0.45rem; font: 600 14px/1.3 var(--font-sans); color: var(--text-strong); }
h2 i { font-size: 13px; color: var(--brand); }
header p { margin: 0; font-size: 13px; font-weight: 600; color: var(--text-strong); }
.task__hint { margin: 0; font-size: 12.5px; color: var(--text-muted); }
</style>
