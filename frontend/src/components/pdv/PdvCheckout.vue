<script setup lang="ts">
/**
 * Tela de pagamento do PDV (no lugar do antigo modal), no formato do PDV desktop do StarChef:
 *   à esquerda a CONFERÊNCIA (itens, cliente, vendedor, entrega/frete, desconto, cupom, total e
 *   os pagamentos lançados); à direita, onde fica o painel da venda, a forma de pagamento, o
 *   valor e o teclado.
 *
 * O operador monta a lista (pode dividir em várias formas) e só no "Concluir venda" tudo vai
 * junto para o checkout — uma transação no backend. A lista mora no PdvPage (`v-model:lines`):
 * sair para trocar o cliente ou a entrega e voltar não perde o que já foi lançado.
 * Troco só existe em dinheiro: nas outras formas o valor não passa do saldo.
 * Cartão/PIX mostram o campo do NSU/autorização: opcional; obrigatório só com a regra da
 * filial ligada (`requireReference`). Crediário e vale-troca exigem cliente na venda.
 * O valor entra como no StarChef: dígitos pela direita (centavos), pelo teclado da tela ou
 * pelo físico; enquanto ninguém digita, ele acompanha o que falta (desconto/cupom mudam o total).
 */
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import { computed, onMounted, ref, watch } from "vue";

import type { PaymentInput } from "@/api/sales";
import type { PaymentMethod, Sale, SaleItem, Seller } from "@/api/types";
import { money, quantity } from "@/utils/format";

export type PaymentLine = PaymentInput & { name: string; kind: string };

const props = defineProps<{
  sale: Sale; items: SaleItem[]; methods: PaymentMethod[]; sellers: Seller[]; operator: string; busy: boolean;
  requireReference?: boolean; requireSeller?: boolean;
}>();
const lines = defineModel<PaymentLine[]>("lines", { required: true });
const emit = defineEmits<{
  back: []; finish: [payments: PaymentInput[]]; customer: []; delivery: []; discount: []; coupon: [];
  seller: [id: number | null];
}>();

const ICONS: Record<string, string> = {
  cash: "pi pi-money-bill", credit_card: "pi pi-credit-card", debit_card: "pi pi-credit-card", pix: "pi pi-qrcode",
  voucher: "pi pi-ticket", store_credit: "pi pi-replay", installment_plan: "pi pi-calendar", bank_slip: "pi pi-file",
};
const NEEDS_CUSTOMER = new Set(["installment_plan", "store_credit"]);
const blocked = (m: PaymentMethod) => NEEDS_CUSTOMER.has(m.kind) && !props.sale.customer;

/* ---- Conferência ---- */
type Delivery = { table_name: string; lead_days: number | null; address_label: string };
const delivery = computed(() => (props.sale.shipping_address
  ? ((props.sale.metafields ?? {}) as Record<string, unknown>)._entrega as Delivery | undefined : undefined));
/** Retirada escolhida. Sem entrega nem retirada a venda não conclui: o operador escolhe (F11). */
const pickup = computed(() => !delivery.value && Boolean(((props.sale.metafields ?? {}) as Record<string, unknown>)._retirada));
const undecided = computed(() => !delivery.value && !pickup.value);
const customerLabel = computed(() => props.sale.customer_name
  || (props.sale.customer_document ? `CPF/CNPJ ${props.sale.customer_document}` : ""));
const units = computed(() => props.items.filter((i) => !i.parent_item)
  .reduce((sum, i) => sum + ((i.unit ?? "UN") === "UN" ? Number(i.quantity) : 1), 0));
/** Item e logo abaixo os serviços dele (montagem, garantia), como no painel da venda. */
const ordered = computed(() => {
  const children = (id: string) => props.items.filter((i) => i.parent_item === id);
  const ids = new Set(props.items.map((i) => i.id));
  return props.items.filter((i) => !i.parent_item || !ids.has(i.parent_item)).flatMap((i) => [i, ...children(i.id)]);
});

/* ---- Valores ---- */
const due = computed(() => Number(props.sale.balance_due ?? props.sale.total));
const paid = computed(() => lines.value.reduce((sum, l) => sum + Number(l.amount), 0));
const remaining = computed(() => Math.max(due.value - paid.value, 0));
const over = computed(() => paid.value - due.value > 0.001);
const change = computed(() => lines.value.reduce((sum, l) => sum + Math.max(Number(l.tendered ?? l.amount) - Number(l.amount), 0), 0));

