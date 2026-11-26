<script setup lang="ts">
/**
 * Parcelas do título (contas a pagar/receber) com a BAIXA na própria linha.
 *
 * "Baixar" abre: conta (de onde sai/entra o dinheiro), valor (já vem o saldo),
 * juros, multa, desconto e data. Pagar menos que o saldo deixa a parcela
 * "paga parcialmente". Vencida: multa e juros do título já vêm preenchidos.
 * Com cliente/fornecedor: usar o crédito dele (pago a mais antes) e aceitar
 * valor acima do saldo (o que passar vira crédito). O título novo ainda não
 * tem parcelas: elas nascem ao salvar.
 */
import Button from "primevue/button";
import DatePicker from "primevue/datepicker";
import Dialog from "primevue/dialog";
import Checkbox from "primevue/checkbox";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import { computed, ref } from "vue";

import { financeApi } from "@/api/operations";
import { useNotify } from "@/composables/useNotify";
import { date, money } from "@/utils/format";

import RelationSelect from "./RelationSelect.vue";

type Installment = {
  id: string; number: number; due_date: string; amount: string; paid_amount: string; paid_at: string | null;
  status: string; balance?: string; interest: string; fine: string; discount: string; due_time?: string | null;
  late?: { days_late: number; fine: string; interest: string; updated_balance: string };
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
const form = ref({ financial_account: null as string | null, amount: 0, interest: 0, fine: 0, discount: 0, date: new Date(),
                   useCredit: false, allowExcess: false });
const saving = ref(false);
const credit = ref(0);
const total = computed(() => form.value.amount);
/** O que falta pagar com os encargos digitados e o crédito usado. */
const due = computed(() => {
  if (!settling.value) return 0;
  const owed = balanceOf(settling.value) + form.value.interest + form.value.fine - form.value.discount;
  return Math.max(owed - (form.value.useCredit ? Math.min(credit.value, owed) : 0), 0);
});
const hasParty = computed(() => Boolean(props.context?.customer || props.context?.supplier));

function open(row: Installment) {
  settling.value = row;
  const fine = Number(row.late?.fine ?? 0);
  const interest = Number(row.late?.interest ?? 0);
  form.value = { financial_account: form.value.financial_account, amount: balanceOf(row) + fine + interest, interest, fine,
                 discount: 0, date: new Date(), useCredit: false, allowExcess: false };
  credit.value = 0;
  if (hasParty.value) {
    void financeApi.credit(row.id).then((r) => { credit.value = Number(r.credit); }).catch(() => undefined);
  }
}

function toggleCredit() {
  form.value.amount = Number(due.value.toFixed(2));
}

const undoing = ref<Installment | null>(null);
const reason = ref("");
async function undo() {
  if (!undoing.value) return;
  saving.value = true;
  try {
    await financeApi.unsettle(undoing.value.id, reason.value.trim());
    notify.success("Baixa desfeita", "O dinheiro voltou por lançamento inverso.");
    undoing.value = null;
    emit("changed");
  } catch (error) {
    notify.error(error, "Não foi possível desfazer a baixa");
  } finally {
    saving.value = false;
  }
}

async function settle() {
  if (!settling.value) return;
  if (!form.value.financial_account && form.value.amount > 0) return notify.warn("Escolha a conta.");
  saving.value = true;
  try {
    await financeApi.settle(settling.value.id, {
      financial_account: form.value.financial_account, amount: form.value.amount.toFixed(2),
      interest: form.value.interest.toFixed(2), fine: form.value.fine.toFixed(2), discount: form.value.discount.toFixed(2),
      date: form.value.date.toLocaleDateString("sv-SE"), use_credit: form.value.useCredit,
      allow_excess: form.value.allowExcess,
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
        <span>{{ date(row.due_date) }}<small v-if="row.due_time" class="muted"> {{ row.due_time.slice(0, 5) }}</small>
          <small v-if="overdue(row)" class="late">vencida{{ row.late?.days_late ? ` há ${row.late.days_late} d` : "" }}</small></span>
        <span class="right num">{{ money(row.amount) }}</span>
        <span class="right">{{ money(row.paid_amount) }}</span>
        <strong class="right">{{ money(balanceOf(row)) }}</strong>
        <span><span class="pill" :class="STATUS[row.status]?.[1]">{{ STATUS[row.status]?.[0] ?? row.status }}</span></span>
        <Button v-if="['open', 'partial'].includes(row.status)" :label="receivable ? 'Receber' : 'Pagar'" icon="pi pi-check"
                size="small" severity="secondary" outlined @click="open(row)" />
        <span v-else class="paid muted"><small>{{ row.paid_at ? date(row.paid_at) : "" }}</small></span>
        <Button v-if="Number(row.paid_amount) > 0" class="undo" label="Desfazer baixa" icon="pi pi-undo" size="small" severity="danger"
                text @click="undoing = row; reason = ''" />
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
          <InputNumber v-model="form.amount" mode="currency" currency="BRL" locale="pt-BR" :min="0" highlight-on-focus placeholder="R$ 0,00" fluid /></div>
        <div class="field span-3"><label>Data</label>
          <DatePicker v-model="form.date" date-format="dd/mm/yy" show-icon fluid /></div>
        <div class="field"><label>Juros</label><InputNumber v-model="form.interest" mode="currency" currency="BRL" locale="pt-BR" :min="0" highlight-on-focus placeholder="R$ 0,00" fluid /></div>
        <div class="field"><label>Multa</label><InputNumber v-model="form.fine" mode="currency" currency="BRL" locale="pt-BR" :min="0" highlight-on-focus placeholder="R$ 0,00" fluid /></div>
        <div class="field"><label>Desconto</label><InputNumber v-model="form.discount" mode="currency" currency="BRL" locale="pt-BR" :min="0" highlight-on-focus placeholder="R$ 0,00" fluid /></div>
      </div>
      <div v-if="hasParty" class="options">
        <label v-if="credit > 0" class="check"><Checkbox v-model="form.useCredit" binary @change="toggleCredit" />
          Usar o crédito de {{ money(credit) }} (pago a mais antes)</label>
        <label class="check"><Checkbox v-model="form.allowExcess" binary />
          Valor acima do saldo vira crédito {{ receivable ? "do cliente" : "com o fornecedor" }}</label>
      </div>
      <p class="hint muted">
        Saldo da parcela: {{ settling ? money(balanceOf(settling)) : "" }}
        <template v-if="settling?.late?.days_late"> · {{ settling.late.days_late }} dias de atraso: multa e juros do título já preenchidos</template>
        · a pagar agora: {{ money(due) }} · menos que isso deixa a parcela parcial.
      </p>
      <template #footer>
        <Button label="Cancelar" severity="secondary" text @click="settling = null" />
        <Button :label="`Confirmar ${money(total)}`" icon="pi pi-check" :loading="saving" @click="settle" />
      </template>
    </Dialog>

    <Dialog :visible="undoing !== null" modal :header="`Desfazer a baixa da parcela ${undoing?.number}`"
            :style="{ width: 'min(440px, calc(100vw - 24px))' }" @update:visible="undoing = null">
      <p class="muted">A parcela volta a ficar em aberto e o dinheiro sai da conta por um lançamento inverso. O crédito usado volta;
        o que foi pago a mais continua como crédito.</p>
      <div class="field"><label>Motivo<span class="req">*</span></label>
        <InputText v-model="reason" maxlength="150" autofocus fluid /></div>
      <template #footer>
        <Button label="Cancelar" severity="secondary" text @click="undoing = null" />
        <Button label="Desfazer baixa" icon="pi pi-undo" severity="danger" :loading="saving" :disabled="!reason.trim()" @click="undo" />
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
.undo { grid-column: 1 / -1; justify-self: end; }
.overdue { background: var(--danger-subtle); }
.late { color: var(--danger-text); font-weight: 600; margin-left: 4px; }
.right { text-align: right; }
.num { font-weight: 600; color: var(--text-strong); }
.hint { margin-top: 0.75rem; font-size: 12px; }
.options { display: flex; flex-direction: column; gap: 6px; margin-top: 0.75rem; font-size: 13px; }
.check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
@media (max-width: 760px) { .table { overflow-x: auto; } .row { min-width: 640px; } }
</style>
