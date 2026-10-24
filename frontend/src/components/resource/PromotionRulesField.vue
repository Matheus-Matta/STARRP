<script setup lang="ts">
/**
 * Regras da tabela de desconto, dentro da própria tabela (um cartão por regra). A ordem
 * é a prioridade: a 1ª que pega o produto vale. Cada regra diz o QUÊ (alvo: categorias,
 * marcas, produtos ou tudo) e QUANTO (percentual, valor abatido ou preço fixo); no alvo
 * "Produtos" dá para pôr o "por" de cada um (encarte). Período próprio é opcional — sem
 * ele vale o da tabela. A lista inteira vai no salvar da tabela.
 */
import Button from "primevue/button";
import DatePicker from "primevue/datepicker";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import SelectButton from "primevue/selectbutton";
import ToggleSwitch from "primevue/toggleswitch";
import { ref } from "vue";

import RelationSelect from "./RelationSelect.vue";

export type RuleProduct = { product: string | null; product_name?: string; promotional_price: string | null;
                            compare_at_price?: string | null };
export type Rule = {
  id?: string; name: string; target: "products" | "categories" | "brands" | "all";
  kind: "percent" | "amount" | "fixed"; value: string | null; categories: string[]; brands: string[];
  products: RuleProduct[]; is_enabled: boolean; starts_at: string | null; ends_at: string | null;
};

const model = defineModel<Rule[]>({ default: () => [] });
defineProps<{ disabled?: boolean }>();

const TARGETS = [
  { label: "Categorias", value: "categories" }, { label: "Marcas", value: "brands" },
  { label: "Produtos", value: "products" }, { label: "Tudo", value: "all" },
];
const KINDS = [
  { label: "% de desconto", value: "percent" }, { label: "R$ abatido", value: "amount" }, { label: "Preço fixo", value: "fixed" },
];
/** Regras com o período aberto (mostra as datas da regra). */
const periodOpen = ref<Record<number, boolean>>({});

function add() {
  model.value = [...model.value, {
    name: "", target: "categories", kind: "percent", value: null, categories: [], brands: [], products: [],
    is_enabled: true, starts_at: null, ends_at: null,
  }];
}
function update(index: number, patch: Partial<Rule>) {
  model.value = model.value.map((r, i) => (i === index ? { ...r, ...patch } : r));
}
function remove(index: number) {
  model.value = model.value.filter((_, i) => i !== index);
}
function move(index: number, step: -1 | 1) {
  const list = [...model.value];
  const target = index + step;
  if (target < 0 || target >= list.length) return;
  [list[index], list[target]] = [list[target]!, list[index]!];
  model.value = list;
}
function updateProduct(index: number, row: number, patch: Partial<RuleProduct>) {
  const products = model.value[index]!.products.map((p, i) => (i === row ? { ...p, ...patch } : p));
  update(index, { products });
}
const addProduct = (index: number) =>
  update(index, { products: [...model.value[index]!.products, { product: null, promotional_price: null }] });
const removeProduct = (index: number, row: number) =>
  update(index, { products: model.value[index]!.products.filter((_, i) => i !== row) });

const asDate = (v: string | null) => (v ? new Date(v) : null);
/** Resumo da regra no cabeçalho do cartão ("20% em 2 categorias"). */
function summary(r: Rule) {
  const value = r.value === null || r.value === "" ? "?" : Number(r.value).toLocaleString("pt-BR");
  const what = r.kind === "percent" ? `${value}% off` : r.kind === "amount" ? `R$ ${value} off` : `por R$ ${value}`;
  const where = r.target === "all" ? "no catálogo todo"
    : r.target === "categories" ? `em ${r.categories.length} categoria(s)`
      : r.target === "brands" ? `em ${r.brands.length} marca(s)` : `em ${r.products.length} produto(s)`;
  return `${what} ${where}`;
}
</script>

