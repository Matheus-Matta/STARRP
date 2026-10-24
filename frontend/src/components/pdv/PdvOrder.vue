<script setup lang="ts">
/**
 * Painel da venda (direita): cliente, vendedor, itens, totais e o caminho para o
 * pagamento. Quantidade muda nos botões − / + da linha; remover pede o motivo.
 */
import Button from "primevue/button";
import Select from "primevue/select";
import { computed, ref } from "vue";

import type { Sale, SaleItem, Seller } from "@/api/types";
import { money, quantity } from "@/utils/format";

/** `seller`: modo vendedor — sem pagamento; o pedido vai para o caixa ("Enviar ao caixa"). */
const props = defineProps<{ sale: Sale | null; items: SaleItem[]; sellers: Seller[]; busy: boolean; seller?: boolean }>();
const emit = defineEmits<{
  customer: []; seller: [id: number | null]; quantity: [item: SaleItem, value: string]; remove: [item: SaleItem];
  discount: []; coupon: []; pay: []; cancel: []; park: []; send: []; delivery: [];
}>();
/** Entrega lançada (metacampo do sistema `_entrega`) ou retirada na loja. */
const delivery = computed(() => {
  const info = ((props.sale?.metafields ?? {}) as Record<string, unknown>)._entrega as
    { table_name: string; lead_days: number | null; address_label: string } | undefined;
  return props.sale?.shipping_address && info ? info : null;
});

const customerLabel = computed(() => props.sale?.customer_name || (props.sale?.customer_document ? `CPF ${props.sale.customer_document}` : ""));
const step = (item: SaleItem, delta: number) => {
  const next = Number(item.quantity) + delta;
  if (next > 0) emit("quantity", item, next.toFixed(3));
};
/** No celular a venda é uma gaveta no rodapé: fechada mostra só total e "Pagar". */
const expanded = ref(false);
const isWeight = (item: SaleItem) => (item.unit ?? "UN") !== "UN";
/** Item e logo abaixo os serviços dele (montagem, garantia), mesmo se lançados depois. */
const ordered = computed(() => {
  const children = (id: string) => props.items.filter((i) => i.parent_item === id);
  const ids = new Set(props.items.map((i) => i.id));
  return props.items.filter((i) => !i.parent_item || !ids.has(i.parent_item)).flatMap((i) => [i, ...children(i.id)]);
});
</script>

