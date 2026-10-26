<script setup lang="ts">
/**
 * Pagamento: o operador monta a lista (pode dividir em várias formas) e só no
 * "Finalizar" tudo vai junto para o checkout — uma transação no backend.
 * Troco só existe em dinheiro: nas outras formas o valor não passa do saldo.
 * Cartão/PIX pedem o NSU/autorização do comprovante (sem ele não lança), e
 * crediário/vale-troca só ficam liberados com cliente na venda.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import { computed, ref, watch } from "vue";

import type { PaymentInput } from "@/api/sales";
import type { PaymentMethod, Sale } from "@/api/types";
import { money } from "@/utils/format";

/** `sale`: para mostrar a conta (itens, descontos, FRETE da entrega) antes das formas de pagamento. */
const props = defineProps<{ total: string; methods: PaymentMethod[]; busy: boolean; hasCustomer: boolean;
                            sale?: Sale | null }>();
type Delivery = { table_name: string; lead_days: number | null; address_label: string };
const delivery = computed(() => (props.sale?.shipping_address
  ? ((props.sale?.metafields ?? {}) as Record<string, unknown>)._entrega as Delivery | undefined : undefined));
const billRows = computed(() => {
  const s = props.sale;
  if (!s) return [];
  const rows: { label: string; value: number; tone?: string }[] = [{ label: "Itens", value: Number(s.subtotal) }];
  if (Number(s.discount)) rows.push({ label: "Desconto", value: -Number(s.discount), tone: "neg" });
  if (Number(s.coupon_discount)) rows.push({ label: `Cupom ${s.coupon_code}`, value: -Number(s.coupon_discount), tone: "neg" });
  rows.push({ label: delivery.value ? `Frete · ${delivery.value.table_name}` : "Frete (retirada na loja)",
              value: Number(s.freight ?? 0) });
  return rows;
});
const visible = defineModel<boolean>("visible", { required: true });
const emit = defineEmits<{ confirm: [payments: PaymentInput[]] }>();

type Line = PaymentInput & { name: string; kind: string };
const lines = ref<Line[]>([]);
const method = ref<PaymentMethod | null>(null);
const amount = ref<number | null>(null);
const installments = ref(1);
const reference = ref("");
const error = ref("");
const NEEDS_CUSTOMER = new Set(["installment_plan", "store_credit"]);
const blocked = (m: PaymentMethod) => NEEDS_CUSTOMER.has(m.kind) && !props.hasCustomer;

const ICONS: Record<string, string> = {
  cash: "pi pi-money-bill", credit_card: "pi pi-credit-card", debit_card: "pi pi-credit-card", pix: "pi pi-qrcode",
  voucher: "pi pi-ticket", store_credit: "pi pi-replay", installment_plan: "pi pi-calendar", bank_slip: "pi pi-file",
};

const paid = computed(() => lines.value.reduce((sum, l) => sum + Number(l.amount), 0));
const remaining = computed(() => Math.max(Number(props.total) - paid.value, 0));
const change = computed(() => lines.value.reduce((sum, l) => sum + Math.max(Number(l.tendered ?? l.amount) - Number(l.amount), 0), 0));

watch(visible, (open) => {
  if (open) {
    lines.value = [];
    error.value = "";
    pick(props.methods.find((m) => !blocked(m)) ?? null);
  }
});

function pick(next: PaymentMethod | null) {
  if (next && blocked(next)) {
    error.value = `${next.name} exige o cliente na venda: identifique o cliente antes (F3).`;
    return;
  }
  method.value = next;
  amount.value = Number(remaining.value.toFixed(2));
  installments.value = 1;
  reference.value = "";
  error.value = "";
}

/** Valor exato + notas comuns acima do saldo, para o troco sair em um toque. */
const quickCash = computed(() => {
  const due = remaining.value;
  const out = new Set<number>([Number(due.toFixed(2))]);
  for (const note of [5, 10, 20, 50, 100, 200]) {
    const v = Math.ceil(due / note) * note;
    if (v > due + 0.001) out.add(v);
  }
  return [...out].sort((a, b) => a - b).slice(0, 5);
});

