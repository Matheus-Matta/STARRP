<script setup lang="ts">
/**
 * Caixa DENTRO do PDV (só no modo caixa): o turno aberto, quanto deve haver na gaveta
 * agora, as vendas do turno e as ações — sangria, suprimento, bloquear a tela,
 * relatório (Z) e fechar o caixa. Os valores pedem confirmação no diálogo próprio.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import { computed } from "vue";

import { resourceApi } from "@/api/resource";
import type { CashSession } from "@/api/types";
import { dateTime, money } from "@/utils/format";

export type CashAction = "open" | "withdrawal" | "supply" | "close" | "lock" | "report";

/** `seesDrawer`: só quem aprova vê o esperado na gaveta (o operador fecha às cegas). */
const props = defineProps<{ session: CashSession | null; operator: string; seesDrawer?: boolean }>();
const emit = defineEmits<{ action: [action: CashAction]; back: [] }>();

type Row = Record<string, unknown>;
const detail = useQuery({
  queryKey: computed(() => ["pdv-cash", props.session?.id]),
  queryFn: () => resourceApi.get<Row>("/cash/sessions/", String(props.session!.id)),
  enabled: computed(() => Boolean(props.session)),
  refetchInterval: 30_000,
});
const sales = useQuery({
  queryKey: computed(() => ["pdv-cash-sales", props.session?.id]),
  queryFn: () => resourceApi.list("/sales/", { cash_session: String(props.session!.id), status: "completed", page_size: 1 }),
  enabled: computed(() => Boolean(props.session)),
  refetchInterval: 30_000,
});
const expected = computed(() => detail.data.value?.expected_now ?? detail.data.value?.expected_amount ?? null);
</script>

<template>
  <section class="panel">
    <header class="panel__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para a venda" @click="emit('back')" />
      <div>
        <h2>Caixa</h2>
        <p>{{ session ? `Turno aberto por ${operator}` : "Nenhum turno aberto neste caixa." }}</p>
      </div>
    </header>

    <div v-if="session" class="stats">
      <div class="stat"><span>Aberto em</span><strong>{{ dateTime(session.opened_at) }}</strong></div>
      <div class="stat"><span>Troco inicial</span><strong>{{ money(session.opening_amount) }}</strong></div>
      <div v-if="seesDrawer && expected !== null" class="stat stat--brand">
        <span>Em dinheiro na gaveta agora</span><strong>{{ money(expected) }}</strong></div>
      <div v-else class="stat stat--blind">
        <span>Dinheiro na gaveta</span><strong><i class="pi pi-eye-slash" /> Oculto</strong>
        <small>No fechamento você conta e informa; a conferência é do gerente.</small></div>
      <div class="stat"><span>Vendas no turno</span><strong>{{ sales.data.value?.count ?? "—" }}</strong></div>
    </div>

    <div v-if="session" class="actions">
      <button type="button" class="action" @click="emit('action', 'withdrawal')">
        <i class="pi pi-arrow-up-right" /><strong>Sangria</strong><small>Retirar dinheiro da gaveta</small>
      </button>
      <button type="button" class="action" @click="emit('action', 'supply')">
        <i class="pi pi-arrow-down-left" /><strong>Suprimento</strong><small>Colocar troco na gaveta</small>
      </button>
      <button type="button" class="action" @click="emit('action', 'lock')">
        <i class="pi pi-lock" /><strong>Bloquear tela</strong><small>Sair um instante sem fechar (F12)</small>
      </button>
      <button type="button" class="action" @click="emit('action', 'report')">
        <i class="pi pi-print" /><strong>Relatório do turno</strong><small>Parcial (X) na bobina</small>
      </button>
      <button type="button" class="action action--danger" @click="emit('action', 'close')">
        <i class="pi pi-power-off" /><strong>Fechar caixa</strong><small>Contar a gaveta e encerrar o turno</small>
      </button>
    </div>
    <div v-else class="closed">
      <i class="pi pi-lock" />
      <p>Abra o caixa com o troco inicial para começar a vender.</p>
      <Button label="Abrir caixa" icon="pi pi-lock-open" @click="emit('action', 'open')" />
    </div>
  </section>
</template>

<style scoped>
.panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; padding: 12px; overflow-y: auto; }
.panel__head { display: flex; align-items: center; gap: 10px; }
.panel__head h2 { margin: 0; font: 700 17px/1.2 var(--font-sans); color: var(--text-strong); }
.panel__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
.stat { display: flex; flex-direction: column; gap: 4px; padding: 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface-card); }
.stat span { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.stat strong { font: 800 20px/1.2 var(--font-sans); color: var(--text-strong); }
.stat--brand { background: var(--brand-subtle); border-color: var(--brand-border); }
.stat--brand strong { color: var(--text-brand); }
.stat--blind strong { color: var(--text-muted); display: flex; gap: 8px; align-items: center; font-size: 17px; }
.stat--blind small { font-size: 11.5px; color: var(--text-muted); }
.actions { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.action {
  display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 16px; text-align: left; cursor: pointer;
  border: 1px solid var(--border); border-radius: 12px; background: var(--surface-card); font-family: var(--font-sans);
  transition: border-color var(--dur-fast) ease, box-shadow var(--dur-fast) ease;
}
.action:hover { border-color: var(--brand); box-shadow: var(--shadow-sm); }
.action i { font-size: 20px; color: var(--brand); margin-bottom: 4px; }
.action strong { font-size: 14px; color: var(--text-strong); }
.action small { font-size: 12px; color: var(--text-muted); }
.action--danger i { color: var(--danger-text); }
.action--danger:hover { border-color: var(--danger); }
.closed { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 12px; color: var(--text-muted); text-align: center; }
.closed i { font-size: 2rem; }
</style>