/* ---- Lançamento ---- */
const method = ref<PaymentMethod | null>(null);
const digits = ref("0");
const typed = ref(false);
const installments = ref(1);
const reference = ref("");
const error = ref("");
const amount = computed(() => Number(digits.value) / 100);
const amountText = computed(() => amount.value.toLocaleString("pt-BR", { minimumFractionDigits: 2 }));
const isCash = computed(() => method.value?.kind === "cash");
/** Troco do valor que está no visor (antes de lançar). */
const pendingChange = computed(() => (isCash.value ? Math.max(amount.value - remaining.value, 0) : 0));

function suggest() {
  typed.value = false;
  digits.value = String(Math.round(remaining.value * 100));
}
/** O total mudou (desconto, cupom, frete) ou uma linha saiu: o visor volta a mostrar o que falta. */
watch(remaining, () => !typed.value && suggest());

function pick(next: PaymentMethod | null) {
  if (next && blocked(next)) {
    error.value = `${next.name} exige o cliente na venda: identifique o cliente antes (F3).`;
    return;
  }
  method.value = next;
  installments.value = 1;
  reference.value = "";
  error.value = "";
  suggest();
}

function press(key: string) {
  typed.value = true;
  if (key === "clear") digits.value = "0";
  else if (key === "back") digits.value = digits.value.length <= 1 ? "0" : digits.value.slice(0, -1);
  else digits.value = (digits.value === "0" ? key : digits.value + key).slice(0, 9);
}
/** Teclado físico no visor: mesma regra das teclas (dígitos pela direita). */
function type(raw: string) {
  typed.value = true;
  digits.value = String(Number(raw.replace(/\D/g, "").slice(-9) || "0"));
}

/** Valor exato + notas comuns acima do saldo, para o troco sair em um toque. */
const quickCash = computed(() => {
  const value = remaining.value;
  const out = new Set<number>([Number(value.toFixed(2))]);
  for (const note of [5, 10, 20, 50, 100, 200]) {
    const v = Math.ceil(value / note) * note;
    if (v > value + 0.001) out.add(v);
  }
  return [...out].sort((a, b) => a - b).slice(0, 4);
});
function quick(value: number) {
  typed.value = true;
  digits.value = String(Math.round(value * 100));
  add();
}

/** Lança a linha; devolve false (com a mensagem) se faltar algo. */
function add(): boolean {
  error.value = "";
  const m = method.value;
  if (!m) {
    error.value = "Escolha a forma de pagamento.";
    return false;
  }
  if (amount.value <= 0) {
    error.value = "Informe o valor.";
    return false;
  }
  if (remaining.value <= 0.001) {
    error.value = "A venda já está paga.";
    return false;
  }
  const value = isCash.value ? Math.min(amount.value, remaining.value) : amount.value;
  if (!isCash.value && value > remaining.value + 0.001) {
    error.value = `Em ${m.name} o valor não pode passar de ${money(remaining.value)} (troco só em dinheiro).`;
    return false;
  }
  if (m.requires_reference && props.requireReference && !reference.value.trim()) {
    error.value = `Digite o NSU/autorização do comprovante de ${m.name}.`;
    document.getElementById("pdv-pay-ref")?.focus();
    return false;
  }
  lines.value = [...lines.value, {
    method: m.id, name: m.name, kind: m.kind,
    amount: value.toFixed(2), tendered: isCash.value ? amount.value.toFixed(2) : undefined,
    installments: installments.value,
    ...(m.requires_reference && reference.value.trim() ? { nsu: reference.value.trim() } : {}),
  }];
  pick(m);
  return true;
}

function removeLine(index: number) {
  lines.value = lines.value.filter((_, i) => i !== index);
}

/** F10 / "Concluir": com valor no visor e saldo aberto, lança antes de concluir — pagamento
 *  único no valor exato sai num toque só. */
function finish() {
  if (props.requireSeller && !props.sale.seller) {
    error.value = "Esta filial exige vendedor: escolha o vendedor na conferência ao lado.";
    return;
  }
  if (undecided.value) {
    error.value = "Escolha se é entrega ou retirada na loja (F11) antes de concluir.";
    return;
  }
  if (amount.value > 0 && remaining.value > 0.001 && !add()) return;
  if (over.value) {
    error.value = "Os pagamentos passam do total (o desconto ou o cupom mudou). Remova um pagamento.";
    return;
  }
  if (remaining.value > 0.001) {
    error.value = `Ainda falta ${money(remaining.value)}.`;
    return;
  }
  emit("finish", lines.value.map((line) => ({
    method: line.method, amount: line.amount, tendered: line.tendered, installments: line.installments, nsu: line.nsu,
  })));
}
defineExpose({ finish });

