<script setup lang="ts">
/**
 * Página de impressão: `/imprimir/<documento>/<id>` fora do layout do sistema.
 * Documentos: turno, venda, estoque, separacao, conta, titulo, dre, lista.
 * `?formato=a4|a4-landscape|80mm` escolhe o papel; sem ele vale o último escolhido para
 * aquele documento neste navegador (o caixa que troca para bobina uma vez fica nela) e,
 * na primeira vez, o padrão do documento (A4). `?auto=1` já abre a impressão.
 */
import { computed, defineAsyncComponent } from "vue";
import { useRoute } from "vue-router";

import { type PrintFormat, rememberedFormat } from "@/print/format";

const DOCS: Record<string, ReturnType<typeof defineAsyncComponent>> = {
  turno: defineAsyncComponent(() => import("@/print/docs/CashShiftPrint.vue")),
  venda: defineAsyncComponent(() => import("@/print/docs/SalePrint.vue")),
  estoque: defineAsyncComponent(() => import("@/print/docs/StockDocumentPrint.vue")),
  separacao: defineAsyncComponent(() => import("@/print/docs/PickingPrint.vue")),
  conta: defineAsyncComponent(() => import("@/print/docs/AccountStatementPrint.vue")),
  titulo: defineAsyncComponent(() => import("@/print/docs/TitlePrint.vue")),
  dre: defineAsyncComponent(() => import("@/print/docs/DrePrint.vue")),
  lista: defineAsyncComponent(() => import("@/print/docs/ListPrint.vue")),
};

const route = useRoute();
const doc = computed(() => DOCS[String(route.params.doc)]);
const format = computed(() => (route.query.formato as PrintFormat | undefined) ?? rememberedFormat(String(route.params.doc)));
</script>

<template>
  <component :is="doc" v-if="doc" :id="String(route.params.id ?? '')" :initial-format="format" />
  <p v-else style="padding: 40px; text-align: center">Documento de impressão desconhecido.</p>
</template>
