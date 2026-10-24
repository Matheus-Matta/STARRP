<script setup lang="ts">
/**
 * Parcelas do título (contas a pagar/receber) com a BAIXA na própria linha.
 *
 * "Baixar" abre: conta (de onde sai/entra o dinheiro), valor (já vem o saldo),
 * juros, multa, desconto e data. Pagar menos que o saldo deixa a parcela
 * "paga parcialmente". O título novo ainda não tem parcelas: elas nascem ao
 * salvar, a partir do total e do nº de parcelas.
 */
import Button from "primevue/button";
import DatePicker from "primevue/datepicker";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import { computed, ref } from "vue";

import { financeApi } from "@/api/operations";
import { useNotify } from "@/composables/useNotify";
import { date, money } from "@/utils/format";

import RelationSelect from "./RelationSelect.vue";

type Installment = {
  id: string; number: number; due_date: string; amount: string; paid_amount: string; paid_at: string | null;
  status: string; balance?: string; interest: string; fine: string; discount: string;
};

const props = defineProps<{ context?: Record<string, unknown> }>();
const emit = defineEmits<{ changed: [] }>();
const model = defineModel<Installment[] | null>({ default: () => [] });
const notify = useNotify();

const STATUS: Record<string, [string, string]> = {
  open: ["Em aberto", "pill--info"], partial: ["Parcial", "pill--warning"], paid: ["Paga", "pill--success"],
  cancelled: ["Cancelada", "pill--neutral"],
};
const receivable = computed(() => props.context?.kind === "receivable");
const rows = computed(() => model.value ?? []);
const today = new Date().toLocaleDateString("sv-SE");
const overdue = (row: Installment) => ["open", "partial"].includes(row.status) && row.due_date < today;
const balanceOf = (row: Installment) => Number(row.balance ?? Number(row.amount) - Number(row.paid_amount));

const settling = ref<Installment | null>(null);
const form = ref({ financial_account: null as string | null, amount: 0, interest: 0, fine: 0, discount: 0, date: new Date() });
const saving = ref(false);
const total = computed(() => form.value.amount);

function open(row: Installment) {
  settling.value = row;
  form.value = { financial_account: form.value.financial_account, amount: balanceOf(row), interest: 0, fine: 0, discount: 0,
                 date: new Date() };
}

async function settle() {
  if (!settling.value || !form.value.financial_account) return notify.warn("Escolha a conta.");
  saving.value = true;
  try {
    await financeApi.settle(settling.value.id, {
      financial_account: form.value.financial_account, amount: form.value.amount.toFixed(2),
      interest: form.value.interest.toFixed(2), fine: form.value.fine.toFixed(2), discount: form.value.discount.toFixed(2),
      date: form.value.date.toLocaleDateString("sv-SE"),
    });
    notify.success(receivable.value ? "Recebimento registrado" : "Pagamento registrado");
    settling.value = null;
    emit("changed");
  } catch (error) {
    notify.error(error, "Não foi possível dar baixa");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="installments">
    <p v-if="!rows.length" class="muted empty">As parcelas são geradas ao salvar, pelo total e pelo nº de parcelas.</p>
    <div v-else class="table" role="table">
      <div class="row head" role="row">
        <span>Nº</span><span>Vencimento</span><span class="right">Valor</span><span class="right">Pago</span>
        <span class="right">Saldo</span><span>Situação</span><span />
      </div>
      <div v-for="row in rows" :key="row.id" class="row" role="row" :class="{ overdue: overdue(row) }">
        <span class="num">{{ row.number }}</span>
        <span>{{ date(row.due_date) }} <small v-if="overdue(row)" class="late">vencida</small></span>
        <span class="right num">{{ money(row.amount) }}</span>
        <span class="right">{{ money(row.paid_amount) }}</span>
        <strong class="right">{{ money(balanceOf(row)) }}</strong>
        <span><span class="pill" :class="STATUS[row.status]?.[1]">{{ STATUS[row.status]?.[0] ?? row.status }}</span></span>
        <Button v-if="['open', 'partial'].includes(row.status)" :label="receivable ? 'Receber' : 'Pagar'" icon="pi pi-check"
                size="small" severity="secondary" outlined @click="open(row)" />
        <small v-else class="muted">{{ row.paid_at ? date(row.paid_at) : "" }}</small>
      </div>
    </div>

    <Dialog :visible="settling !== null" modal :header="`${receivable ? 'Receber' : 'Pagar'} parcela ${settling?.number}`"
            :style="{ width: 'min(440px, calc(100vw - 24px))' }" @update:visible="settling = null">
      <div class="grid-form">
        <div class="field full">
          <label>{{ receivable ? "Entra na conta" : "Sai da conta" }}<span class="req">*</span></label>
          <RelationSelect v-model="form.financial_account" :relation="{ endpoint: '/finance/accounts/', params: { is_active: 'true' } }" />
        </div>
        <div class="field span-3"><label>Valor</label>
          <InputNumber v-model="form.amount" mode="currency" currency="BRL" locale="pt-BR" fluid /></div>
        <div class="field span-3"><label>Data</label>
          <DatePicker v-model="form.date" date-format="dd/mm/yy" show-icon fluid /></div>
        <div class="field"><label>Juros</label><InputNumber v-model="form.interest" mode="currency" currency="BRL" locale="pt-BR" fluid /></div>
        <div class="field"><label>Multa</label><InputNumber v-model="form.fine" mode="currency" currency="BRL" locale="pt-BR" fluid /></div>
        <div class="field"><label>Desconto</label><InputNumber v-model="form.discount" mode="currency" currency="BRL" locale="pt-BR" fluid /></div>
      </div>
      <p class="hint muted">Saldo da parcela: {{ settling ? money(balanceOf(settling)) : "" }} · menos que o saldo deixa a parcela parcial.</p>
      <template #footer>
        <Button label="Cancelar" severity="secondary" text @click="settling = null" />
        <Button :label="`Confirmar ${money(total)}`" icon="pi pi-check" :loading="saving" @click="settle" />
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
.empty { margin: 0; font-size: 13px; }
.table { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.row { display: grid; grid-template-columns: 44px 1.2fr 1fr 1fr 1fr 1fr 110px; gap: 0.5rem; align-items: center;
       padding: 8px 12px; border-top: 1px solid var(--border-subtle); font-size: 13.5px; }
.head { border-top: 0; background: var(--surface-sunken); font: 650 11.5px/1.3 var(--font-sans); letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
.overdue { background: var(--danger-subtle); }
.late { color: var(--danger-text); font-weight: 600; margin-left: 4px; }
.right { text-align: right; }
.num { font-weight: 600; color: var(--text-strong); }
.hint { margin-top: 0.75rem; font-size: 12px; }
@media (max-width: 760px) { .table { overflow-x: auto; } .row { min-width: 640px; } }
</style>