<template>
  <div class="rules">
    <p v-if="!model.length" class="empty">
      Sem regras: a tabela ainda não dá desconto em nada. Adicione a primeira (ex.: 20% em Moda praia).
    </p>
    <article v-for="(r, i) in model" :key="r.id ?? `new-${i}`" class="rule" :class="{ off: !r.is_enabled }">
      <header class="rule__head">
        <span class="prio" :title="'Prioridade: a 1ª regra que pega o produto vale'">{{ i + 1 }}</span>
        <InputText :model-value="r.name" placeholder="Nome da regra (ex.: Moda praia -20%)" class="rule__name"
                   :disabled="disabled" :aria-label="`Nome da regra ${i + 1}`" @update:model-value="update(i, { name: String($event ?? '') })" />
        <small class="rule__sum">{{ summary(r) }}</small>
        <span class="rule__tools">
          <ToggleSwitch :model-value="r.is_enabled" :disabled="disabled" :title="r.is_enabled ? 'Ligada' : 'Desligada'"
                        :aria-label="`Ligar regra ${i + 1}`" @update:model-value="update(i, { is_enabled: $event })" />
          <Button icon="pi pi-arrow-up" text rounded size="small" severity="secondary" :disabled="disabled || i === 0"
                  aria-label="Subir prioridade" @click="move(i, -1)" />
          <Button icon="pi pi-arrow-down" text rounded size="small" severity="secondary" :disabled="disabled || i === model.length - 1"
                  aria-label="Descer prioridade" @click="move(i, 1)" />
          <Button icon="pi pi-trash" text rounded size="small" severity="danger" :disabled="disabled"
                  :aria-label="`Remover regra ${i + 1}`" @click="remove(i)" />
        </span>
      </header>

      <div class="rule__grid">
        <label class="c6">Vale para
          <SelectButton :model-value="r.target" :options="TARGETS" option-label="label" option-value="value" :allow-empty="false"
                        :disabled="disabled" @update:model-value="update(i, { target: $event })" />
        </label>
        <label class="c4">Desconto
          <SelectButton :model-value="r.kind" :options="KINDS" option-label="label" option-value="value" :allow-empty="false"
                        :disabled="disabled" @update:model-value="update(i, { kind: $event })" />
        </label>
        <label class="c2">{{ r.kind === "percent" ? "Percentual" : r.kind === "amount" ? "Valor abatido" : "Preço fixo" }}
          <InputNumber :model-value="r.value === null ? null : Number(r.value)" :min="0" :max="r.kind === 'percent' ? 100 : undefined"
                       :min-fraction-digits="r.kind === 'percent' ? 0 : 2" :max-fraction-digits="2" locale="pt-BR"
                       :suffix="r.kind === 'percent' ? ' %' : undefined" :prefix="r.kind === 'percent' ? undefined : 'R$ '"
                       fluid :disabled="disabled" @update:model-value="update(i, { value: $event === null ? null : Number($event).toFixed(2) })" />
        </label>

        <label v-if="r.target === 'categories'" class="c12">Categorias (as de dentro entram)
          <RelationSelect :model-value="r.categories" :relation="{ endpoint: '/catalog/categories/' }" multiple
                          :disabled="disabled" @update:model-value="update(i, { categories: ($event ?? []) as string[] })" />
        </label>
        <label v-else-if="r.target === 'brands'" class="c12">Marcas
          <RelationSelect :model-value="r.brands" :relation="{ endpoint: '/catalog/brands/' }" multiple :disabled="disabled"
                          @update:model-value="update(i, { brands: ($event ?? []) as string[] })" />
        </label>
        <div v-else-if="r.target === 'products'" class="c12 products">
          <span class="products__label">Produtos <small>— "por" opcional: vence o desconto da regra (preço de encarte)</small></span>
          <div v-for="(p, j) in r.products" :key="j" class="products__row">
            <RelationSelect :model-value="p.product" :relation="{ endpoint: '/catalog/products/' }" :disabled="disabled"
                            placeholder="Produto" @update:model-value="updateProduct(i, j, { product: ($event ?? null) as string | null })" />
            <InputNumber :model-value="p.promotional_price === null ? null : Number(p.promotional_price)" mode="currency"
                         currency="BRL" locale="pt-BR" placeholder="Por (opcional)" :disabled="disabled" class="por"
                         @update:model-value="updateProduct(i, j, { promotional_price: $event === null ? null : Number($event).toFixed(2) })" />
            <Button icon="pi pi-times" text rounded size="small" severity="secondary" :disabled="disabled" aria-label="Tirar produto"
                    @click="removeProduct(i, j)" />
          </div>
          <Button label="Adicionar produto" icon="pi pi-plus" text size="small" :disabled="disabled" class="products__add"
                  @click="addProduct(i)" />
        </div>
        <p v-else class="c12 all">Vale para todos os produtos da loja.</p>

        <div class="c12 period">
          <button v-if="!periodOpen[i] && !r.starts_at && !r.ends_at" type="button" class="period__open" :disabled="disabled"
                  @click="periodOpen = { ...periodOpen, [i]: true }">
            <i class="pi pi-calendar" /> Período próprio (sem ele, vale o da tabela)
          </button>
          <template v-else>
            <label>Começa
              <DatePicker :model-value="asDate(r.starts_at)" show-time date-format="dd/mm/yy" show-icon fluid :disabled="disabled"
                          @update:model-value="update(i, { starts_at: $event ? ($event as Date).toISOString() : null })" />
            </label>
            <label>Termina
              <DatePicker :model-value="asDate(r.ends_at)" show-time date-format="dd/mm/yy" show-icon fluid :disabled="disabled"
                          @update:model-value="update(i, { ends_at: $event ? ($event as Date).toISOString() : null })" />
            </label>
          </template>
        </div>
      </div>
    </article>
    <Button label="Adicionar regra" icon="pi pi-plus" severity="secondary" outlined size="small" class="add" :disabled="disabled"
            @click="add" />
  </div>
