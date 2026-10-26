<script setup lang="ts">
/**
 * Trilho de atalhos do PDV (esquerda), cada um com a sua tecla:
 * F1 venda · F2 pedidos · F3 cliente · F4 caixa (só no modo caixa) · F5 preço · Shift+F5 frete · F8 sair.
 * Venda, pedidos, cliente e caixa abrem DENTRO do PDV (sem janela por cima).
 */
import { computed } from "vue";

export type RailAction = "sale" | "orders" | "customer" | "cash" | "price" | "freight" | "backoffice";

const props = defineProps<{ active?: RailAction; seller?: boolean; exitLabel?: string }>();
const emit = defineEmits<{ select: [action: RailAction] }>();

const items = computed(() => [
  { action: "sale" as const, label: "Venda", icon: "pi pi-th-large", key: "F1" },
  { action: "orders" as const, label: "Pedidos", icon: "pi pi-inbox", key: "F2" },
  { action: "customer" as const, label: "Cliente", icon: "pi pi-user", key: "F3" },
  ...(props.seller ? [] : [{ action: "cash" as const, label: "Caixa", icon: "pi pi-wallet", key: "F4" }]),
  { action: "price" as const, label: "Preço", icon: "pi pi-tag", key: "F5" },
  { action: "freight" as const, label: "Frete", icon: "pi pi-truck", key: "⇧F5" },
  { action: "backoffice" as const, label: props.exitLabel ?? "Sair", icon: "pi pi-sign-out", key: "F8" },
]);
</script>

<template>
  <nav class="rail" aria-label="Atalhos do PDV">
    <button v-for="item in items" :key="item.action" type="button" class="rail__item"
            :class="{ active: active === item.action, last: item.action === 'backoffice' }" :title="`${item.label} (${item.key})`"
            @click="emit('select', item.action)">
      <kbd>{{ item.key }}</kbd>
      <i :class="item.icon" />
      <span>{{ item.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.rail {
  width: 72px; flex-shrink: 0; display: flex; flex-direction: column; gap: 4px; padding: 8px 6px;
  background: var(--nav-bg); border-right: 1px solid var(--nav-border);
}
.rail__item {
  position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 10px 2px 8px;
  border: 0; border-radius: 8px; background: transparent; color: var(--nav-muted); cursor: pointer; font: 600 11px/1 var(--font-sans);
  transition: background-color var(--dur-fast) ease, color var(--dur-fast) ease;
}
.rail__item i { font-size: 18px; }
.rail__item:hover { background: var(--nav-hover); color: var(--nav-strong); }
.rail__item.active { background: var(--nav-active); color: var(--nav-active-text); }
.rail__item.active::before { content: ""; position: absolute; left: -6px; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0; background: var(--brand-400); }
.rail__item.last { margin-top: auto; }
kbd { position: absolute; top: 3px; right: 4px; font: 600 8.5px/1 var(--font-mono); color: var(--nav-muted); opacity: 0.8; }
@media (max-width: 860px) {
  .rail { width: 100%; flex-direction: row; justify-content: space-around; padding: 4px; border-right: 0; border-bottom: 1px solid var(--nav-border); }
  .rail__item { flex: 1; padding: 6px 2px; }
  .rail__item span { font-size: 10px; }
  .rail__item.last { margin-top: 0; }
  .rail__item.active::before { display: none; }
  kbd { display: none; }
}
</style>
