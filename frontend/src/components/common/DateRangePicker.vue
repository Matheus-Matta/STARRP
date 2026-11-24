<script setup lang="ts">
/**
 * Seletor de PERÍODO do sistema (filtros das listas, relatórios, extratos):
 *
 * - dois meses lado a lado (um no celular): do dia 20 deste mês ao dia 10 do próximo sem trocar de página;
 * - atalhos de um clique: hoje, 7 dias, este mês, mês passado, próximo mês, próximos 30 dias, este ano;
 * - aceita digitar ("01/11/2026 - 10/12/2026");
 * - só avisa quem usa quando o período está completo (início E fim) ou foi limpo: o primeiro clique
 *   não dispara uma busca pela metade.
 */
import DatePicker from "primevue/datepicker";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

type Range = (Date | null)[] | null;

const props = withDefaults(defineProps<{
  modelValue?: Range; placeholder?: string; size?: "small" | "large"; maxDate?: Date; minDate?: Date;
  presets?: boolean; showClear?: boolean;
}>(), { modelValue: null, placeholder: "Período", size: undefined, maxDate: undefined, minDate: undefined,
        presets: true, showClear: true });
const emit = defineEmits<{ "update:modelValue": [Range] }>();

const picker = ref<{ overlayVisible?: boolean } | null>(null);
const draft = ref<Range>(props.modelValue);
watch(() => props.modelValue, (value) => (draft.value = value));

/* Dois meses na tela larga, um no celular. */
const wide = ref(true);
let media: MediaQueryList | null = null;
const onMedia = () => (wide.value = Boolean(media?.matches));
onMounted(() => {
  media = window.matchMedia("(min-width: 720px)");
  onMedia();
  media.addEventListener("change", onMedia);
});
onBeforeUnmount(() => media?.removeEventListener("change", onMedia));

function onPick(value: Range | Date) {
  const range = Array.isArray(value) ? value : value ? [value, null] : null;
  draft.value = range;
  if (!range || !range[0]) emit("update:modelValue", null);
  else if (range[1]) emit("update:modelValue", range);
}

const day = (offset = 0) => {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + offset);
  return d;
};
const monthStart = (shift: number) => {
  const d = day();
  return new Date(d.getFullYear(), d.getMonth() + shift, 1);
};
const monthEnd = (shift: number) => {
  const d = day();
  return new Date(d.getFullYear(), d.getMonth() + shift + 1, 0);
};
const PRESETS: { label: string; range: () => Date[] }[] = [
  { label: "Hoje", range: () => [day(), day()] },
  { label: "Últimos 7 dias", range: () => [day(-6), day()] },
  { label: "Este mês", range: () => [monthStart(0), monthEnd(0)] },
  { label: "Mês passado", range: () => [monthStart(-1), monthEnd(-1)] },
  { label: "Próximo mês", range: () => [monthStart(1), monthEnd(1)] },
  { label: "Próximos 30 dias", range: () => [day(), day(29)] },
  { label: "Este ano", range: () => [new Date(day().getFullYear(), 0, 1), new Date(day().getFullYear(), 11, 31)] },
];
/** Atalho que passa do limite (ex.: "Próximo mês" num relatório só até hoje) fica de fora. */
const usable = (preset: { range: () => Date[] }) => {
  const [from, to] = preset.range();
  return !(props.maxDate && from! > props.maxDate) && !(props.minDate && to! < props.minDate);
};
function clamp(range: Date[]) {
  const [from, to] = range;
  return [props.minDate && from! < props.minDate ? props.minDate : from!, props.maxDate && to! > props.maxDate ? props.maxDate : to!];
}
function apply(preset: { range: () => Date[] }) {
  const range = clamp(preset.range());
  draft.value = range;
  emit("update:modelValue", range);
  if (picker.value) picker.value.overlayVisible = false;
}
function clear() {
  draft.value = null;
  emit("update:modelValue", null);
  if (picker.value) picker.value.overlayVisible = false;
}
</script>

<template>
  <DatePicker ref="picker" :model-value="draft" selection-mode="range" date-format="dd/mm/yy" show-icon icon-display="input"
              manual-input hide-on-range-selection :number-of-months="wide ? 2 : 1" :placeholder="placeholder"
              :size="size" :max-date="maxDate" :min-date="minDate" class="date-range"
              @update:model-value="onPick($event as never)">
    <template v-if="presets || showClear" #footer>
      <div class="date-range__presets">
        <template v-if="presets">
          <button v-for="p in PRESETS.filter(usable)" :key="p.label" type="button" class="date-range__preset" @click="apply(p)">
            {{ p.label }}
          </button>
        </template>
        <button v-if="showClear && draft?.[0]" type="button" class="date-range__preset date-range__clear" @click="clear">
          <i class="pi pi-times" /> Limpar
        </button>
      </div>
    </template>
  </DatePicker>
</template>

<style scoped>
.date-range { min-width: 0; }
.date-range__presets { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 4px 2px; border-top: 1px solid var(--border-subtle);
                       margin-top: 6px; max-width: 640px; }
.date-range__preset { padding: 5px 10px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface-card);
                      font: 600 12px/1.2 var(--font-sans); color: var(--text-body); cursor: pointer;
                      transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease; }
.date-range__preset:hover, .date-range__preset:focus-visible { border-color: var(--brand); background: var(--surface-sunken);
                                                               color: var(--text-strong); }
.date-range__clear { margin-left: auto; color: var(--danger-text); }
.date-range__clear i { font-size: 10px; margin-right: 2px; }
</style>
