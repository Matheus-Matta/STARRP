<script setup lang="ts">
/** Devolve itens de uma venda concluída e conclui o reembolso na mesma tela. */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import Textarea from "primevue/textarea";
import { computed, reactive, ref } from "vue";

import { http } from "@/api/http";
import { resourceApi } from "@/api/resource";
import { ApprovalCancelled, withApproval } from "@/composables/useApproval";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { money, quantity } from "@/utils/format";

type Item = { id: string; description: string; sku?: string; quantity: string; total: string; status: string };
type ReturnRow = { status: string; items: { sale_item: string; quantity: string }[] };

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const sale = props.ctx.values;
const items = computed(() => ((sale.items ?? []) as Item[]).filter((item) => item.status === "active"));

const previous = useQuery({
  queryKey: ["sale-returns", props.ctx.id],
  queryFn: () => resourceApi.list<ReturnRow>("/returns/", {
    sale: props.ctx.id, status: "completed", page_size: 100,
  }),
});
const returned = computed(() => {
  const out: Record<string, number> = {};
  for (const saleReturn of previous.data.value?.results ?? []) {
    for (const item of saleReturn.items) out[item.sale_item] = (out[item.sale_item] ?? 0) + Number(item.quantity);
  }
  return out;
});
const available = (item: Item) => Math.max(Number(item.quantity) - (returned.value[item.id] ?? 0), 0);

const qty = reactive<Record<string, number | null>>({});
const restock = reactive<Record<string, boolean>>({});
const selected = computed(() => items.value
  .filter((item) => Number(qty[item.id] ?? 0) > 0 && Number(qty[item.id]) <= available(item))
  .map((item) => ({ sale_item: item.id, quantity: Number(qty[item.id]).toFixed(3), restock: restock[item.id] !== false })));

const methods = computed(() => [
  { label: "Crédito na carteira do cliente", value: "store_credit", disabled: !sale.customer || !sale.store_credit_refund_allowed,
    hint: !sale.customer ? "O pedido não tem cliente identificado" : !sale.store_credit_refund_allowed ? "Desligado na regra da filial" : "Para usar em compras futuras" },
  { label: "Estorno na forma original", value: "original_payment", hint: "Registre também na maquininha ou no banco" },
  { label: "Dinheiro do caixa", value: "cash", hint: "Exige caixa aberto e saldo suficiente na gaveta" },
]);
const refundMethod = ref(methods.value.find((method) => !method.disabled)?.value ?? "original_payment");
const reason = ref("");
const saving = ref(false);
const createdId = ref<string | null>(null);
const locked = computed(() => Boolean(createdId.value));
const ready = computed(() => selected.value.length > 0 && reason.value.trim().length > 0 && !previous.isPending.value);

