<script setup lang="ts">
/**
 * Relatório gerado pela Cosmos. No balão: até 4 indicadores do mesmo tamanho e o gráfico principal;
 * "Ver completo" abre todos os blocos numa grade alinhada (cartões da mesma linha com a mesma
 * altura). Baixa em Excel (com os gráficos) ou CSV.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { computed, ref } from "vue";

import { cosmosApi } from "@/api/cosmos";
import type { BookReport } from "@/api/reports";
import KpiTile from "@/components/report/KpiTile.vue";
import ReportBlock from "@/components/report/ReportBlock.vue";
import { fmt, type Format } from "@/components/report/chart";
import { useNotify } from "@/composables/useNotify";
import { date } from "@/utils/format";

const props = defineProps<{ report: BookReport & { id: string } }>();
const notify = useNotify();
const full = ref(false);
const downloading = ref<"xlsx" | "csv" | null>(null);
const f = (value: unknown) => (value ?? "number") as Format;

const kpis = computed(() => props.report.kpis.slice(0, 4));
/** O gráfico principal (o primeiro que não é tabela); sem gráfico, a tabela. */
const main = computed(() => props.report.blocks.find((b) => b.type !== "table" && b.type !== "insights")
  ?? props.report.blocks[0]);
const hasTable = computed(() => props.report.blocks.some((b) => b.type === "table"));
const more = computed(() => Math.max(props.report.blocks.length - 1, 0));

