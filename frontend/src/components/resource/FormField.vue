<script setup lang="ts">
/** Desenha UM campo a partir da sua descrição (`FieldDef`). */
import ColorPicker from "primevue/colorpicker";
import DatePicker from "primevue/datepicker";
import Editor from "primevue/editor";
import InputNumber from "primevue/inputnumber";
import InputMask from "primevue/inputmask";
import InputText from "primevue/inputtext";
import MultiSelect from "primevue/multiselect";
import Password from "primevue/password";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import Textarea from "primevue/textarea";
import ToggleSwitch from "primevue/toggleswitch";
import { computed, defineAsyncComponent, ref } from "vue";

import { useViewport } from "@/composables/useViewport";
import type { FieldDef } from "@/resources/types";
import { lookupCep, MASKS } from "@/utils/masks";

import BarcodeListField from "./BarcodeListField.vue";
import GridField from "./GridField.vue";
import ImageGallery from "./ImageGallery.vue";
import InstallmentsField from "./InstallmentsField.vue";
import RelationSelect from "./RelationSelect.vue";
import StockItemsField from "./StockItemsField.vue";
import AddressListField from "./AddressListField.vue";
import MetafieldsField from "./MetafieldsField.vue";
import PromotionRulesField from "./PromotionRulesField.vue";
import TagsInput from "./TagsInput.vue";
import ZipRangesField from "./ZipRangesField.vue";
import VolumeListField from "./VolumeListField.vue";

// Assíncrono: VariantsField desenha FormField dentro dele (import circular).
const VariantsField = defineAsyncComponent(() => import("./VariantsField.vue"));

/** `context` = todos os valores do formulário (campos que dependem de outros, como as variantes). */
/** `bare`: o campo É a seção (editor de texto ocupando o cartão inteiro): sem rótulo nem margem. */
const { isPhone } = useViewport();
const props = defineProps<{ field: FieldDef; error?: string; context?: Record<string, unknown>; disabled?: boolean;
                            bare?: boolean }>();
const model = defineModel<unknown>();
/** `reload`: o campo mudou dados no servidor (baixa de parcela) e o formulário precisa reler. */
/** `fill`: o campo preencheu outros (o CEP traz rua, bairro, cidade, UF e IBGE). */
const emit = defineEmits<{ reload: []; fill: [values: Record<string, string>] }>();

/**
 * Máscara do campo: a declarada, ou a do tipo. Documento depende do tipo de pessoa
 * (física = CPF, jurídica ou sem tipo = CNPJ). O valor guardado é só dígitos.
 */
const mask = computed(() => {
  if (props.field.mask) return props.field.mask;
  // Telefone: fixo (10) com 11º opcional; chegando o 11º dígito vira celular "(11) 98765-4321".
  if (props.field.type === "phone") return String(model.value ?? "").replace(/\D/g, "").length >= 11 ? MASKS.mobile : MASKS.phone;
  if (props.field.type === "cep") return MASKS.cep;
  if (props.field.type === "document") return props.context?.person_type === "F" ? MASKS.cpf : MASKS.cnpj;
  return undefined;
});
const cepNote = ref("");
async function onComplete(event: Event) {
  if (props.field.type !== "cep") return;
  cepNote.value = "Buscando o endereço…";
  // O valor do campo, não o do modelo: no "complete" o modelo ainda tem o dígito anterior.
  const found = await lookupCep((event.target as HTMLInputElement).value);
  cepNote.value = found ? "Endereço preenchido pelo CEP." : "CEP não encontrado: preencha o endereço.";
  if (found) emit("fill", found);
}
const length = computed(() => String(model.value ?? "").length);

/** Prévia de como o produto aparece no Google (título, endereço e resumo). */
/** Texto puro do HTML do editor (decodifica &nbsp; e cia., sem executar nada). */
const plain = (html: unknown) => (new DOMParser().parseFromString(String(html ?? ""), "text/html").body.textContent ?? "")
  .replace(/\s+/g, " ").trim();
const seo = computed(() => {
  const v = props.context ?? {};
  const slug = String(v.slug || String(v.name ?? "").normalize("NFD").replace(/[^\w\s-]/g, "").trim().toLowerCase().replace(/\s+/g, "-"));
  return {
    title: String(v.seo_title || v.name || "Título do produto"),
    url: `minhaloja.com.br › produto › ${slug || "endereco"}`,
    text: String(v.seo_description || plain(v.description).slice(0, 160) || "O resumo aparece aqui. Sem resumo, o Google usa o começo da descrição."),
  };
});
const id = computed(() => `f-${props.field.name}`);

