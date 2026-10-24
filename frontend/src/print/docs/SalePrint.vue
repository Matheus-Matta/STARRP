<script setup lang="ts">
/**
 * Comprovante da venda. Bobina 80 mm: o recibo do balcão. A4: o pedido para o
 * cliente (com dados, itens, descontos e pagamentos). Não é documento fiscal:
 * a NFC-e/NF-e sai pelo módulo fiscal.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref } from "vue";

import { resourceApi } from "@/api/resource";
import type { ColumnDef } from "@/resources/types";
import { dateTime, money, quantity } from "@/utils/format";

import PrintMeta from "../PrintMeta.vue";
import PrintShell, { type PrintFormat } from "../PrintShell.vue";
import PrintTable from "../PrintTable.vue";

type Sale = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const query = useQuery({ queryKey: ["print-sale", props.id], queryFn: () => resourceApi.get<Sale>("/sales/", props.id) });
const sale = computed(() => query.data.value);
/** Itens ativos, cada serviço (montagem, garantia) logo abaixo do item dele. */
const items = computed(() => {
  const active = (sale.value?.items ?? []).filter((i: Sale) => i.status === "active");
  const ids = new Set(active.map((i: Sale) => i.id));
  return active.filter((i: Sale) => !i.parent_item || !ids.has(i.parent_item)).flatMap((item: Sale) => [
    item,
    ...active.filter((s: Sale) => s.parent_item === item.id).map((s: Sale) => ({ ...s, description: `↳ ${s.description} (serviço)` })),
  ]);
});
const payments = computed(() => (sale.value?.payments ?? []).filter((p: Sale) => p.status === "approved"));
const STATUS: Record<string, string> = { open: "Aberta", draft: "Pedido guardado", completed: "Concluída", cancelled: "Cancelada" };
const columns: ColumnDef[] = [
  { key: "description", label: "Produto" }, { key: "sku", label: "Código" }, { key: "quantity", label: "Qtd.", type: "quantity" },
  { key: "unit_price", label: "Preço", type: "money" }, { key: "discount", label: "Desc.", type: "money" },
  { key: "total", label: "Total", type: "money" },
];
</script>

<template>
  <PrintShell v-model:format="format" :title="`Venda ${sale?.number ?? ''}`" :formats="['a4', '80mm']" :ready="!!sale"
              :store-id="sale?.store" :filename="`venda-${sale?.number ?? id}`"
              :subtitle="sale ? `${STATUS[sale.status] ?? sale.status} · ${dateTime(sale.completed_at ?? sale.created_at)}` : ''">
    <template v-if="sale" #default="{ thermal }">
      <PrintMeta :columns="3" :items="[
        ['Cliente', sale.customer_name || 'Consumidor'],
        ['CPF/CNPJ', sale.customer_document],
        ['Vendedor', sale.seller_name],
      ]" />

      <ul v-if="thermal" class="receipt">
        <li v-for="item in items" :key="item.id">
          <div class="receipt__name">{{ item.description }}</div>
          <div class="receipt__line">
            <span>{{ quantity(item.quantity) }} {{ String(item.unit).toLowerCase() }} × {{ money(item.unit_price) }}</span>
            <b>{{ money(item.total) }}</b>
          </div>
        </li>
      </ul>
      <PrintTable v-else :columns="columns" :rows="items" />

      <div class="doc-total-box">
        <div><span>Subtotal</span><span>{{ money(sale.subtotal) }}</span></div>
        <div v-if="Number(sale.discount)"><span>Desconto</span><span>− {{ money(sale.discount) }}</span></div>
        <div v-if="Number(sale.coupon_discount)"><span>Cupom {{ sale.coupon_code }}</span><span>− {{ money(sale.coupon_discount) }}</span></div>
        <div v-if="Number(sale.freight)"><span>Frete</span><span>{{ money(sale.freight) }}</span></div>
        <div><span>Total</span><span>{{ money(sale.total) }}</span></div>
      </div>

      <section class="doc-section">
        <h2>Pagamento</h2>
        <div v-for="p in payments" :key="p.id" class="pay">
          <span>{{ p.method_name }}<template v-if="p.installments > 1"> ({{ p.installments }}x)</template></span>
          <span>{{ money(p.amount) }}</span>
        </div>
        <div v-if="Number(sale.change_amount)" class="pay"><span>Troco</span><b>{{ money(sale.change_amount) }}</b></div>
        <p v-if="!payments.length" class="doc-note">Sem pagamento registrado.</p>
      </section>

      <p class="doc-note center">Comprovante sem valor fiscal. Obrigado pela preferência!</p>
      <p v-if="sale.status === 'cancelled'" class="cancelled">VENDA CANCELADA<span v-if="sale.cancel_reason"> — {{ sale.cancel_reason }}</span></p>
    </template>
  </PrintShell>
</template>

<style scoped>
.receipt { list-style: none; margin: 0; padding: 0; border-top: 1px dashed #111; }
.receipt li { padding: 3px 0; border-bottom: 1px dotted #999; }
.receipt__name { font-weight: 700; }
.receipt__line { display: flex; justify-content: space-between; font-size: 8pt; }
.pay { display: flex; justify-content: space-between; padding: 2px 0; font-size: 9pt; }
.center { text-align: center; }
.cancelled { margin: 0; padding: 6px; border: 2px solid #b91c1c; color: #b91c1c; font-weight: 700; text-align: center; }
</style>