function delta(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function tone(value: unknown, good?: string) {
  const n = delta(value);
  if (!n) return "flat";
  return (n > 0) === (good !== "down") ? "good" : "bad";
}
function arrow(value: unknown) {
  const n = delta(value) ?? 0;
  return n > 0 ? "pi pi-arrow-up" : n < 0 ? "pi pi-arrow-down" : "pi pi-minus";
}
const pct = (value: unknown) => `${Math.abs(delta(value) ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;

async function download(formato: "xlsx" | "csv") {
  downloading.value = formato;
  try {
    await cosmosApi.download(props.report.id, formato);
  } catch (error) {
    notify.error(error, "Não foi possível baixar");
  } finally {
    downloading.value = null;
  }
}
const exportTable = (format: "xlsx" | "csv") => download(format);
</script>

<template>
  <article class="rep">
    <header class="rep__head">
      <span class="rep__icon"><i class="pi pi-chart-bar" /></span>
      <div class="rep__title">
        <strong :title="report.title">{{ report.title }}</strong>
        <small>{{ date(report.period.from) }} a {{ date(report.period.to) }}</small>
      </div>
    </header>

    <!-- Indicadores: grade 2×2, todos do mesmo tamanho (rótulo, valor, variação). -->
    <div v-if="kpis.length" class="kpis">
      <div v-for="k in kpis" :key="k.label" class="kpi" :title="k.hint || k.label">
        <span class="kpi__label">{{ k.label }}</span>
        <strong class="kpi__value">{{ fmt(k.value, f(k.format)) }}</strong>
        <span class="kpi__delta" :class="`kpi__delta--${tone(k.delta, k.good)}`">
          <template v-if="delta(k.delta) !== null">
            <i :class="arrow(k.delta)" />
            {{ pct(k.delta) }} <span class="kpi__vs">vs. anterior</span>
          </template>
          <template v-else>&nbsp;</template>
        </span>
      </div>
    </div>

    <section v-if="main" class="chart">
      <h4 :title="main.title">{{ main.title }}</h4>
      <div class="chart__body">
        <ReportBlock :block="main" :table-title="`${report.title} ${main.title}`" compact />
      </div>
    </section>

    <footer class="rep__actions">
      <Button :label="more ? `Ver completo (+${more})` : 'Ver completo'" icon="pi pi-window-maximize" size="small" text
              @click="full = true" />
      <span class="grow" />
      <Button label="Excel" icon="pi pi-file-excel" size="small" outlined :loading="downloading === 'xlsx'"
              title="Planilha com resumo, uma aba por bloco e os gráficos" @click="download('xlsx')" />
      <Button v-if="hasTable" label="CSV" icon="pi pi-download" size="small" text :loading="downloading === 'csv'"
              @click="download('csv')" />
    </footer>

    <Dialog v-model:visible="full" modal maximizable :header="report.title" class="rep-dialog"
            :style="{ width: 'min(1100px, 96vw)' }">
      <p v-if="report.subtitle" class="sub">{{ report.subtitle }}</p>
      <div class="full__kpis">
        <KpiTile v-for="(k, i) in report.kpis" :key="k.label" :label="k.label" :value="k.value" :format="f(k.format)"
                 :delta="k.delta" :good="k.good" :hint="k.hint" :accent="i" />
      </div>
      <div class="full__blocks">
        <section v-for="(block, i) in report.blocks" :key="i" class="card"
                 :class="block.span === 'half' && block.type !== 'table' ? 'card--half' : 'card--whole'">
          <header class="card__head">
            <h4 :title="block.title">{{ block.title }}</h4>
            <p v-if="block.description" class="sub" :title="block.description">{{ block.description }}</p>
          </header>
          <div class="card__body">
            <ReportBlock :block="block" :table-title="`${report.title} ${block.title}`"
                         :on-export="(format) => exportTable(format)" />
          </div>
        </section>
      </div>
    </Dialog>
  </article>
</template>

<style scoped>
.rep { width: 100%; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-card);
       padding: 12px; display: grid; gap: 10px; min-width: 0; }
.rep__head { display: flex; gap: 10px; align-items: center; min-width: 0; }
.rep__icon { width: 30px; height: 30px; flex-shrink: 0; display: grid; place-items: center; border-radius: 8px;
             background: var(--brand-subtle); color: var(--text-brand); font-size: 13px; }
.rep__title { display: grid; min-width: 0; }
.rep__title strong { font-size: 13.5px; color: var(--text-strong); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rep__title small { font-size: 11.5px; color: var(--text-muted); }

/* Indicadores do balão: mesma largura e mesma altura, sempre. */
.kpis { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-rows: 1fr; gap: 6px; }
.kpi { display: grid; grid-template-rows: auto 1fr auto; gap: 2px; min-width: 0; padding: 8px 10px;
       border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--surface-sunken); }
.kpi__label { font-size: 11.5px; font-weight: 600; color: var(--text-muted); white-space: nowrap; overflow: hidden;
              text-overflow: ellipsis; }
.kpi__value { font: 800 16px/1.25 var(--font-sans); color: var(--text-strong); letter-spacing: -0.01em;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; align-self: center; }
.kpi__delta { font-size: 11px; font-weight: 700; display: inline-flex; gap: 3px; align-items: center; white-space: nowrap;
              overflow: hidden; }
.kpi__delta i { font-size: 9px; }
.kpi__delta--good { color: var(--success-text); }
.kpi__delta--bad { color: var(--danger-text); }
.kpi__delta--flat { color: var(--text-subtle); }
.kpi__vs { font-weight: 500; color: var(--text-subtle); }

/* Gráfico principal: quadro de altura fixa (todo relatório fica do mesmo tamanho na conversa). */
.chart { min-width: 0; padding: 10px; border: 1px solid var(--border-subtle); border-radius: 8px; display: grid; gap: 6px; }
.chart__body { min-width: 0; height: 200px; overflow: hidden; }
.chart__body > :deep(*) { height: 100%; }
h4 { margin: 0; font: 700 12.5px/1.3 var(--font-sans); color: var(--text-strong); white-space: nowrap; overflow: hidden;
     text-overflow: ellipsis; }

.rep__actions { display: flex; gap: 4px; align-items: center; border-top: 1px solid var(--border-subtle); padding-top: 8px; }
.grow { flex: 1; }
.sub { margin: 0; font-size: 12.5px; color: var(--text-muted); }

/* Tela completa: grade de 2 colunas; cartões da mesma linha com a mesma altura e o gráfico no mesmo ponto. */
.full__kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); grid-auto-rows: 1fr; gap: 10px;
              margin: 4px 0 14px; }
.full__kpis > :deep(.kpi) { height: 100%; }
.full__blocks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; align-items: stretch; }
.card { min-width: 0; display: flex; flex-direction: column; gap: 10px; padding: 14px; border: 1px solid var(--border);
        border-radius: var(--radius-lg); background: var(--surface-card); }
.card--whole { grid-column: 1 / -1; }
.card__head { display: grid; gap: 2px; min-height: 38px; }
.card__head .sub { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card--half .card__body { flex: 1; min-height: 240px; display: flex; flex-direction: column; justify-content: center; }
@media (max-width: 760px) { .full__blocks { grid-template-columns: 1fr; } .card--half { grid-column: 1 / -1; } }
</style>