const decimals = computed(() => ({ money: 2, percent: 2, quantity: 3, measure: 1, number: 0 })[props.field.type as string] ?? 0);
const WIDE = ["textarea", "barcodes", "variants", "volumes", "grid", "stock-items", "installments", "images", "richtext",
              "addresses", "zip-ranges", "metafields", "promotion-rules"];
/** Campos que já são um bloco com títulos próprios: sem o rótulo de cima. */
const SELF_LABELED = ["variants", "stock-items", "installments", "images", "addresses", "zip-ranges", "metafields",
                      "promotion-rules"];
const sizeClass = computed(() => (props.field.full || WIDE.includes(props.field.type) ? "full"
  : props.field.span ? `span-${props.field.span}` : ""));
const existingOptions = computed(() =>
  ((props.context?.variants ?? []) as { options?: { attribute: string; value: string }[] }[]).map((v) => v.options ?? []));

/** InputNumber trabalha com número; a API com texto decimal. Convertemos na borda. */
const numeric = computed({
  get: () => (model.value === null || model.value === undefined || model.value === "" ? null : Number(model.value)),
  set: (v: number | null) => {
    model.value = v === null ? null : decimals.value ? v.toFixed(decimals.value) : v;
  },
});

/** DatePicker trabalha com Date; a API com ISO. */
const asDate = computed({
  get: () => (model.value ? new Date(String(model.value).length === 10 ? `${model.value}T00:00:00` : String(model.value)) : null),
  set: (v: Date | null) => {
    if (!v) model.value = null;
    else if (props.field.type === "date") model.value = v.toLocaleDateString("sv-SE");
    else model.value = v.toISOString();
  },
});

/** A linha inteira do switch é clicável (não só a bolinha). */
function toggle() {
  if (!props.disabled) model.value = !model.value;
}

const color = computed({
  get: () => String(model.value ?? "").replace("#", ""),
  set: (v: string) => (model.value = `#${v}`),
});
</script>

