<script setup lang="ts">
/**
 * O registro para LER (confirmado, só leitura ou sem permissão de editar), no
 * lugar dos campos desabilitados. Mesmo cuidado do formulário:
 *
 *   ┌ números de destaque ──────────────────────────────────────┐
 *   │ Seção (título + explicação)          │ Resumo              │
 *   │ ┌ rótulo: valor  rótulo: valor ┐     │ ┌ rótulo ... valor ┐ │
 *   └──────────────────────────────────────┴─────────────────────┘
 *   Itens (tabela na largura toda)
 *   (o histórico vem depois, no fim da página: `HistoryFeed`)
 *
 * Cada cadastro descreve as suas seções no `display`; sem ele, as seções do
 * formulário viram a página.
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";

import CellValue from "@/components/resource/CellValue.vue";
import FieldValue, { type ViewField } from "@/components/view/FieldValue.vue";
import ViewTable from "@/components/view/ViewTable.vue";
import {
  type DisplayItem, type DisplaySection, type FieldDef, type FormActionContext, type ResourceDef,
} from "@/resources/types";

type Values = Record<string, unknown>;
const props = defineProps<{ resource: ResourceDef; ctx: FormActionContext }>();
const values = computed(() => props.ctx.values);
const display = computed(() => props.resource.display ?? {});
const WIDE = ["textarea", "stock-items", "installments", "variants", "volumes", "grid", "tags", "multirelation", "barcodes"];
const TABLE = ["stock-items", "installments", "variants", "volumes", "addresses", "zip-ranges", "metafields",
               "promotion-rules"];

const stats = computed(() => (display.value.stats ?? []).filter((s) => !s.visible || s.visible(values.value)));

/** Item pronto para desenhar: o campo (como o FieldValue entende) e os valores onde ele lê. */
type Row = { key: string; field: ViewField; values: Values; link?: string; hint?: string; span: string; strong?: boolean;
             tone?: string };

function fromField(field: FieldDef): Row {
  return { key: field.name, field, values: values.value,
           span: field.full || WIDE.includes(field.type) ? "full" : field.span && field.span >= 4 ? "wide" : "" };
}

function fromItem(item: DisplayItem, index: number): Row {
  const name = item.key ?? `__item${index}`;
  const v = item.value ? { ...values.value, [name]: item.value(values.value) } : values.value;
  const options = item.map ? Object.entries(item.map).map(([value, label]) => ({ value, label })) : undefined;
  return {
    key: name, values: v, span: item.span ?? "", strong: item.strong, tone: item.tone?.(values.value),
    link: item.link?.(values.value) || undefined, hint: item.hint?.(values.value) ?? undefined,
    field: { name, label: item.label, type: item.type ?? "text", relation: item.relation, options, map: item.map, tones: item.tones },
  };
}

type Block = { title: string; icon?: string; description?: string; rows: Row[]; table?: Row; grid?: DisplaySection["table"] };

function build(section: DisplaySection): Block {
  const byName = new Map(props.resource.fields.map((f) => [f.name, f]));
  const fieldRows = (section.fields ?? []).map((n) => byName.get(n)).filter((f): f is FieldDef => !!f)
    .filter((f) => !f.visible || f.visible(values.value)).map(fromField);
  const itemRows = (section.items ?? []).filter((i) => !i.visible || i.visible(values.value)).map(fromItem);
  const description = typeof section.description === "function" ? section.description(values.value) : section.description;
  return { title: section.title, icon: section.icon, description, rows: [...fieldRows, ...itemRows], grid: section.table };
}

/** Sem `display.sections`: as seções do formulário, com as mesmas explicações. */
const formBlocks = computed<Block[]>(() => {
  const hidden = new Set(display.value.hide ?? []);
  const groups = new Map<string, FieldDef[]>();
  for (const field of props.resource.fields) {
    if (hidden.has(field.name) || (field.type === "password" && !(`has_${field.name}` in values.value))) continue;
    if (field.visible && !field.visible(values.value)) continue;
    if (field.type === "seo-preview") continue;  // prévia do Google é só para quem está editando
    const name = field.section ?? "Dados";
    groups.set(name, [...(groups.get(name) ?? []), field]);
  }
  return [...groups.entries()].map(([name, fields]) => {
    const info = props.resource.sections?.[name];
    const only = fields.length === 1 && TABLE.includes(fields[0]!.type);
    return { title: name, icon: info?.icon, description: info?.description,
             rows: only ? [] : fields.map(fromField), table: only ? fromField(fields[0]!) : undefined };
  });
});

const main = computed(() => (display.value.sections
  ? display.value.sections.filter((s) => !s.visible || s.visible(values.value)).map(build)
  : formBlocks.value));
