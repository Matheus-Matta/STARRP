<script setup lang="ts">
/** Marca do serviço integrado (Asaas, Shopify...). Sem logo, ou se a imagem não carregar, o ícone do tipo. */
import { ref, watch } from "vue";

const props = withDefaults(defineProps<{ logo?: string | null; icon?: string; label?: string; size?: number }>(),
                           { logo: null, icon: "pi pi-link", label: "", size: 32 });
const broken = ref(false);
watch(() => props.logo, () => (broken.value = false));
</script>

<template>
  <span class="ilogo" :style="{ width: `${size}px`, height: `${size}px` }">
    <img v-if="logo && !broken" :src="logo" :alt="label" @error="broken = true">
    <i v-else :class="icon" :style="{ fontSize: `${Math.round(size * 0.5)}px` }" />
  </span>
</template>

<style scoped>
.ilogo { display: inline-grid; place-items: center; flex-shrink: 0; border-radius: 8px; overflow: hidden;
         background: var(--surface-card); border: 1px solid var(--border-subtle); }
.ilogo img { width: 100%; height: 100%; object-fit: contain; padding: 2px; }
.ilogo i { color: var(--brand); }
</style>