</template>

<style scoped>
.rules { display: flex; flex-direction: column; gap: 10px; }
.empty { margin: 0; font-size: 13px; color: var(--text-muted); }
.rule { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px 12px; background: var(--surface-card); }
.rule.off { opacity: 0.65; border-style: dashed; }
.rule__head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.prio { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
        background: var(--brand-subtle); color: var(--text-brand); font: 800 12px/1 var(--font-sans); }
.rule__name { flex: 1; min-width: 200px; max-width: 360px; font-weight: 600; }
.rule__sum { color: var(--text-muted); font-size: 12.5px; }
.rule__tools { margin-left: auto; display: flex; align-items: center; gap: 2px; }
.rule__tools :deep(.p-toggleswitch) { margin-right: 6px; }
.rule__grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 10px 12px; }
.rule__grid label, .products__label { display: flex; flex-direction: column; gap: 6px; font-size: 12px; font-weight: 600;
                                      color: var(--text-muted); min-width: 0; }
.c2 { grid-column: span 2; } .c4 { grid-column: span 4; } .c6 { grid-column: span 6; } .c12 { grid-column: span 12; }
.products { display: flex; flex-direction: column; gap: 6px; }
.products__label small { font-weight: 400; }
.products__row { display: grid; grid-template-columns: minmax(0, 1fr) 170px 36px; gap: 8px; align-items: center; }
.products__add { align-self: flex-start; }
.all { margin: 0; font-size: 13px; color: var(--text-muted); }
.period { display: flex; gap: 12px; flex-wrap: wrap; }
.period label { flex: 1; min-width: 200px; }
.period__open { border: 0; background: transparent; color: var(--text-brand); cursor: pointer; font: 600 12.5px/1 var(--font-sans);
                display: flex; gap: 6px; align-items: center; padding: 4px 0; }
.add { align-self: flex-start; }
@media (max-width: 900px) { .rule__grid > * { grid-column: span 12; } }
</style>
