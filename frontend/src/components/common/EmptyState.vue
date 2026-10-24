<script setup lang="ts">
/** Estado vazio com ícone, mensagem e ação opcional. */
defineProps<{ icon?: string; title: string; description?: string }>();
</script>

<template>
  <div class="empty">
    <span class="empty__icon"><i :class="icon ?? 'pi pi-inbox'" /></span>
    <strong>{{ title }}</strong>
    <p v-if="description">{{ description }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; padding: 2.5rem 1rem; }
.empty__icon {
  width: 56px; height: 56px; border-radius: 16px; display: grid; place-items: center; font-size: 22px; margin-bottom: 6px;
  color: var(--text-subtle); background: var(--surface-sunken); border: 1px dashed var(--border-strong);
}
strong { color: var(--text-strong); font-size: 15px; }
p { margin: 0; color: var(--text-muted); max-width: 360px; font-size: 13px; }
</style>
