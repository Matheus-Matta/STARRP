<script setup lang="ts">
/**
 * Cancelamento do pedido e/ou da nota, aberto pelo pedido ou pela nota emitida.
 *
 * Pedido: cancela a nota autorizada na SEFAZ (se houver), a venda (estoque volta, comissão e cupom
 * saem, títulos cancelados) e reembolsa cada pagamento. Precisa de `sales.cancel` (ou o gerente
 * autoriza na hora).
 * Nota: só a nota (a venda continua concluída, para emitir de novo) ou, marcado, nota + pedido +
 * reembolso. A justificativa da SEFAZ tem de 15 a 255 caracteres e há prazo (NF-e 24 h, NFC-e 30 min).
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Textarea from "primevue/textarea";
import { computed, ref } from "vue";

import { http } from "@/api/http";
import { ApprovalCancelled, withApproval } from "@/composables/useApproval";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { dateTime, money } from "@/utils/format";

type Pay = { id: string; method_name: string; method_kind: string; amount: string; status: string; installments: number };
type Inv = { id: string; label?: string; document_model: string; status: string; authorized_at: string | null; environment: string };
type Row = Record<string, unknown>;

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const v = props.ctx.values;
/** Aberto pela nota (tem modelo) ou pelo pedido. */
const fromInvoice = "document_model" in v;
const saleId = fromInvoice ? ((v.sale as string | null) ?? null) : props.ctx.id;
const withSale = ref(Boolean(saleId));

const saleQuery = useQuery({
  queryKey: ["cancel-order-sale", saleId],
  queryFn: async () => (await http.get<Row>(`/sales/${saleId}/`)).data,
  enabled: fromInvoice && Boolean(saleId),
});
const sale = computed<Row | null>(() => (fromInvoice ? saleQuery.data.value ?? null : v));
const invoice = computed<Inv | null>(() => {
  if (fromInvoice) return v as unknown as Inv;
  return ((v.invoices ?? []) as Inv[]).find((i) => i.status === "authorized") ?? null;
});
const authorized = computed(() => invoice.value?.status === "authorized");
const touchesSale = computed(() => !fromInvoice || withSale.value);
const payments = computed(() => ((sale.value?.payments ?? []) as Pay[]).filter((p) => p.status === "approved"));
const completed = computed(() => sale.value?.status === "completed");

const STATUS: Record<string, string> = { draft: "Rascunho", processing: "Em processamento", authorized: "Autorizada",
                                          rejected: "Rejeitada", cancelled: "Cancelada", error: "Erro de comunicação" };
const DEADLINE_MIN: Record<string, number> = { "55": 24 * 60, "65": 30 };
const deadline = computed(() => {
  const inv = invoice.value;
  if (!inv?.authorized_at || !authorized.value) return null;
  return new Date(new Date(inv.authorized_at).getTime() + (DEADLINE_MIN[inv.document_model] ?? 0) * 60_000);
});
const expired = computed(() => Boolean(deadline.value && deadline.value.getTime() < Date.now()));
const model = computed(() => (invoice.value?.document_model === "55" ? "NF-e" : "NFC-e"));

/** O que acontece com cada pagamento (o dinheiro sai do caixa de quem cancela; o resto se devolve fora). */
function refund(p: Pay) {
  if (!completed.value) return "pagamento cancelado";
  if (p.method_kind === "cash") return "sai do seu caixa aberto como devolução";
  if (p.method_kind === "installment_plan" || p.method_kind === "bank_slip") return "parcelas canceladas no financeiro";
  if (p.method_kind === "store_credit") return "volta para o vale-troca do cliente";
  return "estornado: devolva na maquininha/banco";
}

const reason = ref("");
const saving = ref(false);
const minReason = computed(() => (authorized.value ? 15 : 1));
const ready = computed(() => reason.value.trim().length >= minReason.value && reason.value.trim().length <= 255
  && !(authorized.value && expired.value) && (!fromInvoice || authorized.value));

