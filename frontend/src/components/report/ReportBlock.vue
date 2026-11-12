<script setup lang="ts">
/**
 * Um bloco do livro de relatórios (gráfico ou tabela), no formato padrão do backend.
 * Usado pela tela de relatórios e pelos relatórios que a Cosmos gera na conversa.
 */
import type { BookBlock } from "@/api/reports";

import BarsChart from "./BarsChart.vue";
import CompareChart from "./CompareChart.vue";
import HeatmapChart from "./HeatmapChart.vue";
import InsightsBlock from "./InsightsBlock.vue";
import LineChart from "./LineChart.vue";
import RankingChart from "./RankingChart.vue";
import ReportTable from "./ReportTable.vue";
import ShareChart from "./ShareChart.vue";
import WaterfallChart from "./WaterfallChart.vue";
import type { Format } from "./chart";

defineProps<{ block: BookBlock; tableTitle: string; compact?: boolean;
              onExport?: (format: "xlsx" | "csv", tab: string | null) => Promise<void> }>();

const f = (value: unknown) => (value ?? "number") as Format;
/** Mensagem de lista vazia que o relatório manda ("Nenhuma promoção deu prejuízo no período."). */
const emptyOf = (block: BookBlock) => (typeof block.empty === "string" ? block.empty : undefined);
</script>

<template>
  <LineChart v-if="block.type === 'line'" :x="block.x as string[]" :series="block.series as never" :format="f(block.format)"
             :zero="block.zero !== false" :grain="block.grain as never" />
  <BarsChart v-else-if="block.type === 'bars'" :x="block.x as string[]" :series="block.series as never"
             :format="f(block.format)" :stacked="block.stacked" :grain="block.grain as never" />
  <RankingChart v-else-if="block.type === 'ranking'" :rows="block.rows as never" :format="f(block.format)"
                :limit="(block.limit as number | undefined) ?? (compact || block.span === 'half' ? 8 : 12)"
                :ordered="block.ordered !== false" :empty="emptyOf(block)" />
  <ShareChart v-else-if="block.type === 'share'" :rows="block.rows as never" :format="f(block.format)" />
  <HeatmapChart v-else-if="block.type === 'heatmap'" :rows="block.rows as string[]" :cols="block.cols as string[]"
                :values="block.values as never" :format="f(block.format)" />
  <WaterfallChart v-else-if="block.type === 'waterfall'" :steps="block.steps as never" :format="f(block.format)" />
  <CompareChart v-else-if="block.type === 'compare'" :metrics="block.metrics as never" :rows="block.rows as never" />
  <InsightsBlock v-else-if="block.type === 'insights'" :items="block.items as never" />
  <ReportTable v-else-if="block.type === 'table'" :columns="block.columns as never" :rows="block.rows as never"
               :title="tableTitle" :tabs="block.tabs as never" :empty="emptyOf(block)" :on-export="onExport" />
</template>
