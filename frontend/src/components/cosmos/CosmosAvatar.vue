<script setup lang="ts">
/** O símbolo da Cosmos (ícone `cosmos`) num círculo com o fundo da página e um anel sutil. */
import AppIcon from "@/components/common/AppIcon.vue";

withDefaults(defineProps<{ size?: number; pulse?: boolean }>(), { size: 32, pulse: false });
</script>

<template>
  <span class="avatar" :class="{ pulse }" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true">
    <AppIcon name="cosmos" :size="Math.round(size * 0.52)" />
  </span>
</template>

<style scoped>
.avatar {
  flex: none; display: inline-grid; place-items: center; border-radius: 50%;
  color: var(--text-strong); background: var(--surface-raised); border: 1px solid var(--border-strong);
  box-shadow: inset 0 0 0 3px var(--surface-sunken);
}
.pulse { animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse { 50% { box-shadow: inset 0 0 0 3px var(--surface-sunken), 0 0 0 5px var(--surface-active); } }
</style>