const aside = computed(() => (display.value.aside ?? []).filter((s) => !s.visible || s.visible(values.value)).map(build)
  .filter((b) => b.rows.length));
const hasSide = computed(() => aside.value.length > 0);
/** Tabelas (itens, pagamentos) ocupam a largura toda, abaixo do bloco com a lateral. */
const isTable = (b: Block) => Boolean(b.grid || b.table);
const top = computed(() => main.value.filter((b) => !isTable(b)));
const wide = computed(() => main.value.filter(isTable));
</script>

<template>
  <component :is="display.component" v-if="display.component" :ctx="ctx" />
  <div v-else-if="main.length || stats.length" class="rv">
    <div v-if="stats.length" class="rv-stats">
      <div v-for="stat in stats" :key="stat.label" class="rv-stat">
        <span class="rv-stat__label"><i v-if="stat.icon" :class="stat.icon" /> {{ stat.label }}</span>
        <strong class="rv-stat__value"
                :class="[stat.tone?.(values) && `tone-${stat.tone(values)}`, { 'rv-stat__value--date': ['date', 'datetime'].includes(stat.type ?? '') }]">
          <CellValue v-if="stat.type" :column="{ key: stat.label, label: stat.label, type: stat.type }" :value="stat.value(values)" />
          <template v-else>{{ stat.value(values) ?? "—" }}</template>
        </strong>
        <small v-if="stat.hint?.(values)">{{ stat.hint(values) }}</small>
      </div>
    </div>

    <div class="rv-body" :class="{ 'rv-body--side': hasSide }">
      <div class="rv-main">
        <section v-for="block in top" :key="block.title" class="rv-sec">
          <header class="rv-sec__head">
            <h2><i v-if="block.icon" :class="block.icon" /> {{ block.title }}
              <small v-if="block.grid">{{ block.grid.rows(values).length }}</small></h2>
            <p v-if="block.description">{{ block.description }}</p>
          </header>
          <div class="rv-card" :class="{ 'rv-card--flush': block.grid || block.table }">
            <ViewTable v-if="block.grid" :columns="typeof block.grid.columns === 'function' ? block.grid.columns(values) : block.grid.columns"
                       :rows="block.grid.rows(values)" :empty="block.grid.empty" />
            <FieldValue v-else-if="block.table" :field="block.table.field" :values="block.table.values" class="rv-flush" />
            <dl v-else class="rv-grid">
              <div v-for="row in block.rows" :key="row.key" class="rv-item" :class="[row.span, row.tone && `tone-${row.tone}`, { strong: row.strong }]">
                <dt>{{ row.field.label }}</dt>
                <dd>
                  <RouterLink v-if="row.link" :to="row.link" class="rv-link">
                    <FieldValue :field="row.field" :values="row.values" /> <i class="pi pi-arrow-up-right" />
                  </RouterLink>
                  <FieldValue v-else :field="row.field" :values="row.values" />
                  <small v-if="row.hint" class="rv-hint">{{ row.hint }}</small>
                </dd>
              </div>
            </dl>
          </div>
        </section>
      </div>

      <aside v-if="hasSide" class="rv-side">
        <section v-for="block in aside" :key="block.title" class="rv-sec">
          <header class="rv-sec__head"><h2><i v-if="block.icon" :class="block.icon" /> {{ block.title }}</h2></header>
          <dl class="rv-card rv-list">
            <div v-for="row in block.rows" :key="row.key" class="rv-list__row" :class="[row.tone && `tone-${row.tone}`, { strong: row.strong }]">
              <dt>{{ row.field.label }}</dt>
              <dd>
                <RouterLink v-if="row.link" :to="row.link" class="rv-link"><FieldValue :field="row.field" :values="row.values" /></RouterLink>
                <FieldValue v-else :field="row.field" :values="row.values" />
              </dd>
            </div>
          </dl>
        </section>

      </aside>
    </div>

        <section v-for="block in wide" :key="block.title" class="rv-sec">
      <header class="rv-sec__head">
        <h2><i v-if="block.icon" :class="block.icon" /> {{ block.title }}
          <small v-if="block.grid">{{ block.grid.rows(values).length }}</small></h2>
        <p v-if="block.description">{{ block.description }}</p>
      </header>
      <div class="rv-card" :class="{ 'rv-card--flush': block.grid || block.table }">
        <ViewTable v-if="block.grid" :columns="typeof block.grid.columns === 'function' ? block.grid.columns(values) : block.grid.columns"
                   :rows="block.grid.rows(values)" :empty="block.grid.empty" />
        <FieldValue v-else-if="block.table" :field="block.table.field" :values="block.table.values" class="rv-flush" />
        <dl v-else class="rv-grid">
          <div v-for="row in block.rows" :key="row.key" class="rv-item" :class="[row.span, row.tone && `tone-${row.tone}`, { strong: row.strong }]">
            <dt>{{ row.field.label }}</dt>
            <dd>
              <RouterLink v-if="row.link" :to="row.link" class="rv-link">
                <FieldValue :field="row.field" :values="row.values" /> <i class="pi pi-arrow-up-right" />
              </RouterLink>
              <FieldValue v-else :field="row.field" :values="row.values" />
              <small v-if="row.hint" class="rv-hint">{{ row.hint }}</small>
            </dd>
          </div>
        </dl>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rv { display: flex; flex-direction: column; gap: 14px; }