/** Lança a linha; devolve false (com a mensagem) se faltar algo. */
function add(): boolean {
  error.value = "";
  if (!method.value) return false;
  if (!amount.value || amount.value <= 0) {
    error.value = "Informe o valor.";
    return false;
  }
  const isCash = method.value.kind === "cash";
  const value = isCash ? Math.min(amount.value, remaining.value) : amount.value;
  if (!isCash && value > remaining.value + 0.001) {
    error.value = `Em ${method.value.name} o valor não pode passar de ${money(remaining.value)} (troco só em dinheiro).`;
    return false;
  }
  if (method.value.requires_reference && !reference.value.trim()) {
    error.value = `Digite o NSU/autorização do comprovante de ${method.value.name}.`;
    document.getElementById("pdv-pay-ref")?.focus();
    return false;
  }
  lines.value.push({
    method: method.value.id, name: method.value.name, kind: method.value.kind,
    amount: value.toFixed(2), tendered: isCash ? amount.value.toFixed(2) : undefined,
    installments: installments.value,
    ...(method.value.requires_reference ? { nsu: reference.value.trim() } : {}),
  });
  pick(method.value);
  return true;
}

function cash(value: number) {
  amount.value = value;
  add();
}

function finish() {
  if (amount.value && remaining.value > 0.001 && !add()) return;
  if (remaining.value > 0.001) {
    error.value = `Ainda falta ${money(remaining.value)}.`;
    return;
  }
  emit("confirm", lines.value.map((line) => ({
    method: line.method, amount: line.amount, tendered: line.tendered, installments: line.installments, nsu: line.nsu,
  })));
}
</script>

<template>
  <Dialog v-model:visible="visible" modal header="Pagamento" :style="{ width: '46rem' }" :breakpoints="{ '760px': '96vw' }">
    <dl v-if="billRows.length" class="bill">
      <div v-for="row in billRows" :key="row.label" :class="row.tone"><dt>{{ row.label }}</dt>
        <dd>{{ row.value < 0 ? "− " : "" }}{{ money(Math.abs(row.value)) }}</dd></div>
      <p v-if="delivery" class="bill__note"><i class="pi pi-truck" /> Entrega em {{ delivery.address_label }} ·
        {{ delivery.lead_days ? `${delivery.lead_days} dia(s) útil(eis)` : "no mesmo dia" }}</p>
    </dl>
    <div class="summary">
      <div class="tile"><span>Total</span><strong class="num">{{ money(total) }}</strong></div>
      <div class="tile"><span>Pago</span><strong class="num">{{ money(paid) }}</strong></div>
      <div class="tile" :class="change > 0 ? 'tile--change' : remaining > 0.001 ? 'tile--due' : 'tile--ok'">
        <span>{{ change > 0 ? "Troco" : remaining > 0.001 ? "Falta" : "Pago" }}</span>
        <strong class="num">{{ money(change > 0 ? change : remaining) }}</strong>
      </div>
    </div>

    <div class="methods">
      <button v-for="m in methods" :key="m.id" type="button" class="method"
              :class="{ active: method?.id === m.id, blocked: blocked(m) }" :disabled="remaining <= 0.001"
              :title="blocked(m) ? 'Exige cliente na venda' : undefined" @click="pick(m)">
        <i :class="ICONS[m.kind] ?? 'pi pi-wallet'" />
        <span>{{ m.name }}</span>
        <small v-if="blocked(m)">exige cliente</small>
      </button>
    </div>

    <div v-if="method && remaining > 0.001" class="entry">
      <div class="field">
        <label>{{ method.kind === "cash" ? "Valor recebido" : "Valor" }}</label>
        <InputNumber v-model="amount" mode="currency" currency="BRL" locale="pt-BR" autofocus fluid size="large" @keydown.enter="add" />
      </div>
      <div v-if="(method.max_installments ?? 1) > 1" class="field installments">
        <label>Parcelas</label>
        <InputNumber v-model="installments" :min="1" :max="method.max_installments" show-buttons fluid size="large" />
      </div>
      <div v-if="method.requires_reference" class="field">
        <label for="pdv-pay-ref">NSU / autorização <b class="req">*</b></label>
        <InputText id="pdv-pay-ref" v-model="reference" fluid size="large" placeholder="Do comprovante"
                   :invalid="!!error && !reference" @keydown.enter="add" />
      </div>
      <Button label="Adicionar" icon="pi pi-plus" severity="secondary" size="large" @click="add" />
    </div>
    <div v-if="method?.kind === 'cash' && remaining > 0.001" class="quick">
      <span>Recebido:</span>
      <Button v-for="v in quickCash" :key="v" :label="money(v)" size="small" severity="secondary" outlined @click="cash(v)" />
    </div>
    <p v-if="error" class="error" role="alert"><i class="pi pi-exclamation-circle" /> {{ error }}</p>

    <TransitionGroup v-if="lines.length" name="row" tag="ul" class="lines">
      <li v-for="(line, index) in lines" :key="`${line.method}-${index}`">
        <i :class="ICONS[line.kind] ?? 'pi pi-wallet'" />
        <span class="lines__name">{{ line.name }}<small v-if="(line.installments ?? 1) > 1"> · {{ line.installments }}x</small><small v-if="line.nsu"> · NSU {{ line.nsu }}</small><small v-if="line.tendered && Number(line.tendered) > Number(line.amount)"> · recebido {{ money(line.tendered) }}</small></span>
        <strong class="num">{{ money(line.amount) }}</strong>
        <Button icon="pi pi-times" text rounded severity="danger" aria-label="Remover" @click="lines.splice(index, 1)" />
      </li>
    </TransitionGroup>

    <template #footer>
      <Button label="Voltar" severity="secondary" outlined @click="visible = false" />
      <Button label="Finalizar venda" icon="pi pi-check" :loading="busy" :disabled="remaining > 0.001 && !amount" @click="finish" />
    </template>
  </Dialog>