onMounted(() => {
  pick(props.methods.find((m) => !blocked(m)) ?? null);
  setTimeout(() => document.getElementById("pdv-pay-amount")?.focus());
});
</script>

<template>
  <section class="review" aria-label="Conferência da venda">
    <header class="review__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para a venda (Esc)" @click="emit('back')" />
      <div>
        <h2>Pagamento · Venda {{ sale.number }}</h2>
        <p>Confira tudo antes de receber. Voltar (Esc) mantém a venda como está.</p>
      </div>
    </header>

    <div class="who">
      <button type="button" class="who__card" @click="emit('customer')">
        <i class="pi pi-user" />
        <span><small>Cliente</small><strong>{{ customerLabel || "Consumidor (sem cliente)" }}</strong></span>
        <kbd>F3</kbd>
      </button>
      <button type="button" class="who__card" :class="{ 'who__card--todo': undecided }" @click="emit('delivery')">
        <i :class="delivery ? 'pi pi-truck' : pickup ? 'pi pi-shop' : 'pi pi-exclamation-circle'" />
        <span v-if="delivery"><small>Entrega · {{ delivery.table_name }}</small>
          <strong>{{ delivery.address_label }} · {{ delivery.lead_days ? `${delivery.lead_days} dia(s) útil(eis)` : "no mesmo dia" }}</strong></span>
        <span v-else-if="pickup"><small>Entrega</small><strong>Retirada na loja</strong></span>
        <span v-else><small>Entrega</small><strong>Escolha entrega ou retirada</strong></span>
        <kbd>F11</kbd>
      </button>
      <div class="who__card who__card--static">
        <i class="pi pi-id-card" />
        <span><small>Vendedor</small>
          <Select v-if="sellers.length" :model-value="sale.seller ?? null" :options="sellers" option-label="name" option-value="user_id"
                  :show-clear="!requireSeller" filter :placeholder="requireSeller ? 'Escolha o vendedor (obrigatório)' : 'Sem vendedor (fica com o caixa)'"
                  size="small" :disabled="busy" class="who__seller" :invalid="requireSeller && !sale.seller"
                  @update:model-value="emit('seller', $event ?? null)" />
          <strong v-else>{{ sale.seller_name || "Sem vendedor" }}</strong></span>
      </div>
      <div class="who__card who__card--static">
        <i class="pi pi-desktop" />
        <span><small>Operador</small><strong>{{ operator || "—" }}</strong></span>
      </div>
    </div>

    <div class="items">
      <div class="items__head"><span>Itens</span><small>{{ items.length }} {{ items.length === 1 ? "linha" : "linhas" }} ·
        {{ quantity(units) }} un.</small></div>
      <ul>
        <li v-for="item in ordered" :key="item.id" :class="{ service: item.parent_item }">
          <span class="items__qty">{{ quantity(item.quantity) }}{{ (item.unit ?? "UN") === "UN" ? "×" : ` ${(item.unit ?? "").toLowerCase()}` }}</span>
          <span class="items__name"><i v-if="item.parent_item" class="pi pi-wrench" /> {{ item.description }}
            <small>{{ money(item.unit_price) }}<template v-if="Number(item.list_price) > Number(item.unit_price)">
              · de {{ money(item.list_price) }}</template><template v-if="item.promotion"> · <b class="promo">promoção</b></template></small></span>
          <strong>{{ money(item.total) }}</strong>
        </li>
      </ul>
    </div>

    <div class="bill">
      <dl>
        <div><dt>Subtotal dos itens</dt><dd>{{ money(sale.subtotal) }}</dd></div>
        <div v-if="Number(sale.discount)" class="neg"><dt>Desconto</dt><dd>− {{ money(sale.discount) }}</dd></div>
        <div v-if="sale.coupon_code" class="neg"><dt>Cupom {{ sale.coupon_code }}</dt><dd>− {{ money(sale.coupon_discount) }}</dd></div>
        <div><dt>{{ delivery ? `Frete · ${delivery.table_name}` : pickup ? "Frete (retirada na loja)" : "Frete (a escolher)" }}</dt><dd>{{ Number(sale.freight) ? `+ ${money(sale.freight)}` : money(0) }}</dd></div>
        <div v-if="Number(sale.paid_amount)"><dt>Já pago</dt><dd>− {{ money(sale.paid_amount) }}</dd></div>
        <div class="bill__total"><dt>Total a pagar</dt><dd>{{ money(due) }}</dd></div>
      </dl>
      <div class="bill__adjust">
        <Button severity="secondary" outlined size="small" :disabled="busy" @click="emit('discount')">
          <i class="pi pi-percentage" /> {{ Number(sale.discount) ? "Alterar desconto" : "Desconto" }} <kbd>F6</kbd></Button>
        <Button severity="secondary" outlined size="small" :disabled="busy" @click="emit('coupon')">
          <i class="pi pi-ticket" /> {{ sale.coupon_code ? "Trocar cupom" : "Cupom" }} <kbd>F7</kbd></Button>
      </div>
    </div>

    <div class="paid">
      <div class="items__head"><span>Pagamentos desta venda</span><small v-if="lines.length">Vão juntos ao concluir</small></div>
      <p v-if="!lines.length" class="paid__empty">Nenhum pagamento lançado. Escolha a forma ao lado e adicione.</p>
      <TransitionGroup v-else name="row" tag="ul">
        <li v-for="(line, index) in lines" :key="`${line.method}-${index}`">
          <i :class="ICONS[line.kind] ?? 'pi pi-wallet'" />
          <span class="paid__name">{{ line.name }}<small v-if="(line.installments ?? 1) > 1"> · {{ line.installments }}x</small><small v-if="line.nsu"> · NSU {{ line.nsu }}</small><small v-if="line.tendered && Number(line.tendered) > Number(line.amount)"> · recebido {{ money(line.tendered) }} · troco {{ money(Number(line.tendered) - Number(line.amount)) }}</small></span>
          <strong>{{ money(line.amount) }}</strong>
          <Button icon="pi pi-times" text rounded severity="danger" size="small" aria-label="Remover pagamento" @click="removeLine(index)" />
        </li>
      </TransitionGroup>
    </div>
  </section>

  <aside class="pay" aria-label="Recebimento">
    <div class="tiles">
      <div class="tile"><span>Total</span><strong>{{ money(due) }}</strong></div>
      <div class="tile"><span>Recebido</span><strong>{{ money(paid) }}</strong></div>
      <div class="tile tile--wide" :class="change > 0 ? 'tile--change' : remaining > 0.001 ? 'tile--due' : 'tile--ok'">
        <span>{{ change > 0 ? "Troco a entregar" : remaining > 0.001 ? "Falta receber" : "Pago" }}</span>
        <strong>{{ money(change > 0 ? change : remaining) }}</strong>
      </div>
    </div>

    <div class="field">
      <label for="pdv-pay-method">Forma de pagamento</label>
      <Select input-id="pdv-pay-method" :model-value="method" :options="methods" option-label="name" data-key="id" fluid
              :option-disabled="blocked" :disabled="remaining <= 0.001" placeholder="Escolha" @update:model-value="pick">
        <template #value="{ value }">
          <span v-if="value" class="opt"><i :class="ICONS[value.kind] ?? 'pi pi-wallet'" /> {{ value.name }}</span>
          <span v-else>Escolha</span>
        </template>
        <template #option="{ option }">
          <span class="opt"><i :class="ICONS[option.kind] ?? 'pi pi-wallet'" /> {{ option.name }}
            <small v-if="blocked(option)">exige cliente</small></span>
        </template>
      </Select>
    </div>

    <div v-if="method && ((method.max_installments ?? 1) > 1 || method.requires_reference)" class="extra">
      <div v-if="(method.max_installments ?? 1) > 1" class="field">
        <label>Parcelas</label>
        <InputNumber v-model="installments" :min="1" :max="method.max_installments" show-buttons fluid />
      </div>
      <div v-if="method.requires_reference" class="field">
        <label for="pdv-pay-ref">NSU / autorização <b v-if="requireReference" class="req">*</b></label>
        <InputText id="pdv-pay-ref" v-model="reference" fluid :placeholder="requireReference ? 'Do comprovante' : 'Opcional'"
                   :invalid="!!error && !reference" @keydown.enter="add" />
      </div>
    </div>

    <div class="field">
      <label for="pdv-pay-amount">{{ isCash ? "Valor recebido" : "Valor do pagamento" }}</label>
      <div class="display">
        <span>R$</span>
        <input id="pdv-pay-amount" :value="amountText" inputmode="numeric" autocomplete="off" :disabled="remaining <= 0.001"
               @input="type(($event.target as HTMLInputElement).value)" @keydown.enter.prevent="add" />
      </div>
    </div>
    <div v-if="pendingChange > 0.001" class="change"><span>Troco</span><strong>{{ money(pendingChange) }}</strong></div>
    <div v-if="isCash && remaining > 0.001" class="quick">
      <button v-for="v in quickCash" :key="v" type="button" @click="quick(v)">{{ money(v) }}</button>
    </div>

    <div class="keypad">
      <button v-for="key in ['1','2','3','4','5','6','7','8','9','clear','0','back']" :key="key" type="button"
              :disabled="remaining <= 0.001" :aria-label="key === 'back' ? 'Apagar' : key === 'clear' ? 'Limpar' : key" @click="press(key)">
        <i v-if="key === 'back'" class="pi pi-delete-left" /><template v-else>{{ key === "clear" ? "C" : key }}</template>
      </button>
    </div>

    <p v-if="error" class="error" role="alert"><i class="pi pi-exclamation-circle" /> {{ error }}</p>

    <Button severity="secondary" outlined class="add" :disabled="remaining <= 0.001 || amount <= 0 || busy" @click="add">
      <i class="pi pi-plus" /> {{ pendingChange > 0.001 ? "Receber e registrar troco" : "Adicionar pagamento" }} <kbd>Enter</kbd>
    </Button>
    <Button class="finish" :loading="busy" :disabled="busy || (remaining > 0.001 && amount <= 0)" @click="finish">
      <i v-if="!busy" class="pi pi-check-circle" /> Concluir venda <kbd>F10</kbd>
    </Button>
  </aside>
