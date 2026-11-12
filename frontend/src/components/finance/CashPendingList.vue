<script setup lang="ts">
/**
 * Sangrias e suprimentos do turno aguardando aprovação, com Aprovar / Recusar.
 * Serve ao PDV (o operador pede a senha do gerente ou a do caixa da filial no ato) e à
 * retaguarda (o gerente aprova direto). Sem pendências, não mostra nada.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import Button from "primevue/button";
import { computed, ref } from "vue";

import { cashApi } from "@/api/cash";
import type { CashMovement } from "@/api/types";
import { ApprovalCancelled, withApproval } from "@/composables/useApproval";
import { useNotify } from "@/composables/useNotify";
import { dateTime, money } from "@/utils/format";

/** `version`: quem lança movimentos fora daqui (o PDV) sobe o número para recarregar a lista. */
const props = defineProps<{ sessionId: string; version?: number }>();
const emit = defineEmits<{ changed: [] }>();
const notify = useNotify();
const client = useQueryClient();
const KIND: Record<string, string> = { withdrawal: "Sangria", supply: "Suprimento" };
const DONE: Record<string, [string, string]> = { withdrawal: ["Sangria aprovada", "Sangria recusada"],
                                                 supply: ["Suprimento aprovado", "Suprimento recusado"] };

const query = useQuery({
  queryKey: computed(() => ["cash-pending", props.sessionId, props.version ?? 0]),
  queryFn: () => cashApi.movements(props.sessionId),
  refetchInterval: 20_000,
});
const pending = computed(() => (query.data.value ?? []).filter((m) => m.status === "pending"));
const busy = ref<string | null>(null);

async function decide(movement: CashMovement, approve: boolean) {
  const id = String(movement.id);
  busy.value = id;
  try {
    if (approve) {
      await withApproval((approval) => cashApi.approveMovement(id, "", approval));
      notify.success(DONE[movement.kind]?.[0] ?? "Movimento aprovado", money(movement.amount));
    } else {
      await cashApi.rejectMovement(id);
      notify.success(DONE[movement.kind]?.[1] ?? "Movimento recusado", "Não mexe na gaveta.");
    }
    await client.invalidateQueries({ queryKey: ["cash-pending", props.sessionId] });
    emit("changed");
  } catch (error) {
    if (!(error instanceof ApprovalCancelled)) notify.error(error, "Não foi possível concluir");
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <div v-if="pending.length" class="pend">
    <p class="pend__head"><i class="pi pi-clock" /> Aguardando aprovação ({{ pending.length }})
      <small>O caixa só fecha depois que cada um for aprovado ou recusado.</small></p>
    <ul>
      <li v-for="m in pending" :key="String(m.id)">
        <div class="pend__what">
          <strong>{{ KIND[m.kind] ?? m.kind }} · {{ money(m.amount) }}</strong>
          <small>{{ m.reason || "Sem motivo" }} · {{ m.operator_name }} · {{ dateTime(m.created_at) }}</small>
        </div>
        <div class="pend__act">
          <Button label="Recusar" icon="pi pi-times" size="small" severity="secondary" outlined
                  :disabled="busy !== null" @click="decide(m, false)" />
          <Button label="Aprovar" icon="pi pi-check" size="small" :loading="busy === String(m.id)"
                  :disabled="busy !== null && busy !== String(m.id)" @click="decide(m, true)" />
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.pend { border: 1px solid color-mix(in srgb, var(--warning) 45%, var(--border)); background: var(--warning-subtle); border-radius: 12px; padding: 12px 14px; }
.pend__head { margin: 0 0 8px; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; font: 700 13.5px var(--font-sans); color: var(--text-strong); }
.pend__head i { color: var(--warning-text); }
.pend__head small { font-weight: 500; font-size: 12px; color: var(--text-muted); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
li { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px;
     border-radius: 10px; background: var(--surface-card); border: 1px solid var(--border); }
.pend__what { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pend__what strong { font-size: 14px; color: var(--text-strong); }
.pend__what small { font-size: 12px; color: var(--text-muted); overflow-wrap: anywhere; }
.pend__act { display: flex; gap: 6px; }
</style>
