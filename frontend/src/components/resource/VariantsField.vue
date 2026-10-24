<script setup lang="ts">
/**
 * Variantes do produto — o que se vende e se estoca (SKU, preço, códigos, caixas).
 *
 * - Simples, kit e serviço: UMA variante, editada aqui mesmo como se fosse o produto.
 * - Com variação: tabela com uma linha por combinação da grade; cada linha
 *   abre os detalhes (códigos de barras, estoque mínimo, medidas e volumes).
 */
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Tag from "primevue/tag";
import ToggleSwitch from "primevue/toggleswitch";
import { computed, ref, watch } from "vue";

import type { FieldDef } from "@/resources/types";

import FormField from "./FormField.vue";

type Option = { attribute: string; value: string; value_id: string };
export type VariantRow = Record<string, unknown> & {
  id?: string; name?: string; sku?: string; price?: string | null; promotional_price?: string | null;
  is_default?: boolean; is_active?: boolean; options?: Option[];
};

const props = defineProps<{ context?: Record<string, unknown>; errors?: string }>();
const model = defineModel<VariantRow[]>({ default: () => [] });
const open = ref<Set<number>>(new Set());

const variable = computed(() => props.context?.type === "variable");

/**
 * Prévia da grade ainda não salva (`context.grid`): o que o salvar vai fazer.
 * Ex.: grade Tamanho [P, M] × Cor [Azul] → "M / Azul" aparece como NOVA com o SKU
 * CAM-M-AZU; se o eixo Cor sair, "P / Preto" aparece riscada (vai sair).
 */
type Grid = Record<string, string[]>;
const grid = computed(() => props.context?.grid as Grid | null | undefined);
const norm = (text: string) => text.trim().toLowerCase();
const code = (text: string) => text.normalize("NFD").replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 3) || "X";
const base = computed(() => String(props.context?.reference || model.value.find((r) => r.is_default)?.sku
  || String(props.context?.name ?? "").replace(/\W/g, "").toUpperCase().slice(0, 8)));
/** A chave da variante só com os eixos da grade nova (como o servidor junta ao tirar um eixo). */
function keyOf(row: VariantRow, axes: string[]) {
  const byAxis = new Map((row.options ?? []).map((o) => [norm(o.attribute), norm(o.value)]));
  return axes.map((axis) => byAxis.get(norm(axis)) ?? "").join("|");
}
const leaving = computed(() => {
  if (!grid.value) return new Set<number>();
  const axes = Object.keys(grid.value);
  const out = new Set<number>();
  const seen = new Set<string>();
  model.value.forEach((row, index) => {
    const byAxis = new Map((row.options ?? []).map((o) => [norm(o.attribute), norm(o.value)]));
    const lostValue = axes.some((axis) => byAxis.has(norm(axis))
      && !grid.value![axis]!.some((v) => norm(v) === byAxis.get(norm(axis))));
    const key = keyOf(row, axes);
    if (lostValue || seen.has(key)) out.add(index);
    else seen.add(key);
  });
  return out;
});
const fresh = computed(() => {
  if (!grid.value) return [];
  const axes = Object.entries(grid.value).filter(([, values]) => values.length);
  if (!axes.length) return [];
  // Variante que fica e não tem um eixo novo ganha o 1º valor dele (como o servidor faz).
  const kept = new Set(model.value.filter((_, i) => !leaving.value.has(i)).map((row) => keyOf(row, axes.map(([a]) => a))
    .split("|").map((part, i) => part || norm(axes[i]![1][0]!)).join("|")));
  const combos = axes.reduce<string[][]>((acc, [, values]) => acc.flatMap((c) => values.map((v) => [...c, v])), [[]]);
  return combos.filter((combo) => !kept.has(combo.map(norm).join("|")))
    .map((combo) => ({ label: combo, sku: `${base.value}-${combo.map(code).join("-")}` }));
});
const byWeight = computed(() => props.context?.sale_method === "weight");
const keepsStock = computed(() => !["kit", "service"].includes(String(props.context?.type ?? "")));

function blank(isDefault: boolean): VariantRow {
  return { sku: "", price: null, promotional_price: null, is_default: isDefault, is_active: true, barcodes: [], volumes: [] };
}

watch(variable, (isVariable) => {
  if (!isVariable && model.value.length === 0) model.value = [blank(true)];
}, { immediate: true });