async function save() {
  saving.value = true;
  const text = reason.value.trim();
  try {
    if (fromInvoice) {
      await withApproval((approval) => http.post(`/fiscal/invoices/${props.ctx.id}/cancel/`,
        { reason: text, with_sale: withSale.value && Boolean(saleId), approval }));
    } else {
      await withApproval((approval) => http.post(`/sales/${props.ctx.id}/cancel/`, { reason: text, approval }));
    }
    notify.success(touchesSale.value ? "Pedido cancelado" : "Nota cancelada",
                   touchesSale.value && authorized.value ? `${model.value} cancelada e pagamentos reembolsados.` : undefined);
    emit("done");
  } catch (error) {
    if (!(error instanceof ApprovalCancelled)) notify.error(error, "Não cancelado");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="cod">
    <p v-if="fromInvoice && !authorized" class="warn"><i class="pi pi-info-circle" /> Só nota autorizada se cancela na
      SEFAZ. Esta está "{{ STATUS[String(v.status)] ?? v.status }}".</p>

    <template v-if="authorized">
      <p v-if="expired" class="bad"><i class="pi pi-clock" /> Passou o prazo de cancelamento da {{ model }} (venceu em
        {{ dateTime(deadline) }}). Faça a <b>devolução</b> do pedido, que emite a nota de entrada.</p>
      <p v-else-if="deadline" class="muted"><i class="pi pi-clock" /> Prazo da SEFAZ para cancelar a {{ model }}: até
        <b>{{ dateTime(deadline) }}</b>.</p>
      <p v-if="invoice?.environment === '2'" class="muted"><i class="pi pi-flag" /> Nota de homologação: o cancelamento é
        de teste.</p>
    </template>

    <label v-if="fromInvoice && saleId" class="check">
      <Checkbox v-model="withSale" binary input-id="cod-sale" />
      <span><b>Cancelar também o pedido {{ sale?.number ?? (v.sale_number as string) ?? "" }} e reembolsar</b><br />
        <small>Sem marcar, cancela só a nota: o pedido continua concluído (ex.: nota com dado errado, para emitir de novo).</small></span>
    </label>

    <section class="what">
      <h3>O que vai acontecer</h3>
      <ul>
        <li v-if="authorized"><i class="pi pi-file-excel" /> {{ invoice?.label ?? model }}: cancelada na SEFAZ</li>
        <template v-if="touchesSale && sale">
          <li><i class="pi pi-times-circle" /> Pedido {{ sale.number }} cancelado
            <template v-if="completed">: o estoque dos itens volta, comissão e cupom saem</template></li>
          <li v-for="p in payments" :key="p.id"><i class="pi pi-replay" /> {{ p.method_name }} {{ money(p.amount) }} —
            {{ refund(p) }}</li>
          <li v-if="!payments.length" class="muted"><i class="pi pi-wallet" /> Nenhum pagamento a reembolsar.</li>
        </template>
        <li v-else-if="touchesSale && saleQuery.isPending.value" class="muted"><i class="pi pi-spin pi-spinner" /> Carregando o pedido…</li>
      </ul>
    </section>

    <div class="field">
      <label for="cod-reason">Justificativa <b class="req">*</b>
        <small v-if="authorized">(de 15 a 255 caracteres, vai para a SEFAZ — {{ reason.trim().length }}/255)</small></label>
      <Textarea id="cod-reason" v-model="reason" rows="3" auto-resize fluid maxlength="255"
                placeholder="Ex.: cliente desistiu da compra e foi reembolsado" />
    </div>
    <div class="cod__foot">
      <Button label="Voltar" severity="secondary" text @click="emit('close')" />
      <Button :label="touchesSale ? 'Cancelar pedido' : 'Cancelar nota'" icon="pi pi-times" severity="danger" :loading="saving"
              :disabled="!ready || saving" @click="save" />
    </div>
  </div>
</template>

<style scoped>
.cod { display: flex; flex-direction: column; gap: 12px; min-width: min(560px, 100%); }
.cod p { margin: 0; font-size: 13px; display: flex; gap: 6px; align-items: baseline; }
.warn { color: var(--warning-text); }
.bad { color: var(--danger-text); }
.check { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
         cursor: pointer; font-size: 13px; }
.check small { color: var(--text-muted); font-size: 12px; }
.what h3 { margin: 0 0 6px; font: 700 13px/1 var(--font-sans); color: var(--text-strong); }
.what ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.what li { display: flex; gap: 8px; align-items: baseline; }
.what i { color: var(--text-muted); }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 12.5px; font-weight: 600; color: var(--text-muted); }
.field small { font-weight: 400; }
.req { color: var(--danger-text); }
.cod__foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
