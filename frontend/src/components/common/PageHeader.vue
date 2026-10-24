<script setup lang="ts">
/** Cabeçalho de página: ícone, título, descrição e ações à direita. */
defineProps<{ title: string; subtitle?: string; icon?: string }>();
</script>

<template>
  <header class="page-header">
    <div class="page-header__main">
      <span v-if="icon" class="page-header__icon"><i :class="icon" /></span>
      <div>
        <h1>{{ title }}</h1>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
    </div>
    <div v-if="$slots.default" class="page-header__actions"><slot /></div>
  </header>
</template>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; animation: srp-fade-up var(--dur-slow) var(--ease-out); }
.page-header__main { display: flex; align-items: center; gap: 14px; min-width: 0; }
.page-header__icon {
  width: 36px; height: 36px; flex-shrink: 0; border-radius: 9px; display: grid; place-items: center; font-size: 15px;
  color: var(--brand); background: var(--brand-subtle); border: 1px solid var(--brand-border);
}
h1 { font: 700 19px/1.2 var(--font-sans); letter-spacing: -0.01em; }
p { margin-top: 2px; color: var(--text-muted); font-size: 12.5px; }
.page-header__actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
</style>
