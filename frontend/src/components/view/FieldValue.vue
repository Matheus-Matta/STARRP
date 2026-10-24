<script setup lang="ts">
/**
 * O valor de UM campo para leitura: dinheiro formatado, "Sim/Não" com ícone, o
 * rótulo da opção (não o código), o nome do registro relacionado (não o id),
 * tags como etiquetas... Campos compostos (itens, parcelas, variantes) viram tabela.
 */
import { computed } from "vue";

import type { ColumnDef, FieldDef, Tone } from "@/resources/types";
import { formatDocument } from "@/utils/documents";
import { applyMask, formatPhone, MASKS } from "@/utils/masks";
import { date, dateTime, money, percent, quantity } from "@/utils/format";

import RelationValue from "./RelationValue.vue";
import ViewTable from "./ViewTable.vue";

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
/** Campo do formulário ou item da visualização (que aceita também `tag` com cores). */
export type ViewField = Omit<FieldDef, "type"> & {
  type: FieldDef["type"] | "tag"; map?: Record<string, string>; tones?: Record<string, Tone>;
};
const props = defineProps<{ field: ViewField; values: Row }>();
const value = computed(() => props.values[props.field.name]);
const empty = computed(() => value.value === null || value.value === undefined || value.value === ""
  || (Array.isArray(value.value) && !value.value.length));
/** O serializer costuma mandar o nome junto (`warehouse_name`, `supplier_name`): evita buscar. */
const relationName = computed(() => props.values[`${props.field.name}_name`]
  ?? props.values[props.field.name.replace(/^financial_/, "") + "_name"]);
const option = computed(() => props.field.options?.find((o) => String(o.value) === String(value.value))?.label);