const DETAIL: FieldDef[] = [
  { name: "images", label: "Fotos desta variação", type: "images", full: true,
    hint: "Ex.: a camiseta azul de frente e de costas. A 1ª aparece no PDV quando esta variação é escolhida." },
  { name: "scale_code", label: "PLU da balança", type: "text", maxLength: 6, hint: "Código do item na balança etiquetadora." },
  { name: "min_stock", label: "Estoque mínimo", type: "quantity" },
  { name: "max_stock", label: "Estoque máximo", type: "quantity" },
  { name: "barcodes", label: "Códigos de barras", type: "barcodes", full: true },
  { name: "gross_weight", label: "Peso bruto (kg)", type: "quantity" },
  { name: "net_weight", label: "Peso líquido (kg)", type: "quantity" },
  { name: "height_cm", label: "Altura (cm)", type: "measure" },
  { name: "width_cm", label: "Largura (cm)", type: "measure" },
  { name: "length_cm", label: "Comprimento (cm)", type: "measure" },
  { name: "volumes", label: "Volumes (caixas da unidade)", type: "volumes", full: true },
];
const MAIN: FieldDef[] = [
  { name: "sku", label: "SKU (código interno)", type: "text", maxLength: 60, hint: "Vazio = gerado pela referência." },
  { name: "price", label: "Preço de venda", type: "money", required: true },
  { name: "promotional_price", label: "Preço promocional fixo", type: "money",
    hint: "Sem data. Promoção com período fica nas tabelas de desconto." },
];

/** Some com o que não se aplica: PLU só na balança; estoque e caixas só em quem estoca. */
const details = computed(() => DETAIL.filter((f) => {
  if (f.name === "scale_code") return byWeight.value;
  if (f.name === "images") return variable.value;
  if (["min_stock", "max_stock", "volumes"].includes(f.name)) return keepsStock.value;
  return true;
}));

/** 1ª foto da variante (miniatura na linha). */
const photoOf = (row: VariantRow) => (row.images as { url: string }[] | undefined)?.[0]?.url;

function update(index: number, patch: Partial<VariantRow>) {
  model.value = model.value.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

function setDefault(index: number) {
  model.value = model.value.map((row, i) => ({ ...row, is_default: i === index }));
}

function remove(index: number) {
  const rest = model.value.filter((_, i) => i !== index);
  if (rest.length && !rest.some((r) => r.is_default)) rest[0] = { ...rest[0]!, is_default: true };
  model.value = rest;
  open.value = new Set();
}

function toggle(index: number) {
  const next = new Set(open.value);
  if (next.has(index)) next.delete(index);
  else next.add(index);
  open.value = next;
}

const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));
const money = (v: number | null) => (v === null ? null : v.toFixed(2));
</script>

<template>
  <div class="variants">
    <Message v-if="errors" severity="error" :closable="false">{{ errors }}</Message>

    <!-- Uma variante só: os campos aparecem como se fossem do produto. -->
    <template v-if="!variable">
      <Message v-if="model.length > 1" severity="warn" :closable="false">
        Este produto tem {{ model.length }} variantes. Para manter todas, use o tipo “Com variação”.
      </Message>
      <div v-if="model[0]" class="grid-form">
        <FormField v-for="field in [...MAIN, ...details]" :key="field.name" :field="field"
                   :model-value="model[0][field.name]" @update:model-value="update(0, { [field.name]: $event })" />
      </div>
    </template>

    <!-- Com grade: uma linha por combinação. -->
    <template v-else>
      <p v-if="!model.length && !fresh.length" class="muted empty">
        Nenhuma variante ainda. Monte a grade acima (ex.: Tamanho P, M, G): as combinações aparecem aqui e são criadas ao salvar.
      </p>
      <div v-if="model.length || fresh.length" class="table" role="table">
        <div class="row head" role="row">
          <span>Variação</span><span>SKU</span><span>Preço</span><span>Promocional</span><span>Ativa</span><span />
        </div>
        <template v-for="(row, index) in model" :key="row.id ?? index">
          <div class="row" :class="{ 'row--open': open.has(index), 'row--off': row.is_active === false, 'row--leaving': leaving.has(index) }"
               role="row" :title="leaving.has(index) ? 'Sai ao salvar (a grade não tem mais esta combinação)' : undefined">
            <span class="name">
              <button type="button" class="star" :class="{ on: row.is_default }" :title="row.is_default ? 'Variante padrão' : 'Tornar padrão'"
                      @click="setDefault(index)"><i :class="row.is_default ? 'pi pi-star-fill' : 'pi pi-star'" /></button>
              <span class="chips">
                <Tag v-for="o in row.options ?? []" :key="o.value_id" :value="o.value" severity="secondary" />
                <img v-if="photoOf(row)" :src="photoOf(row)" alt="" class="variant-thumb" />
                <span v-if="!row.options?.length">{{ row.name || "Nova" }}</span>
                <span v-if="leaving.has(index)" class="pill pill--danger">sai ao salvar</span>
              </span>
            </span>
            <InputText :model-value="row.sku" size="small" fluid aria-label="SKU" :invalid="!String(row.sku ?? '').trim()"
                       placeholder="Gerado ao salvar" @update:model-value="update(index, { sku: String($event ?? '') })" />
            <InputNumber :model-value="num(row.price)" mode="currency" currency="BRL" locale="pt-BR" size="small" fluid
                         aria-label="Preço" @update:model-value="update(index, { price: money($event) })" />
            <InputNumber :model-value="num(row.promotional_price)" mode="currency" currency="BRL" locale="pt-BR" size="small"
                         fluid aria-label="Promocional" @update:model-value="update(index, { promotional_price: money($event) })" />
            <ToggleSwitch :model-value="row.is_active !== false" aria-label="Ativa"
                          @update:model-value="update(index, { is_active: $event })" />
            <span class="actions">
              <Button :icon="open.has(index) ? 'pi pi-chevron-up' : 'pi pi-sliders-h'" text rounded size="small"
                      :aria-label="open.has(index) ? 'Fechar detalhes' : 'Detalhes'" @click="toggle(index)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger" aria-label="Excluir variante"
                      @click="remove(index)" />
            </span>
          </div>
          <div v-if="open.has(index)" class="detail grid-form">
            <FormField v-for="field in details" :key="field.name" :field="field" :model-value="row[field.name]"
                       @update:model-value="update(index, { [field.name]: $event })" />
          </div>
        </template>
        <div v-for="item in fresh" :key="item.sku" class="row row--fresh" role="row">
          <span class="name">
            <i class="pi pi-plus-circle fresh-icon" />
            <span class="chips"><Tag v-for="value in item.label" :key="value" :value="value" severity="info" /></span>
          </span>
          <span class="fresh-sku" title="SKU que a variante vai ganhar (pode mudar depois de salvar)">{{ item.sku }}</span>
          <span class="muted fresh-note">Nova: criada ao salvar com o preço da padrão</span>
        </div>
      </div>
      <p v-if="fresh.length || leaving.size" class="muted preview-note">
        <i class="pi pi-info-circle" /> Ao salvar: {{ fresh.length }} {{ fresh.length === 1 ? "variante nova" : "variantes novas" }}<template
          v-if="leaving.size">, {{ leaving.size }} {{ leaving.size === 1 ? "sai" : "saem" }} (variante com estoque não sai: zere antes)</template>.
      </p>
    </template>
  </div>