<template>
  <aside class="order" :class="{ 'order--open': expanded }">
    <button type="button" class="sheet" :aria-expanded="expanded" @click="expanded = !expanded">
      <span><i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-up'" />
        {{ items.length }} {{ items.length === 1 ? "item" : "itens" }}</span>
      <strong>{{ money(sale?.total ?? 0) }}</strong>
    </button>
    <header class="order__head">
      <div>
        <h2>{{ sale ? `${seller ? "Pedido" : "Venda"} ${sale.number}` : seller ? "Novo pedido" : "Nova venda" }}</h2>
        <small>Balcão · {{ items.length }} {{ items.length === 1 ? "item" : "itens" }}</small>
      </div>
      <button v-if="sale" type="button" class="cancel" :disabled="busy" @click="emit('cancel')"><i class="pi pi-times-circle" /> Cancelar</button>
    </header>

    <button type="button" class="customer" :class="{ set: customerLabel }" @click="emit('customer')">
      <i :class="customerLabel ? 'pi pi-user' : 'pi pi-user-plus'" />
      <span>{{ customerLabel || "Vincular cliente (opcional)" }}</span>
      <kbd>F3</kbd>
    </button>
    <button type="button" class="customer delivery" :class="{ set: delivery }" :disabled="!sale" @click="emit('delivery')">
      <i :class="delivery ? 'pi pi-truck' : 'pi pi-shop'" />
      <span v-if="delivery">{{ delivery.table_name }} · {{ delivery.address_label }} ·
        {{ delivery.lead_days ? `${delivery.lead_days} dia(s)` : "hoje" }}</span>
      <span v-else>Retirada na loja (entregar?)</span>
      <kbd>F11</kbd>
    </button>
    <Select v-if="sellers.length" :model-value="sale?.seller ?? null" :options="sellers" option-label="name" option-value="user_id"
            show-clear filter placeholder="Vendedor (opcional)" size="small" :disabled="busy" class="seller"
            @update:model-value="emit('seller', $event ?? null)" />

    <div class="lines">
      <div v-if="!items.length" class="empty">
        <span class="empty__icon"><i class="pi pi-shopping-bag" /></span>
        <strong>A venda está vazia</strong>
        <small>Clique num produto ou leia o código de barras.</small>
      </div>
      <TransitionGroup name="row" tag="ul">
        <li v-for="item in ordered" :key="item.id" class="line" :class="{ 'line--service': item.parent_item }">
          <div class="line__top">
            <strong><i v-if="item.parent_item" class="pi pi-wrench" /> {{ item.description }}</strong>
            <span class="line__total">{{ money(item.total) }}</span>
          </div>
          <div class="line__bottom">
            <span v-if="item.parent_item" class="qty-text">Serviço · {{ quantity(item.quantity) }}×</span>
            <span v-else-if="isWeight(item)" class="qty-text">{{ quantity(item.quantity) }} {{ (item.unit ?? "").toLowerCase() }}</span>
            <span v-else class="stepper">
              <button type="button" :disabled="busy || Number(item.quantity) <= 1" aria-label="Menos um" @click="step(item, -1)">
                <i class="pi pi-minus" /></button>
              <span>{{ quantity(item.quantity) }}</span>
              <button type="button" :disabled="busy" aria-label="Mais um" @click="step(item, 1)"><i class="pi pi-plus" /></button>
            </span>
            <small>× {{ money(item.unit_price) }}<template v-if="item.promotion"> · <span class="promo">promoção</span></template></small>
            <button type="button" class="remove" :disabled="busy" aria-label="Remover item" @click="emit('remove', item)">
              <i class="pi pi-trash" /></button>
          </div>
        </li>
      </TransitionGroup>
    </div>

    <footer class="order__foot">
      <dl>
        <div><dt>Subtotal</dt><dd>{{ money(sale?.subtotal ?? 0) }}</dd></div>
        <div v-if="Number(sale?.discount)"><dt>Desconto</dt><dd class="neg">− {{ money(sale?.discount) }}</dd></div>
        <div v-if="sale?.coupon_code"><dt>Cupom {{ sale.coupon_code }}</dt><dd class="neg">− {{ money(sale.coupon_discount) }}</dd></div>
        <div v-if="Number(sale?.freight)"><dt>Frete</dt><dd>+ {{ money(sale?.freight) }}</dd></div>
      </dl>
      <div class="total"><span>Total</span><strong>{{ money(sale?.total ?? 0) }}</strong></div>
      <div class="buttons">
        <Button severity="secondary" outlined size="small" :disabled="!sale || busy" @click="emit('discount')">
          <i class="pi pi-percentage" /> Desconto <kbd>F6</kbd></Button>
        <Button severity="secondary" outlined size="small" :disabled="!sale || busy" @click="emit('coupon')">
          <i class="pi pi-ticket" /> Cupom <kbd>F7</kbd></Button>
      </div>
      <Button severity="secondary" outlined class="park" :disabled="!items.length || busy" @click="emit('park')">
        <i class="pi pi-bookmark" /> Guardar pedido <kbd>F9</kbd>
      </Button>
      <Button v-if="seller" class="pay" :disabled="!items.length || busy" @click="emit('send')">
        <i class="pi pi-send" /> Enviar ao caixa <kbd>F10</kbd>
      </Button>
      <Button v-else class="pay" :disabled="!sale || !Number(sale.total) || busy" @click="emit('pay')">
        <i class="pi pi-credit-card" /> Ir para pagamento <kbd>F10</kbd>
      </Button>
    </footer>
  </aside>
</template>