</template>

<style scoped>
/* ---- Conferência (esquerda) ---- */
.review { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 12px 16px 16px; overflow-y: auto; }
.review__head { display: flex; align-items: flex-start; gap: 10px; }
.review__head h2 { margin: 0; font: 800 17px/1.2 var(--font-sans); color: var(--text-strong); }
.review__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.who { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr)); gap: 8px; }
.who__card {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px; min-height: 56px; border-radius: 10px; text-align: left;
  border: 1px solid var(--border-subtle); background: var(--surface-card); color: var(--text-body); font: inherit; cursor: pointer;
}
button.who__card:hover { border-color: var(--brand-border); background: var(--surface-hover); }
.who__card--todo { border-style: dashed; border-color: var(--warning-text); background: var(--warning-subtle); }
.who__card--todo > i, .who__card--todo strong { color: var(--warning-text); }
.who__card--static { cursor: default; }
.who__card > i { font-size: 16px; color: var(--brand); }
.who__card > span { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.who__card small { font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
.who__card strong { font-size: 13.5px; color: var(--text-strong); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.who__seller { width: 100%; }
.items, .bill, .paid { border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--surface-card); padding: 10px 14px; }
.items__head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.items__head span { font-size: 12px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
.items__head small { font-size: 12px; color: var(--text-muted); }
.items ul, .paid ul { list-style: none; margin: 0; padding: 0; }
.items li { display: flex; align-items: baseline; gap: 10px; padding: 7px 0; border-top: 1px solid var(--border-subtle); font-size: 13.5px; }
.items li:first-child { border-top: 0; }
.items li.service { padding-left: 18px; }
.items li.service i { color: var(--brand); font-size: 11px; }
.items__qty { min-width: 46px; font-weight: 700; color: var(--text-strong); font-variant-numeric: tabular-nums; }
.items__name { flex: 1; min-width: 0; color: var(--text-strong); }
.items__name small { display: block; font-size: 12px; color: var(--text-muted); }
.items li > strong { white-space: nowrap; color: var(--text-strong); font-variant-numeric: tabular-nums; }
.promo { color: var(--accent); font-weight: 600; }
.bill { display: flex; flex-direction: column; gap: 10px; }
.bill dl { margin: 0; display: flex; flex-direction: column; gap: 4px; }
.bill dl div { display: flex; justify-content: space-between; font-size: 13.5px; }
.bill dt { color: var(--text-muted); }
.bill dd { margin: 0; font-weight: 600; color: var(--text-strong); font-variant-numeric: tabular-nums; }
.bill .neg dd { color: var(--danger-text); }
.bill__total { margin-top: 4px; padding-top: 8px; border-top: 1px solid var(--border-subtle); align-items: baseline; }
.bill__total dt { font-size: 15px; font-weight: 700; color: var(--text-strong); }
.bill__total dd { font: 800 1.6rem/1 var(--font-sans); color: var(--brand); }
.bill__adjust { display: flex; gap: 6px; flex-wrap: wrap; }
.bill__adjust :deep(.p-button) { gap: 6px; }
.paid__empty { margin: 4px 0; font-size: 13px; color: var(--text-muted); }
.paid li { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--border-subtle); }
.paid li:first-child { border-top: 0; }
.paid li > i { color: var(--brand); }
.paid__name { flex: 1; color: var(--text-strong); font-weight: 600; font-size: 13.5px; }
.paid__name small { color: var(--text-muted); font-weight: 500; }
.paid li > strong { font-variant-numeric: tabular-nums; color: var(--text-strong); }
kbd { font: 600 10px/1 var(--font-mono); padding: 2px 5px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-muted); margin-left: 4px; }

/* ---- Recebimento (direita, no lugar do painel da venda) ---- */
.pay {
  width: 400px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; min-height: 0; overflow-y: auto;
  padding: 12px 16px 14px; background: var(--surface-card); border-left: 1px solid var(--border);
}
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.tile { display: flex; flex-direction: column; gap: 3px; padding: 8px 12px; border-radius: 10px; background: var(--surface-sunken); border: 1px solid var(--border-subtle); }
.tile span { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-muted); }
.tile strong { font: 800 1.15rem/1.1 var(--font-sans); color: var(--text-strong); font-variant-numeric: tabular-nums; }
.tile--wide { grid-column: span 2; }
.tile--wide strong { font-size: 1.7rem; }
.tile--due { background: var(--warning-subtle); border-color: transparent; } .tile--due strong { color: var(--warning-text); }
.tile--change { background: var(--brand-subtle); border-color: var(--brand-border); } .tile--change strong { color: var(--text-brand); }
.tile--ok { background: var(--success-subtle); border-color: transparent; } .tile--ok strong { color: var(--success-text); }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.req { color: var(--danger-text); }
.opt { display: inline-flex; align-items: center; gap: 8px; }
.opt i { color: var(--brand); }
.opt small { font-size: 11px; color: var(--warning-text); }
.extra { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.display {
  display: flex; align-items: center; gap: 8px; padding: 0 12px; height: 56px; border-radius: 10px;
  border: 1px solid var(--border-strong); background: var(--surface-sunken);
}
.display:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 18%, transparent); }
.display span { font-weight: 700; color: var(--text-muted); }
.display input {
  flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; text-align: right;
  font: 900 1.8rem/1 var(--font-sans); color: var(--text-strong); font-variant-numeric: tabular-nums;
}
.change { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-radius: 10px;
          background: var(--success-subtle); color: var(--success-text); font-weight: 800; }
