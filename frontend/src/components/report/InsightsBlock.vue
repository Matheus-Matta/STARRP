<script setup lang="ts">
/** Conclusões escritas a partir dos números do cruzamento. Ícone + texto (não só a cor). */
defineProps<{ items: { text: string; tone: "good" | "bad" | "info" }[] }>();
const ICON = { good: "pi pi-check-circle", bad: "pi pi-exclamation-triangle", info: "pi pi-info-circle" };
const LABEL = { good: "Positivo", bad: "Atenção", info: "Observação" };
</script>

<template>
  <p v-if="!items.length" class="empty">Sem conclusões no período (faltam dados nos dois lados do cruzamento).</p>
  <ul v-else class="ins">
    <li v-for="(item, i) in items" :key="i" :class="`ins--${item.tone}`">
      <i :class="ICON[item.tone]" :aria-label="LABEL[item.tone]" />
      <span>{{ item.text }}</span>
    </li>
  </ul>
</template>

<style scoped>
.ins { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 8px; }
.ins li { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border);
          background: var(--surface-card); font-size: 13.5px; line-height: 1.45; color: var(--text-body); }
.ins i { margin-top: 2px; font-size: 15px; }
.ins--good { border-color: color-mix(in srgb, var(--success) 40%, var(--border)); }
.ins--good i { color: var(--success-text); }
.ins--bad { border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); }
.ins--bad i { color: var(--danger-text); }
.ins--info i { color: var(--text-brand); }
.empty { margin: 0; color: var(--text-muted); font-size: 13px; }
</style>
