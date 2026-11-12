<script setup lang="ts">
/** Ícone próprio em SVG (`icons.ts`), na cor do texto: `<AppIcon name="cosmos" :size="20" />`. */
import { computed } from "vue";

import { type IconName, icons } from "./icons";

const props = withDefaults(defineProps<{ name: IconName; size?: number | string }>(), { size: "1em" });
const icon = computed(() => icons[props.name]);
const height = computed(() => (typeof props.size === "number" ? `${props.size}px` : props.size));
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html — desenho fixo do código (icons.ts), nunca dado de usuário -->
  <svg :viewBox="`0 0 ${icon.width} ${icon.height}`" :style="{ height, width: 'auto' }" aria-hidden="true" v-html="icon.body" />
</template>