.rv-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.rv-stat {
  display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border-radius: 10px;
  background: var(--surface-card); border: 1px solid var(--border); box-shadow: var(--shadow-xs);
}
.rv-stat__label { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.rv-stat__label i { font-size: 12px; color: var(--text-subtle); }
.rv-stat__value { font: 700 21px/1.2 var(--font-sans); color: var(--text-strong); letter-spacing: -0.01em; }
.rv-stat__value :deep(.num) { font-weight: inherit; color: inherit; }
.rv-stat__value--date { font-size: 17px; }
.rv-stat small { font-size: 12px; color: var(--text-muted); }
.tone-success { --tone: var(--success-text); }
.tone-danger { --tone: var(--danger-text); }
.tone-warning { --tone: var(--warning-text); }
.tone-info { --tone: var(--info-text); }
.tone-brand { --tone: var(--text-brand); }
.tone-neutral { --tone: var(--text-subtle); }
.rv-stat__value[class*="tone-"] { color: var(--tone); }

/* Corpo: coluna principal + lateral (resumo e histórico) a partir de 1100px. */
.rv-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px 18px; align-items: start; }
@media (min-width: 1100px) { .rv-body--side { grid-template-columns: minmax(0, 1fr) 320px; } }
.rv-main, .rv-side { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.rv-side { position: sticky; top: 12px; }

/* Seção igual à do formulário: título e explicação em cima, cartão embaixo. */
.rv-sec { display: flex; flex-direction: column; gap: 0.55rem; }
.rv-sec__head { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; padding: 0 2px; }
.rv-sec__head h2 { margin: 0; display: flex; align-items: center; gap: 0.45rem; font: 600 14px/1.3 var(--font-sans); color: var(--text-strong); }
.rv-sec__head h2 i { font-size: 13px; color: var(--brand); }
.rv-sec__head h2 small { font-size: 12px; color: var(--text-muted); font-weight: 600; }
.rv-sec__head p { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--text-muted); }
.rv-card { background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow-xs); margin: 0; }
.rv-card--flush { overflow: hidden; }

/* Lista de descrição (PrimeBlocks): rótulo pequeno em cima, valor embaixo. */
.rv-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px 0; margin: 0; padding: 8px 0; }
.rv-item { padding: 8px 18px; min-width: 0; }
.rv-item.wide { grid-column: span 2; }
.rv-item.full { grid-column: 1 / -1; }
.rv-item dt { font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 3px; }
.rv-item dd { margin: 0; font-size: 14px; font-weight: 500; color: var(--text-strong); overflow-wrap: anywhere; }
.rv-item.strong dd { font-size: 16px; font-weight: 700; }
.rv-item[class*="tone-"] dd { color: var(--tone); }
.rv-hint { display: block; font-size: 12px; color: var(--text-muted); font-weight: 400; margin-top: 2px; }
.rv-link { display: inline-flex; align-items: center; gap: 5px; color: var(--text-brand); text-decoration: none; font-weight: 600; }
.rv-link:hover { text-decoration: underline; }
.rv-link i { font-size: 10px; }
.rv-flush { margin: 0; border: 0; }

/* Lateral: rótulo à esquerda, valor à direita. */
.rv-list { padding: 4px 0; }
.rv-list__row { display: flex; justify-content: space-between; gap: 12px; padding: 8px 16px; font-size: 13.5px; }
.rv-list__row + .rv-list__row { border-top: 1px solid var(--border-subtle); }
.rv-list__row dt { color: var(--text-muted); }
.rv-list__row dd { margin: 0; text-align: right; font-weight: 600; color: var(--text-strong); }
.rv-list__row.strong dd { font-size: 15.5px; font-weight: 700; }
.rv-list__row.strong { background: var(--surface-sunken, var(--surface-hover)); }
.rv-list__row[class*="tone-"] dd { color: var(--tone); }

@media (max-width: 900px) {
  .rv-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rv-side { position: static; }
}
@media (max-width: 560px) {
  .rv-grid { grid-template-columns: 1fr; }
  .rv-item.wide { grid-column: 1 / -1; }
}
</style>