<template>
  <div class="field" :class="[sizeClass, { 'field--bare': bare }]">
    <label v-if="!bare && !SELF_LABELED.includes(field.type)" :for="id">{{ field.label }}<span v-if="field.required" class="req">*</span></label>

    <!-- Rótulo em cima, como os outros campos: o switch fica na mesma linha dos inputs vizinhos. -->
    <div v-if="field.type === 'boolean'" class="switch-row" :class="{ on: !!model, disabled }" @click="toggle">
      <span class="switch-row__text">{{ field.hint ?? (model ? "Sim" : "Não") }}</span>
      <ToggleSwitch v-model="model as boolean" :input-id="id" :disabled="disabled" @click.stop />
    </div>
    <Textarea v-else-if="field.type === 'textarea'" :id="id" v-model="model as string" rows="2" auto-resize
              :maxlength="field.maxLength" :placeholder="field.placeholder" :invalid="!!error" :disabled="disabled" />
    <Editor v-else-if="field.type === 'richtext'" :id="id" v-model="model as string" :readonly="disabled"
            editor-style="min-height: 180px" class="rich" :class="{ invalid: !!error }">
      <template #toolbar>
        <span class="ql-formats">
          <select class="ql-header" aria-label="Estilo"><option value="2">Título</option><option value="3">Subtítulo</option><option selected>Texto</option></select>
        </span>
        <span class="ql-formats">
          <button class="ql-bold" aria-label="Negrito" /><button class="ql-italic" aria-label="Itálico" />
          <button class="ql-underline" aria-label="Sublinhado" />
        </span>
        <span class="ql-formats">
          <button class="ql-list" value="ordered" aria-label="Lista numerada" /><button class="ql-list" value="bullet" aria-label="Lista" />
        </span>
        <span class="ql-formats">
          <button class="ql-link" aria-label="Link" /><button class="ql-blockquote" aria-label="Citação" />
          <button class="ql-clean" aria-label="Limpar formatação" />
        </span>
      </template>
    </Editor>
    <div v-else-if="field.type === 'seo-preview'" class="seo" aria-label="Prévia no Google">
      <span class="seo__url">{{ seo.url }}</span>
      <strong class="seo__title" :class="{ long: seo.title.length > 70 }">{{ seo.title }}</strong>
      <p class="seo__text">{{ seo.text.length > 160 ? `${seo.text.slice(0, 157)}…` : seo.text }}</p>
    </div>
    <InputNumber
      v-else-if="['number', 'money', 'percent', 'quantity', 'measure'].includes(field.type)" v-model="numeric" :input-id="id"
      :min-fraction-digits="decimals" :max-fraction-digits="decimals" :mode="field.type === 'money' ? 'currency' : 'decimal'"
      currency="BRL" locale="pt-BR" :suffix="field.type === 'percent' ? ' %' : undefined" :placeholder="field.placeholder"
      :invalid="!!error" :disabled="disabled" fluid
    />
    <!-- No celular, botões demais (mais de 3) não cabem: vira lista de seleção. -->
    <Select
      v-else-if="field.type === 'segmented' && isPhone && (field.options?.length ?? 0) > 3" v-model="model" :input-id="id"
      :options="field.options" option-label="label" option-value="value" :invalid="!!error" :disabled="disabled" fluid
    />
    <SelectButton
      v-else-if="field.type === 'segmented'" v-model="model" :options="field.options" option-label="label"
      option-value="value" :allow-empty="false" :invalid="!!error" :disabled="disabled" class="segmented" :aria-label="field.label"
    />
    <Select
      v-else-if="field.type === 'select'" v-model="model" :input-id="id" :options="field.options" option-label="label"
      option-value="value" :placeholder="field.placeholder" :invalid="!!error" :disabled="disabled" fluid
    />
    <MultiSelect
      v-else-if="field.type === 'multiselect'" v-model="model" :input-id="id" :options="field.options" option-label="label"
      option-value="value" display="chip" filter :placeholder="field.placeholder ?? 'Selecione'" :invalid="!!error"
      :max-selected-labels="4" selected-items-label="{0} selecionados" :disabled="disabled" fluid
    />
    <RelationSelect
      v-else-if="field.type === 'relation' || field.type === 'multirelation'" v-model="model" :input-id="id"
      :relation="field.relation!" :multiple="field.type === 'multirelation'" :creatable="field.creatable"
      :placeholder="field.placeholder" :invalid="!!error" :disabled="disabled"
    />
    <TagsInput v-else-if="field.type === 'tags'" v-model="model as string[]" :input-id="id" :source="field.tagSource"
               :placeholder="field.placeholder" :invalid="!!error" :disabled="disabled" />
    <DatePicker
      v-else-if="field.type === 'date' || field.type === 'datetime'" v-model="asDate" :input-id="id"
      :show-time="field.type === 'datetime'" date-format="dd/mm/yy" show-icon :invalid="!!error" :disabled="disabled" fluid
    />
    <Password v-else-if="field.type === 'password'" v-model="model as string" :input-id="id" :feedback="false" toggle-mask :disabled="disabled" fluid />
    <ColorPicker v-else-if="field.type === 'color'" v-model="color" :input-id="id" :disabled="disabled" />
    <ImageGallery v-else-if="field.type === 'images'" v-model="model as never" :disabled="disabled" />
    <AddressListField v-else-if="field.type === 'addresses'" v-model="model as never" :disabled="disabled" />
    <ZipRangesField v-else-if="field.type === 'zip-ranges'" v-model="model as never" :disabled="disabled" />
    <PromotionRulesField v-else-if="field.type === 'promotion-rules'" v-model="model as never" :disabled="disabled" />
    <MetafieldsField v-else-if="field.type === 'metafields'" v-model="model as never" :owner="field.owner ?? 'product'"
                     :context="context" :disabled="disabled" />
    <BarcodeListField v-else-if="field.type === 'barcodes'" v-model="model as never" />
    <VolumeListField v-else-if="field.type === 'volumes'" v-model="model as never" />
    <GridField v-else-if="field.type === 'grid'" v-model="model as never" :existing="existingOptions" />
    <VariantsField v-else-if="field.type === 'variants'" v-model="model as never" :context="context" :errors="error" />
    <StockItemsField v-else-if="field.type === 'stock-items'" v-model="model as never" :context="context" />
    <InstallmentsField v-else-if="field.type === 'installments'" v-model="model as never" :context="context"
                       @changed="emit('reload')" />
    <!-- Máscara: mostra 01001-000 / (11) 98765-4321 e guarda só os dígitos. A máscara pode mudar com o campo aberto (CPF↔CNPJ, fixo↔celular). -->
    <InputMask
      v-else-if="mask" :id="id" v-model="model as string" :mask="mask" unmask :auto-clear="false" slot-char="_"
      :placeholder="field.placeholder ?? mask.replace('?', '').replace(/9/g, '0')" :invalid="!!error" :disabled="disabled" fluid
      @complete="onComplete"
    />
    <InputText
      v-else :id="id" v-model="model as string" :maxlength="field.maxLength" :placeholder="field.placeholder" :invalid="!!error"
      :type="field.type === 'email' ? 'email' : 'text'" :disabled="disabled" fluid
    />

    <small v-if="error && field.type !== 'variants'" class="error"><i class="pi pi-exclamation-circle" /> {{ error }}</small>
    <small v-else-if="cepNote" class="hint"><i class="pi pi-map-marker" /> {{ cepNote }}</small>
    <small v-else-if="field.hint && field.type !== 'boolean' && !bare" class="hint">{{ field.hint }}</small>
    <small v-if="field.counter && field.maxLength" class="counter" :class="{ near: length > field.maxLength * 0.9 }">
      {{ length }}/{{ field.maxLength }}
    </small>
  </div>