</template>

<style scoped>
.variants { display: flex; flex-direction: column; gap: 0.75rem; }
.empty { margin: 0; font-size: 13px; }
.table { border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.row {
  display: grid; grid-template-columns: minmax(180px, 1.4fr) 1fr 0.9fr 0.9fr 56px 76px; gap: 0.6rem; align-items: center;
  padding: 0.5rem 0.75rem; border-top: 1px solid var(--border); transition: background-color var(--dur-fast) ease;
}
.row:first-child { border-top: 0; }
.row:not(.head):hover { background: var(--surface-hover); }
.row--open { background: var(--brand-subtle); }
.row--off .name { opacity: 0.55; }
.head { background: var(--surface-sunken); font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
.name { display: flex; align-items: center; gap: 0.5rem; min-width: 0; font-weight: 600; color: var(--text-strong); }
.chips { display: flex; flex-wrap: wrap; gap: 0.25rem; }
.star {
  border: 0; background: transparent; color: var(--text-muted); cursor: pointer; padding: 0.25rem; border-radius: var(--radius-sm);
  transition: color var(--dur-fast) ease, background-color var(--dur-fast) ease;
}
.star:hover { background: var(--surface-sunken); color: var(--warning); }
.star.on { color: var(--warning); }
.actions { display: flex; justify-content: flex-end; }
.detail { padding: 1rem 0.75rem 1.1rem; border-top: 1px dashed var(--border); background: var(--surface-sunken); }
.variant-thumb { width: 26px; height: 26px; border-radius: 6px; object-fit: cover; border: 1px solid var(--border-subtle); }
.row--leaving { background: color-mix(in srgb, var(--danger-subtle) 60%, transparent); }
.row--leaving .chips :deep(.p-tag) { text-decoration: line-through; }
.row--fresh { background: color-mix(in srgb, var(--info-subtle) 55%, transparent); }
.row--fresh .fresh-note { grid-column: span 4; font-size: 12.5px; }
.fresh-icon { color: var(--info-text); }
.fresh-sku { font: 600 13px/1.2 var(--font-mono, monospace); color: var(--text-strong); padding-left: 0.6rem; }
.preview-note { margin: 0; font-size: 12.5px; display: flex; gap: 0.4rem; align-items: center; }
@media (max-width: 900px) {
  .head { display: none; }
  .row { grid-template-columns: 1fr 1fr; }
  .name { grid-column: 1 / -1; }
  .actions { grid-column: 2; }
}
</style>