</template>

<style scoped>
.bill { margin: 0 0 12px; padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border-subtle); background: var(--surface-sunken); }
.bill div { display: flex; justify-content: space-between; font-size: 13.5px; padding: 2px 0; }
.bill dt { color: var(--text-muted); }
.bill dd { margin: 0; color: var(--text-strong); font-weight: 600; }
.bill .neg dd { color: var(--danger-text); }
.bill__note { margin: 6px 0 0; font-size: 12px; color: var(--text-brand); display: flex; gap: 6px; align-items: center; }
.summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 1.25rem; }
.tile { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px; background: var(--surface-sunken); border: 1px solid var(--border-subtle); }
.tile span { font-size: 11.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
.tile strong { font: 800 1.5rem/1.1 var(--font-sans); color: var(--text-strong); }
.tile--due { background: var(--warning-subtle); border-color: transparent; } .tile--due strong { color: var(--warning-text); }
.tile--change { background: var(--brand-subtle); border-color: var(--brand-border); } .tile--change strong { color: var(--text-brand); }
.tile--ok { background: var(--success-subtle); border-color: transparent; } .tile--ok strong { color: var(--success-text); }
.methods { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(130px, 100%), 1fr)); gap: 8px; margin-bottom: 1.25rem; }
.method {
  display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 14px 10px; cursor: pointer;
  border: 1px solid var(--border); border-radius: 12px; background: var(--surface-card); color: var(--text-body); font: 600 13px/1.2 var(--font-sans);
}
.method i { font-size: 20px; color: var(--text-muted); transition: color var(--dur-fast) ease, transform var(--dur-base) var(--ease-spring); }
.method:enabled:hover { border-color: var(--brand-border); background: var(--surface-hover); }
.method:enabled:hover i { color: var(--brand); transform: translateY(-1px); }
.method.active { border-color: var(--brand); background: var(--brand-subtle); color: var(--text-brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 18%, transparent); }
.method.active i { color: var(--brand); }
.method:disabled { opacity: 0.5; cursor: default; }
.method.blocked { opacity: 0.55; border-style: dashed; }
.method small { font-size: 10.5px; font-weight: 600; color: var(--warning-text); }
.quick { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 0.75rem; font-size: 12.5px; color: var(--text-muted); }
.error { margin: 0.75rem 0 0; display: flex; gap: 6px; align-items: center; color: var(--danger-text); font-size: 13px; font-weight: 600; }
.req { color: var(--danger-text); }
.entry { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; }
.entry .field { flex: 1; }
.entry .installments { flex: 0 0 9rem; }
.lines { list-style: none; padding: 0; margin: 1.25rem 0 0; display: flex; flex-direction: column; gap: 6px; }
.lines li { display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 12px; border-radius: 10px; border: 1px solid var(--border-subtle); background: var(--surface-sunken); }
.lines li i { color: var(--brand); }
.lines__name { flex: 1; color: var(--text-strong); font-weight: 600; font-size: 13.5px; }
.lines__name small { color: var(--text-muted); font-weight: 500; }
.row-enter-active, .row-leave-active { transition: all var(--dur-base) var(--ease-spring); }
.row-enter-from, .row-leave-to { opacity: 0; transform: translateY(-6px); }
</style>