</template>

<style scoped>
.switch-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; height: var(--control-h); padding: 0 10px;
  border: 1px solid var(--border); border-radius: 7px; background: var(--surface-card); cursor: pointer;
  transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease;
}
.switch-row:hover { border-color: var(--brand-border); }
.switch-row.on { border-color: var(--brand-border); background: var(--brand-subtle); }
.switch-row.disabled { cursor: default; border-color: var(--border); background: var(--p-form-field-disabled-background); }
.switch-row__text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--text-body); }
.switch-row.on .switch-row__text { color: var(--text-strong); }
.field small.hint, .field small.error { font-size: 11.5px; }
.counter { align-self: flex-end; margin-top: -2px; font-size: 11px; color: var(--text-subtle); font-variant-numeric: tabular-nums; }
.counter.near { color: var(--warning-text); font-weight: 600; }
/* Editor: mesma borda/raio dos outros campos; barra discreta em cima. */
.rich :deep(.p-editor-toolbar) { border-radius: 7px 7px 0 0; background: var(--surface-sunken); border-color: var(--p-form-field-border-color, var(--border)); }
.rich :deep(.p-editor-content) { border-radius: 0 0 7px 7px; border-color: var(--p-form-field-border-color, var(--border)); }
.rich :deep(.ql-editor) { font: 14px/1.6 var(--font-sans); color: var(--text-body); }
.rich.invalid :deep(.p-editor-content) { border-color: var(--danger); }
/* Editor que é a seção: a barra encosta no topo do cartão e o texto ocupa o resto, sem caixa dentro de caixa. */
.field--bare { gap: 0; }
.field--bare .rich :deep(.p-editor-toolbar) { border: 0; border-bottom: 1px solid var(--border-subtle); border-radius: 10px 10px 0 0; padding: 6px 10px; }
.field--bare .rich :deep(.p-editor-content) { border: 0; border-radius: 0 0 10px 10px; }
.field--bare .rich :deep(.ql-editor) { min-height: 220px; padding: 16px 18px; }
.field--bare .error { padding: 0 18px 12px; }
/* Prévia do Google */
.seo { padding: 12px 14px; border: 1px dashed var(--border); border-radius: 8px; background: var(--surface-card); font-family: Arial, sans-serif; }
.seo__url { display: block; font-size: 12px; color: var(--text-muted); }
.seo__title { display: block; margin: 2px 0; font-size: 18px; font-weight: 400; color: #1a0dab; }
.seo__title.long { text-decoration: underline wavy var(--warning); }
.seo__text { margin: 0; font-size: 13px; line-height: 1.5; color: var(--text-body); }
:root[data-theme="dark"] .seo__title { color: #8ab4f8; }
/* Segmentado ocupa a largura e quebra no celular, sem estourar. */
.segmented { display: flex; flex-wrap: wrap; }
.segmented :deep(.p-togglebutton) { flex: 1 1 auto; font-size: 12.5px; height: var(--control-h); }
</style>
