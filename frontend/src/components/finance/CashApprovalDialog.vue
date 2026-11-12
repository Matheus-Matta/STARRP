<script setup lang="ts">
/**
 * Aprovações do turno na retaguarda: abertura que não bateu, fechamento com diferença
 * (justificativa obrigatória) e sangrias/suprimentos pendentes. Quem tem `cash.approve`
 * aprova direto; os demais informam o gerente ou a senha de aprovação do caixa da filial.
 */
import Button from "primevue/button";
import Textarea from "primevue/textarea";
import { computed, ref } from "vue";

import { cashApi } from "@/api/cash";
import CashPendingList from "@/components/finance/CashPendingList.vue";
import { ApprovalCancelled, withApproval } from "@/composables/useApproval";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { money } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const reason = ref("");
const saving = ref(false);
const v = computed(() => props.ctx.values);
const status = computed(() => String(v.value.status));
const shown = (value: unknown) => (value === null || value === undefined ? "—" : money(value));

async function approve() {
  saving.value = true;
  try {
    const id = props.ctx.id;
    if (status.value === "pending_opening") {
      await withApproval((approval) => cashApi.approveOpening(id, approval, reason.value.trim()));
      notify.success("Abertura aprovada", "O caixa já pode vender.");
    } else {
      await withApproval((approval) => cashApi.approveClosing(id, reason.value.trim(), approval));
      notify.success("Fechamento aprovado", "O contado entrou no cofre.");
    }
    emit("done");
  } catch (error) {
    if (!(error instanceof ApprovalCancelled)) notify.error(error, "Não foi possível aprovar");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="ap">
    <section v-if="status === 'pending_opening' || status === 'pending_approval'" class="ap__box">
      <h3>{{ status === "pending_opening" ? "Abertura com diferença" : "Fechamento com diferença" }}</h3>
      <dl v-if="status === 'pending_opening'">
        <div><dt>Deixado no último fechamento</dt><dd>{{ shown(v.opening_expected) }}</dd></div>
        <div><dt>Contado na abertura</dt><dd>{{ shown(v.opening_amount) }}</dd></div>
        <div><dt>Diferença</dt><dd class="diff">{{ shown(v.opening_difference) }}</dd></div>
      </dl>
      <dl v-else>
        <div><dt>Esperado na gaveta</dt><dd>{{ shown(v.expected_amount) }}</dd></div>
        <div><dt>Contado</dt><dd>{{ shown(v.counted_amount) }}</dd></div>
        <div><dt>Diferença</dt><dd class="diff">{{ shown(v.difference) }}</dd></div>
      </dl>
      <Textarea v-model="reason" rows="2" auto-resize maxlength="500" fluid
                :placeholder="status === 'pending_approval' ? 'Justificativa da diferença (obrigatória)' : 'Observação (opcional)'" />
      <div class="ap__foot">
        <Button :label="status === 'pending_opening' ? 'Aprovar abertura' : 'Aprovar fechamento'" icon="pi pi-check"
                :loading="saving" :disabled="status === 'pending_approval' && reason.trim().length < 3" @click="approve" />
      </div>
    </section>
    <CashPendingList :session-id="ctx.id" @changed="ctx.reload()" />
    <p v-if="status !== 'pending_opening' && status !== 'pending_approval' && !Number(v.pending_movements)" class="muted">
      Nada aguardando aprovação neste turno.
    </p>
  </div>
</template>

<style scoped>
.ap { display: flex; flex-direction: column; gap: 14px; min-width: min(520px, 100%); }
.ap__box { display: flex; flex-direction: column; gap: 10px; padding: 14px; border: 1px solid var(--border); border-radius: 12px; }
.ap__box h3 { margin: 0; font: 700 14px var(--font-sans); color: var(--text-strong); }
dl { margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
dl div { display: flex; flex-direction: column; gap: 2px; }
dt { font-size: 12px; color: var(--text-muted); }
dd { margin: 0; font: 700 15px var(--font-sans); color: var(--text-strong); font-variant-numeric: tabular-nums; }
dd.diff { color: var(--danger-text); }
.ap__foot { display: flex; justify-content: flex-end; }
.muted { margin: 0; font-size: 13px; }
</style>