.change strong { font-size: 1.25rem; }
.quick { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.quick button, .keypad button {
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface-card); color: var(--text-strong);
  font: 700 13px/1 var(--font-sans); cursor: pointer;
}
.quick button { height: 34px; }
.quick button:hover, .keypad button:hover:enabled { border-color: var(--brand-border); background: var(--surface-hover); }
.keypad { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.keypad button { height: 48px; font-size: 18px; font-weight: 800; }
.keypad button:disabled { opacity: 0.45; cursor: default; }
.error { margin: 0; display: flex; gap: 6px; align-items: center; color: var(--danger-text); font-size: 13px; font-weight: 600; }
.add, .finish { width: 100%; justify-content: center; gap: 8px; }
.finish { height: 3.2rem; font-size: 1.05rem; margin-top: auto; }
.finish kbd { border-color: rgba(255, 255, 255, 0.4); color: inherit; }
.row-enter-active, .row-leave-active { transition: all var(--dur-base) var(--ease-spring); }
.row-enter-from, .row-leave-to { opacity: 0; transform: translateY(-6px); }
@media (max-width: 1100px) { .pay { width: 360px; } }
@media (max-width: 860px) {
  .review { min-height: 35%; }
  .pay { width: auto; max-height: 65dvh; border-left: 0; border-top: 1px solid var(--border); }
}
</style>
