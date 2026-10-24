<script setup lang="ts">
/** Cartão de seção (formulários e painéis): título com ícone, descrição e conteúdo. */
defineProps<{ title: string; description?: string; icon?: string }>();
</script>

<template>
  <section class="section">
    <header class="section__head">
      <span v-if="icon" class="section__icon"><i :class="icon" /></span>
      <div>
        <h2>{{ title }}</h2>
        <p v-if="description">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="section__actions"><slot name="actions" /></div>
    </header>
    <div class="section__body"><slot /></div>
  </section>
</template>

<style scoped>
.section { background: var(--surface-card); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-xs); animation: srp-fade-up var(--dur-slow) var(--ease-out) both; }
.section__head { display: flex; align-items: center; gap: 12px; padding: 16px 20px; border-bottom: 1px solid var(--border-subtle); }
.section__icon { width: 32px; height: 32px; border-radius: 9px; display: grid; place-items: center; color: var(--brand); background: var(--brand-subtle); }
h2 { font: 700 15px/1.2 var(--font-sans); }
p { margin-top: 2px; font-size: 12.5px; color: var(--text-muted); }
.section__actions { margin-left: auto; display: flex; gap: 0.5rem; }
.section__body { padding: 20px; }
</style>
