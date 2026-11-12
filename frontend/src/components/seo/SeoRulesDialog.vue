<script setup lang="ts">
/** Regras do Analítico de SEO: o mesmo formulário da precificação, com as regras guardadas à parte. */
import { seoApi } from "@/api/seo";
import PriceRulesDialog from "@/components/pricing/PriceRulesDialog.vue";
import type { FormActionContext } from "@/resources/types";

defineProps<{ ctx?: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
</script>

<template>
  <PriceRulesDialog :api="seoApi" run-label="Salvar e analisar agora"
                    intro="Escolha o que a análise pega. Sem nada marcado, vale o catálogo inteiro. O botão &quot;Analisar SEO&quot; da página do produto não segue estas regras."
                    @done="emit('done')" @close="emit('close')" />
</template>