const TABLES: Record<string, { columns: ColumnDef[]; rows: (v: Row[]) => Row[] }> = {
  "stock-items": {
    columns: [
      { key: "variant_name", label: "Produto", title: true }, { key: "sku", label: "SKU" },
      { key: "quantity", label: "Qtd.", type: "quantity", total: true }, { key: "unit_cost", label: "Custo unit.", type: "money" },
      { key: "total_cost", label: "Total", type: "money", total: true }, { key: "lot_number", label: "Lote" },
      { key: "expires_at", label: "Validade", type: "date" },
    ],
    rows: (v) => v,
  },
  installments: {
    columns: [
      { key: "number", label: "Parcela", title: true }, { key: "due_date", label: "Vencimento", type: "date" },
      { key: "amount", label: "Valor", type: "money", total: true }, { key: "paid_amount", label: "Pago", type: "money", total: true },
      { key: "paid_at", label: "Pago em", type: "date" },
      { key: "status", label: "Situação", type: "tag", map: { open: "Em aberto", partial: "Parcial", paid: "Pago", cancelled: "Cancelado" },
        tones: { paid: "success", partial: "warning", cancelled: "neutral", open: "info" } },
    ],
    rows: (v) => v,
  },
  variants: {
    columns: [
      { key: "label", label: "Variante", title: true }, { key: "sku", label: "SKU" },
      { key: "codes", label: "Códigos" }, { key: "price", label: "Preço", type: "money" },
      { key: "promotional_price", label: "Promoção", type: "money" }, { key: "is_active", label: "Ativa", type: "boolean" },
    ],
    rows: (v) => v.map((row) => ({
      ...row, label: (row.options ?? []).map((o: Row) => o.value).join(" / ") || "Padrão",
      codes: (row.barcodes ?? []).map((b: Row) => b.code).join(", "),
    })),
  },
  addresses: {
    columns: [
      { key: "label", label: "Endereço", title: true }, { key: "line", label: "Logradouro" }, { key: "place", label: "Bairro / cidade" },
      { key: "zip", label: "CEP" }, { key: "reference", label: "Referência" }, { key: "star", label: "Padrão" },
    ],
    rows: (v) => v.map((a) => ({ ...a, line: [a.street, a.number, a.complement].filter(Boolean).join(", "),
      place: [a.district, [a.city, a.state].filter(Boolean).join(" - ")].filter(Boolean).join(" · "),
      zip: applyMask(a.zip_code, MASKS.cep), star: a.is_default ? "★ Padrão" : "" })),
  },
  "promotion-rules": {
    columns: [
      { key: "position", label: "Prioridade" }, { key: "name", label: "Regra", title: true },
      { key: "what", label: "Desconto" }, { key: "where", label: "Vale para" },
      { key: "is_enabled", label: "Ligada", type: "boolean" },
    ],
    rows: (v) => v.map((r, i) => ({
      ...r, position: i + 1,
      what: r.kind === "percent" ? `${Number(r.value).toLocaleString("pt-BR")}%`
        : r.kind === "amount" ? `R$ ${Number(r.value).toFixed(2).replace(".", ",")} off` : `por R$ ${Number(r.value).toFixed(2).replace(".", ",")}`,
      where: r.target === "all" ? "Tudo" : r.target === "categories" ? `${(r.categories ?? []).length} categoria(s)`
        : r.target === "brands" ? `${(r.brands ?? []).length} marca(s)`
          : (r.products ?? []).map((p: Row) => p.product_name).filter(Boolean).join(", "),
    })),
  },
  "zip-ranges": {
    columns: [
      { key: "label", label: "Faixa", title: true }, { key: "start", label: "CEP inicial" }, { key: "end", label: "CEP final" },
      { key: "value", label: "Valor", type: "money" }, { key: "days", label: "Prazo" },
    ],
    rows: (v) => v.map((r) => ({ ...r, label: r.label || "—", start: applyMask(r.zip_start, MASKS.cep),
      end: applyMask(r.zip_end, MASKS.cep), days: r.lead_days === null || r.lead_days === undefined ? "da tabela" : `${r.lead_days} dia(s)` })),
  },
  volumes: {
    columns: [
      { key: "number", label: "Caixa", title: true }, { key: "description", label: "Conteúdo" },
      { key: "size", label: "C × L × A (cm)" }, { key: "gross_weight", label: "Peso (kg)", type: "quantity" },
      { key: "barcode", label: "Código" },
    ],
    rows: (v) => v.map((row, i) => ({ ...row, number: `Vol ${i + 1}`,
      size: [row.length_cm, row.width_cm, row.height_cm].every(Boolean)
        ? `${row.length_cm} × ${row.width_cm} × ${row.height_cm}` : "" })),
  },
};
/** Metacampos: objeto {chave: valor} vira tabela (as chaves "_" são do sistema). */
const METAFIELDS = {
  columns: [{ key: "key", label: "Chave", title: true }, { key: "value", label: "Valor" }] as ColumnDef[],
  rows: (v: Row[]) => v,
};
const table = computed(() => {
  if (props.field.type !== "metafields") return TABLES[props.field.type];
  return { ...METAFIELDS, rows: () => Object.entries((value.value ?? {}) as Row).filter(([k]) => !k.startsWith("_"))
    .map(([key, v]) => ({ key, value: typeof v === "boolean" ? (v ? "Sim" : "Não") : typeof v === "object" ? JSON.stringify(v) : String(v) })) };
});
const photos = computed(() => (Array.isArray(value.value) ? value.value : []) as { url: string; alt?: string }[]);
const tag = computed(() => ({ label: props.field.map?.[String(value.value)] ?? option.value ?? String(value.value),
                              tone: props.field.tones?.[String(value.value)] ?? "brand" }));

const text = computed(() => {
  const v = value.value;
  switch (props.field.type) {
    case "money": return money(v);
    case "percent": return percent(v);
    case "quantity": case "measure": return quantity(v);
    case "number": return Number(v).toLocaleString("pt-BR");
    case "date": return date(v);
    case "datetime": return dateTime(v);
    case "document": return formatDocument(String(v));
    case "phone": return formatPhone(v);
    case "cep": return applyMask(v, MASKS.cep);
    case "select": case "segmented": return option.value ?? String(v);
    case "multiselect": return (v as unknown[]).map((x) => props.field.options?.find((o) => o.value === x)?.label ?? x).join(", ");
    default: return props.field.mask ? applyMask(v, props.field.mask) : String(v);
  }
});
</script>

