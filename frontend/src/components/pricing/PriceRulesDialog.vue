<script setup lang="ts">
/** Regras: quais produtos a leitura pega, para não puxar sempre o catálogo inteiro. O Analítico de SEO usa o mesmo formulário. */
import Button from "primevue/button";
import { onMounted, ref } from "vue";

import { pricingApi, type PriceRules } from "@/api/pricing";
import FormField from "@/components/resource/FormField.vue";
import { useNotify } from "@/composables/useNotify";
import type { FieldDef, FormActionContext } from "@/resources/types";
import { useSession } from "@/stores/session";

type RulesApi = Pick<typeof pricingApi, "rules" | "saveRules" | "run">;
const props = withDefaults(defineProps<{ ctx?: FormActionContext; api?: RulesApi; intro?: string; runLabel?: string }>(), {
  ctx: undefined,
  api: () => pricingApi,
  intro: "Escolha o que a leitura do mercado pega. Sem nada marcado, vale o catálogo inteiro. O botão \"Precificar\" da página do produto não segue estas regras.",
  runLabel: "Salvar e ler agora",
});
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const session = useSession();
const values = ref<Record<string, unknown>>({});
const inScope = ref<number | null>(null);
const busy = ref<"load" | "save" | "read" | null>("load");

const PRODUCTS = { endpoint: "/catalog/products/" };
const FIELDS: FieldDef[] = [
  { name: "categories", label: "Categorias", type: "multirelation", relation: { endpoint: "/catalog/categories/" }, span: 3,
    hint: "A categoria leva as subcategorias" },
  { name: "brands", label: "Marcas", type: "multirelation", relation: { endpoint: "/catalog/brands/" }, span: 3,
    hint: "Com categoria e marca, vale o que tem as duas" },
  { name: "products", label: "Produtos", type: "multirelation", relation: PRODUCTS, span: 6,
    hint: "Estes entram sempre, mesmo fora das categorias e marcas" },
  { name: "exclude_products", label: "Nunca incluir estes produtos", type: "multirelation", relation: PRODUCTS, span: 6 },
  { name: "min_price", label: "Preço de venda a partir de", type: "money", span: 3 },
  { name: "max_price", label: "Preço de venda até", type: "money", span: 3 },
  { name: "only_in_stock", label: "Só o que tem estoque", type: "boolean", span: 3, visible: () => session.hasModule("stock") },
  { name: "only_with_barcode", label: "Só o que tem código de barras", type: "boolean", span: 3 },
];

onMounted(async () => {
  try {
    const { in_scope, ...rules } = await props.api.rules();
    values.value = rules;
    inScope.value = in_scope;
  } catch (error) {
    notify.error(error, "Regras não carregadas");
    emit("close");
  } finally {
    busy.value = null;
  }
});

const price = (value: unknown) => (value === "" || value === undefined ? null : value) as PriceRules["min_price"];

async function save(read: boolean) {
  busy.value = read ? "read" : "save";
  try {
    const rules = { ...values.value, min_price: price(values.value.min_price), max_price: price(values.value.max_price) };
    const saved = await props.api.saveRules(rules as PriceRules);
    inScope.value = saved.in_scope;
    if (read) {
      const { checked } = await props.api.run();
      notify.success("Regras salvas", `${checked} produto(s) na fila, de 10 em 10. A lista se atualiza sozinha.`);
    } else {
      notify.success("Regras salvas", `${saved.in_scope} produto(s) entram nas regras.`);
    }
    emit("done");
  } catch (error) {
    notify.error(error, "Regras não salvas");
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <div class="rules">
    <p>{{ intro }}</p>
    <div v-if="busy === 'load'" class="muted"><i class="pi pi-spin pi-spinner" /> Carregando…</div>
    <div v-else class="grid-form">
      <template v-for="field in FIELDS" :key="field.name">
        <FormField v-if="!field.visible || field.visible(values)" v-model="values[field.name]" :field="field" :context="values" />
      </template>
    </div>
    <div class="foot">
      <span v-if="inScope !== null" class="count">{{ inScope }} produto(s) nas regras salvas</span>
      <Button label="Voltar" severity="secondary" text :disabled="busy !== null" @click="emit('close')" />
      <Button label="Salvar" severity="secondary" outlined :loading="busy === 'save'" :disabled="busy !== null" @click="save(false)" />
      <Button :label="runLabel" icon="pi pi-refresh" :loading="busy === 'read'" :disabled="busy !== null" @click="save(true)" />
    </div>
  </div>
</template>

<style scoped>
.rules { display: flex; flex-direction: column; gap: 12px; font-size: 13px; }
p { margin: 0; color: var(--text-muted); }
.foot { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.count { margin-right: auto; color: var(--text-muted); font-size: 12.5px; }
</style>