<style scoped>
.order {
  width: 380px; flex-shrink: 0; display: flex; flex-direction: column; min-height: 0;
  background: var(--surface-card); border-left: 1px solid var(--border);
}
.order__head { display: flex; align-items: flex-start; justify-content: space-between; padding: 14px 16px 10px; border-bottom: 1px solid var(--border-subtle); }
h2 { font: 800 17px/1.2 var(--font-sans); }
.order__head small { font-size: 12px; color: var(--text-muted); }
.cancel { border: 0; background: transparent; color: var(--danger-text); font: 600 12.5px/1 var(--font-sans); cursor: pointer; display: flex; gap: 5px; align-items: center; padding: 4px; }
.cancel:hover { text-decoration: underline; }
.customer {
  margin: 10px 16px 0; display: flex; align-items: center; gap: 8px; height: 38px; padding: 0 12px; border-radius: 8px; cursor: pointer;
  border: 1px dashed var(--border-strong); background: transparent; color: var(--text-body); font: 600 13px/1 var(--font-sans);
}
.customer:hover { border-color: var(--brand); color: var(--text-strong); }
.customer.set { border-style: solid; background: var(--surface-sunken); color: var(--text-strong); }
.customer span { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.seller { margin: 8px 16px 0; }
.delivery { margin-top: 8px; }
.delivery:disabled { opacity: 0.5; cursor: default; }
kbd { font: 600 10px/1 var(--font-mono); padding: 2px 5px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-muted); margin-left: 4px; }
.line--service { margin-left: 18px; border-left: 2px solid var(--brand-border); padding-left: 10px; }
.line--service strong { font-weight: 600; font-size: 13px; }
.line--service strong i { color: var(--brand); font-size: 12px; }
.park { width: 100%; justify-content: center; gap: 6px; margin-bottom: 8px; }
.lines { flex: 1; min-height: 0; overflow-y: auto; padding: 10px 16px; }
.lines ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.empty { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; text-align: center; color: var(--text-muted); }
.empty__icon { width: 52px; height: 52px; border-radius: 12px; display: grid; place-items: center; background: var(--surface-sunken); font-size: 20px; }
.empty strong { color: var(--text-strong); font-size: 14px; }
.empty small { font-size: 12.5px; }
.line { padding: 9px 10px; border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--surface-card); }
.line:hover { border-color: var(--border-strong); }
.line__top { display: flex; justify-content: space-between; gap: 8px; }
.line__top strong { font-size: 13px; color: var(--text-strong); line-height: 1.3; }
.line__total { font-weight: 800; color: var(--text-strong); white-space: nowrap; }
.line__bottom { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.line__bottom small { flex: 1; font-size: 12px; color: var(--text-muted); }
.stepper { display: inline-flex; align-items: center; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.stepper button { width: 26px; height: 24px; border: 0; background: var(--surface-sunken); color: var(--text-body); cursor: pointer; display: grid; place-items: center; }
.stepper button i { font-size: 10px; }
.stepper button:hover:enabled { background: var(--surface-hover); color: var(--text-strong); }
.stepper button:disabled { opacity: 0.4; cursor: default; }
.stepper span { min-width: 34px; text-align: center; font-weight: 700; font-size: 13px; color: var(--text-strong); }
.qty-text { font-weight: 700; font-size: 13px; color: var(--text-strong); }
.remove { border: 0; background: transparent; color: var(--text-subtle); cursor: pointer; padding: 4px; border-radius: 5px; }
.remove:hover:enabled { color: var(--danger-text); background: var(--danger-subtle); }
.order__foot { padding: 12px 16px 14px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 10px; }
dl { margin: 0; display: flex; flex-direction: column; gap: 4px; }
dl div { display: flex; justify-content: space-between; font-size: 13px; }
dt { color: var(--text-muted); }
dd { margin: 0; font-weight: 600; color: var(--text-strong); }
.neg { color: var(--danger-text); }
.total { display: flex; align-items: baseline; justify-content: space-between; }
.total span { font-size: 15px; font-weight: 700; color: var(--text-strong); }
.total strong { font: 800 2rem/1 var(--font-sans); color: var(--brand); letter-spacing: -0.02em; }
.buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.buttons :deep(.p-button) { gap: 6px; }
.pay { height: 3.2rem; font-size: 1.05rem; gap: 8px; justify-content: center; }
.pay kbd { border-color: rgba(255, 255, 255, 0.4); color: inherit; }
.promo { color: var(--accent); font-weight: 600; }
.row-enter-active { transition: all var(--dur-slow) var(--ease-spring); }
.row-leave-active { transition: all var(--dur-base) ease; }
.row-enter-from { opacity: 0; transform: translateY(-6px); background: var(--brand-subtle); }
.row-leave-to { opacity: 0; transform: translateX(16px); }
@media (max-width: 1100px) { .order { width: 340px; } }
.sheet { display: none; }
@media (max-width: 860px) {
  .order {
    position: fixed; z-index: 30; left: 0; right: 0; bottom: 0; width: auto; max-height: 85dvh; border-left: 0;
    border-radius: 14px 14px 0 0; box-shadow: 0 -10px 30px rgba(0, 0, 0, 0.25); border-top: 1px solid var(--border);
  }
  .sheet {
    display: flex; align-items: center; justify-content: space-between; height: 44px; padding: 0 16px; border: 0;
    background: transparent; color: var(--text-strong); font: 700 14px/1 var(--font-sans); cursor: pointer;
  }
  .sheet span { display: flex; align-items: center; gap: 8px; color: var(--text-muted); }
  .order:not(.order--open) > :not(.sheet):not(.order__foot) { display: none; }
  .order:not(.order--open) .order__foot > :not(.pay) { display: none; }
  .order__foot { padding-top: 8px; }
}
</style>