<template>
  <div v-if="table" class="fv-table">
    <ViewTable :columns="table.columns" :rows="table.rows((value ?? []) as Row[])" empty="Nenhum item." />
  </div>
  <span v-else-if="field.type === 'boolean'" class="fv-bool" :class="{ on: value }">
    <i :class="value ? 'pi pi-check-circle' : 'pi pi-minus-circle'" /> {{ value ? "Sim" : "Não" }}
  </span>
  <span v-else-if="field.type === 'password'" :class="values[`has_${field.name}`] ? '' : 'muted'">
    {{ values[`has_${field.name}`] ? "•••••••• (guardado)" : "Não definido" }}
  </span>
  <span v-else-if="empty" class="muted">—</span>
  <span v-else-if="field.type === 'tag'" class="pill" :class="`pill--${tag.tone}`">{{ tag.label }}</span>
  <span v-else-if="field.type === 'relation'">
    <template v-if="relationName">{{ relationName }}</template>
    <RelationValue v-else :relation="field.relation!" :id="value" />
  </span>
  <span v-else-if="field.type === 'multirelation'" class="fv-chips">
    <span v-for="id in value as unknown[]" :key="String(id)" class="fv-chip"><RelationValue :relation="field.relation!" :id="id" /></span>
  </span>
  <span v-else-if="field.type === 'tags'" class="fv-chips">
    <span v-for="tag in value as string[]" :key="tag" class="fv-chip"><i class="pi pi-tag" /> {{ tag }}</span>
  </span>
  <span v-else-if="field.type === 'barcodes'" class="fv-chips">
    <span v-for="code in value as Row[]" :key="code.code ?? code" class="fv-chip mono">{{ code.code ?? code }}</span>
  </span>
  <span v-else-if="field.type === 'color'" class="fv-color"><i :style="{ background: String(value) }" /> {{ value }}</span>
  <a v-else-if="field.type === 'email'" :href="`mailto:${value}`">{{ value }}</a>
  <p v-else-if="field.type === 'textarea'" class="fv-text">{{ value }}</p>
  <div v-else-if="field.type === 'images'" class="fv-photos">
    <img v-for="(item, index) in photos" :key="item.url" :src="item.url" :alt="item.alt || ''"
         :class="{ cover: index === 0 }" loading="lazy" />
  </div>
  <!-- HTML já limpo pelo servidor (core/text.clean_html) ao salvar. -->
  <div v-else-if="field.type === 'richtext'" class="fv-rich" v-html="value" />
  <span v-else :class="{ num: ['money', 'quantity', 'percent', 'number', 'measure'].includes(field.type) }">{{ text }}</span>
</template>

<style scoped>
.fv-table { margin: 8px -16px -12px; border-top: 1px solid var(--border-subtle); }
.fv-bool { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); }
.fv-bool.on { color: var(--success-text); }
.fv-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.fv-chip {
  display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 6px; font-size: 12.5px; font-weight: 600;
  background: var(--surface-hover); color: var(--text-body);
}
.fv-chip i { font-size: 10px; color: var(--text-subtle); }
.mono { font-family: var(--font-mono, monospace); font-weight: 500; }
.fv-color { display: inline-flex; align-items: center; gap: 8px; }
.fv-color i { width: 16px; height: 16px; border-radius: 4px; border: 1px solid var(--border); }
.fv-text { margin: 0; white-space: pre-wrap; line-height: 1.55; }
.fv-rich { line-height: 1.6; font-weight: 400; }
.fv-photos { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 8px; }
.fv-photos img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; border: 1px solid var(--border-subtle); }
.fv-photos img.cover { outline: 2px solid var(--brand); outline-offset: 1px; }
.fv-rich :deep(p) { margin: 0 0 0.5em; }
.fv-rich :deep(ul), .fv-rich :deep(ol) { margin: 0.3em 0 0.6em; padding-left: 1.3em; }
.fv-rich :deep(h2), .fv-rich :deep(h3) { margin: 0.6em 0 0.3em; font-size: 15px; }
.fv-rich :deep(a) { color: var(--text-brand); }
.num { font-variant-numeric: tabular-nums; }
</style>
