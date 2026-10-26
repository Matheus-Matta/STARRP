<script setup lang="ts">
/**
 * Estrelas de 1 a 5. Só leitura (lista, painel) ou de escolher (link do cliente): toque
 * na estrela, teclado com setas, e o texto da nota ao lado ("Ótimo") para não depender da cor.
 */
import { computed } from "vue";

const props = defineProps<{ value: number | null; editable?: boolean; size?: "sm" | "md" | "lg"; showLabel?: boolean }>();
const emit = defineEmits<{ "update:value": [number] }>();
const LABELS = ["", "Péssimo", "Ruim", "Regular", "Bom", "Ótimo"];
const rating = computed(() => Math.round(Number(props.value ?? 0)));

function onKey(event: KeyboardEvent) {
  if (!props.editable) return;
  if (event.key === "ArrowRight" || event.key === "ArrowUp") emit("update:value", Math.min(5, (rating.value || 0) + 1));
  if (event.key === "ArrowLeft" || event.key === "ArrowDown") emit("update:value", Math.max(1, (rating.value || 2) - 1));
}
</script>

<template>
  <span class="stars" :class="[`stars--${size ?? 'md'}`, { 'stars--edit': editable }]" :role="editable ? 'slider' : 'img'"
        :aria-label="`Nota ${rating || 0} de 5`" :aria-valuenow="rating" aria-valuemin="1" aria-valuemax="5"
        :tabindex="editable ? 0 : undefined" @keydown="onKey">
    <button v-for="n in 5" :key="n" type="button" class="star" :class="{ on: n <= rating }" :disabled="!editable"
            :aria-label="`${n} estrela${n > 1 ? 's' : ''}`" tabindex="-1" @click="emit('update:value', n)">★</button>
    <span v-if="showLabel && rating" class="stars__label">{{ LABELS[rating] }}</span>
  </span>
</template>

<style scoped>
.stars { display: inline-flex; align-items: center; gap: 1px; outline: none; }
.star { border: 0; background: transparent; padding: 0; line-height: 1; color: var(--border-strong, #c7cbd1); cursor: default; }
.star.on { color: #f5a524; }
.stars--sm .star { font-size: 14px; }
.stars--md .star { font-size: 18px; }
.stars--lg .star { font-size: 36px; padding: 0 2px; }
.stars--edit .star { cursor: pointer; transition: transform 0.1s ease; }
.stars--edit .star:hover { transform: scale(1.15); }
.stars--edit:focus-visible { box-shadow: 0 0 0 2px var(--brand); border-radius: 6px; }
.stars__label { margin-left: 8px; font-size: 13px; font-weight: 700; color: var(--text-strong); }
</style>