async function save() {
  saving.value = true;
  try {
    if (!createdId.value) {
      const created = await withApproval((approval) => http.post<{ id: string }>(`/sales/${props.ctx.id}/returns/`, {
        items: selected.value, refund_method: refundMethod.value, reason: reason.value.trim(), approval,
      }));
      createdId.value = created.data.id;
    }
    await http.post(`/returns/${createdId.value}/complete/`, {});
    notify.success("Devolução concluída", refundMethod.value === "store_credit"
      ? "O valor entrou na carteira do cliente." : "Estoque, comissão e reembolso foram registrados.");
    emit("done");
  } catch (error) {
    if (!(error instanceof ApprovalCancelled)) notify.error(error, createdId.value ? "Reembolso não concluído" : "Devolução não criada");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="ret">
    <p class="muted">Informe o que voltou. O crédito usa o valor efetivamente pago, com os descontos da venda.</p>
    <div v-if="previous.isPending.value" class="loading"><i class="pi pi-spin pi-spinner" /> Conferindo devoluções anteriores…</div>
    <div v-else class="items">
      <div v-for="item in items" :key="item.id" class="item" :class="{ off: available(item) <= 0 }">
        <div class="item__name">
          <strong>{{ item.description }}</strong>
          <small>{{ item.sku || "Sem SKU" }} · vendido {{ quantity(item.quantity) }} · {{ money(item.total) }}</small>
          <small v-if="available(item) < Number(item.quantity)">Já devolvido: {{ quantity(Number(item.quantity) - available(item)) }}</small>
        </div>
        <label>
          <span>Quantidade</span>
          <InputNumber v-model="qty[item.id]" :min="0" :max="available(item)" :min-fraction-digits="0" :max-fraction-digits="3"
              :disabled="available(item) <= 0 || saving || locked" show-buttons button-layout="horizontal" input-class="qty-input" />
        </label>
        <label class="check">
          <Checkbox :model-value="restock[item.id] !== false" binary :disabled="available(item) <= 0 || saving || locked"
                    @update:model-value="restock[item.id] = Boolean($event)" />
          <span>Volta ao estoque</span>
        </label>
      </div>
      <p v-if="!items.some((item) => available(item) > 0)" class="empty">Todos os itens desta venda já foram devolvidos.</p>
    </div>

    <div class="field">
      <label for="ret-method">Como reembolsar</label>
      <Select v-model="refundMethod" input-id="ret-method" :options="methods" option-label="label" option-value="value"
              :option-disabled="(option) => option.disabled" fluid :disabled="saving || locked">
        <template #option="{ option }">
          <span class="method"><strong>{{ option.label }}</strong><small>{{ option.hint }}</small></span>
        </template>
      </Select>
      <small v-if="refundMethod === 'store_credit'" class="credit"><i class="pi pi-wallet" /> O saldo ficará disponível na carteira do cliente assim que concluir.</small>
    </div>
    <div class="field">
      <label for="ret-reason">Motivo <b>*</b></label>
      <Textarea id="ret-reason" v-model="reason" rows="2" auto-resize fluid :disabled="saving || locked"
                placeholder="Ex.: tamanho não serviu" />
    </div>
    <p v-if="createdId" class="warn"><i class="pi pi-info-circle" /> A devolução foi criada. Corrija o impedimento e tente concluir novamente.</p>
    <div class="ret__foot">
      <Button label="Cancelar" severity="secondary" text :disabled="saving" @click="emit('close')" />
      <Button :label="createdId ? 'Tentar concluir novamente' : 'Concluir devolução'" icon="pi pi-replay" :loading="saving"
              :disabled="!ready || saving" @click="save" />
    </div>
  </div>
</template>

<style scoped>
.ret { display: flex; flex-direction: column; gap: 12px; min-width: min(680px, 100%); }
.ret p { margin: 0; font-size: 13px; }
.loading, .empty { padding: 18px; text-align: center; color: var(--text-muted); }
.items { display: flex; max-height: min(360px, 48vh); flex-direction: column; overflow-y: auto; border: 1px solid var(--border); border-radius: 10px; }
.item { display: grid; grid-template-columns: minmax(180px, 1fr) 170px 135px; align-items: center; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); }
.item:last-child { border-bottom: 0; }
.item.off { opacity: 0.55; }
.item__name { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.item__name strong { overflow: hidden; color: var(--text-strong); font-size: 13.5px; text-overflow: ellipsis; white-space: nowrap; }
.item__name small, .method small { color: var(--text-muted); font-size: 12px; }
.item label, .field { display: flex; flex-direction: column; gap: 4px; }
.item label > span, .field > label { color: var(--text-muted); font-size: 12.5px; font-weight: 600; }
.check { flex-direction: row !important; align-items: center; }
.method { display: flex; flex-direction: column; gap: 2px; }
.credit { display: flex; align-items: center; gap: 5px; color: var(--brand-text); }
.field b { color: var(--danger-text); }
.warn { display: flex; align-items: center; gap: 6px; color: var(--warning-text); }
.ret__foot { display: flex; justify-content: flex-end; gap: 8px; }
:deep(.qty-input) { width: 76px; text-align: center; }
@media (max-width: 640px) { .item { grid-template-columns: 1fr 160px; } .check { grid-column: 1 / -1; } }
</style>
