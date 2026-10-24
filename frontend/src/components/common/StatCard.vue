<script setup lang="ts">
/** Cartão de indicador: rótulo, valor grande, ícone colorido e legenda. */
type Tone = "brand" | "success" | "warning" | "danger" | "info";
withDefaults(defineProps<{ label: string; value: string; icon: string; caption?: string; tone?: Tone }>(), {
  tone: "brand", caption: "",
});
</script>

<template>
  <div class="stat" :class="`stat--${tone}`">
    <div class="stat__head">
      <span class="stat__label">{{ label }}</span>
      <span class="stat__icon"><i :class="icon" /></span>
    </div>
    <strong class="stat__value num">{{ value }}</strong>
    <span v-if="caption" class="stat__caption">{{ caption }}</span>
  </div>
</template>

<style scoped>
.stat {
  --tone: var(--brand); --tone-bg: var(--brand-subtle);
  position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 8px; padding: 18px;
  background: var(--surface-card); border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow-xs);
  transition: transform var(--dur-base) var(--ease-out), box-shadow var(--dur-base) ease, border-color var(--dur-base) ease;
  animation: srp-fade-up var(--dur-slow) var(--ease-out) both;
}
.stat::after { content: ""; position: absolute; inset: auto 0 0 0; height: 3px; background: var(--tone); opacity: 0; transition: opacity var(--dur-base) ease; }
.stat:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: color-mix(in srgb, var(--tone) 35%, var(--border)); }
.stat:hover::after { opacity: 1; }
.stat--success { --tone: var(--success); --tone-bg: var(--success-subtle); }
.stat--warning { --tone: var(--warning); --tone-bg: var(--warning-subtle); }
.stat--danger { --tone: var(--danger); --tone-bg: var(--danger-subtle); }
.stat--info { --tone: var(--info); --tone-bg: var(--info-subtle); }
.stat__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stat__label { font: 600 12.5px/1.2 var(--font-sans); color: var(--text-muted); }
.stat__icon { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: var(--tone); background: var(--tone-bg); }
.stat__value { font: 800 26px/1.1 var(--font-sans); letter-spacing: -0.02em; color: var(--text-strong); }
.stat__caption { font-size: 12px; color: var(--text-subtle); }
</style>
