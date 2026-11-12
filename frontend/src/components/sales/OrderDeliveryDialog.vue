<script setup lang="ts">
/**
 * "Alterar entrega" no pedido concluído (permissão `sales.edit_delivery`): passa para retirada
 * na loja ou escolhe outro endereço do cliente e a tabela de frete. O FRETE COBRADO NÃO MUDA —
 * a venda já está paga; a tabela e o prazo novos valem para a entrega. O motivo vai no histórico.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import SelectButton from "primevue/selectbutton";
import { computed, ref, watch } from "vue";

import { http } from "@/api/http";
import { resourceApi } from "@/api/resource";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { money } from "@/utils/format";
import { applyMask, MASKS } from "@/utils/masks";

type Address = { id: string; label: string; zip_code: string; street: string; number: string; district: string;
                 city: string; state: string; is_default?: boolean };
type FreightQuote = { table: string; table_name: string; value: string | null; lead_days: number | null; error: string };

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const v = props.ctx.values;
const customerId = (v.customer as string | null) ?? null;
const delivery = ((v.metafields ?? {}) as Record<string, unknown>)._entrega as { table: string } | undefined;

const mode = ref<"delivery" | "pickup">("delivery");
const MODES = [{ label: "Entregar", value: "delivery", icon: "pi pi-truck" }, { label: "Retirar na loja", value: "pickup", icon: "pi pi-shop" }];

const customer = useQuery({
  queryKey: ["order-delivery-customer", customerId],
  queryFn: () => resourceApi.get<{ addresses: Address[] }>("/customers/", customerId!),
  enabled: Boolean(customerId),
});
const addresses = computed(() => customer.data.value?.addresses ?? []);
const chosen = ref<string | null>((v.shipping_address as string | null) ?? null);
watch(addresses, (list) => {
  if (!list.some((a) => a.id === chosen.value)) chosen.value = (list.find((a) => a.is_default) ?? list[0])?.id ?? null;
}, { immediate: true });
const address = computed(() => addresses.value.find((a) => a.id === chosen.value) ?? null);

const quotes = useQuery({
  queryKey: computed(() => ["order-delivery-quote", address.value?.zip_code]),
  queryFn: async () => (await http.get<FreightQuote[]>("/logistics/freight-tables/quote/",
                                                      { params: { zip: address.value!.zip_code } })).data,
  enabled: computed(() => mode.value === "delivery" && (address.value?.zip_code ?? "").length === 8),
});
const table = ref<string | null>(delivery?.table ?? null);
const reason = ref("");
const saving = ref(false);

const ready = computed(() => reason.value.trim() && (mode.value === "pickup" || (address.value && table.value)));

async function save() {
  saving.value = true;
  try {
    await http.post(`/sales/${props.ctx.id}/edit-delivery/`, mode.value === "pickup"
      ? { pickup: true, reason: reason.value }
      : { address: address.value!.id, table: table.value, reason: reason.value });
    notify.success("Entrega do pedido alterada");
    emit("done");
  } catch (error) {
    notify.error(error, "Entrega não alterada");
  } finally {
    saving.value = false;
  }
}
const line = (a: Address) => [[a.street, a.number].filter(Boolean).join(", "), a.district, `${a.city}/${a.state}`]
  .filter(Boolean).join(" · ");
</script>

<template>
  <div class="odd">
    <p class="muted">O frete cobrado ({{ money(v.freight as string) }}) não muda: a venda já está paga. Diferença de frete
      se acerta à parte.</p>
    <SelectButton v-model="mode" :options="MODES" option-label="label" option-value="value" :allow-empty="false">
      <template #option="{ option }"><i :class="option.icon" /> {{ option.label }}</template>
    </SelectButton>

    <template v-if="mode === 'delivery'">
      <p v-if="!customerId" class="warn"><i class="pi pi-exclamation-triangle" /> Pedido sem cliente: para entregar, o
        endereço vem do cadastro do cliente. Só dá para marcar retirada.</p>
      <div v-else-if="customer.isPending.value" class="muted"><i class="pi pi-spin pi-spinner" /> Carregando endereços…</div>
      <template v-else>
        <h3>Endereço</h3>
        <p v-if="!addresses.length" class="muted">O cliente não tem endereço cadastrado. Cadastre no cliente e volte aqui.</p>
        <div class="opts">
          <button v-for="a in addresses" :key="a.id" type="button" class="opt" :class="{ active: chosen === a.id }"
                  @click="chosen = a.id; table = null">
            <strong>{{ a.label }}</strong><small>{{ line(a) }} · {{ applyMask(a.zip_code, MASKS.cep) }}</small>
          </button>
        </div>
        <template v-if="address">
          <h3>Tabela de frete</h3>
          <div v-if="quotes.isPending.value" class="muted"><i class="pi pi-spin pi-spinner" /> Cotando…</div>
          <div v-else class="opts">
            <button v-for="q in quotes.data.value ?? []" :key="q.table" type="button" class="opt"
                    :class="{ active: table === q.table, off: q.value === null }" :disabled="q.value === null"
                    @click="table = q.table">
              <strong>{{ q.table_name }}</strong>
              <small v-if="q.value !== null">{{ q.lead_days ? `${q.lead_days} dia(s) útil(eis)` : "No mesmo dia" }} ·
                tabela {{ Number(q.value) ? money(q.value) : "grátis" }}</small>
              <small v-else>{{ q.error }}</small>
            </button>
          </div>
        </template>
      </template>
    </template>

    <div class="field">
      <label for="odd-reason">Motivo <b class="req">*</b></label>
      <InputText id="odd-reason" v-model="reason" fluid placeholder="Ex.: cliente pediu para entregar no trabalho" />
    </div>
    <div class="odd__foot">
      <Button label="Cancelar" severity="secondary" text @click="emit('close')" />
      <Button label="Salvar entrega" icon="pi pi-check" :loading="saving" :disabled="!ready || saving" @click="save" />
    </div>
  </div>
</template>

<style scoped>
.odd { display: flex; flex-direction: column; gap: 12px; min-width: min(620px, 100%); }
.odd p { margin: 0; font-size: 13px; }
.odd h3 { margin: 4px 0 0; font: 700 13.5px/1 var(--font-sans); color: var(--text-strong); }
.warn { color: var(--warning-text); display: flex; gap: 6px; align-items: center; }
.opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(220px, 100%), 1fr)); gap: 8px; }
.opt { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; text-align: left; cursor: pointer; border-radius: 10px;
       border: 1px solid var(--border); background: var(--surface-card); font-family: var(--font-sans); color: var(--text-body); }
.opt strong { color: var(--text-strong); font-size: 13.5px; }
.opt small { font-size: 12px; color: var(--text-muted); }
.opt:hover:enabled { border-color: var(--brand-border); }
.opt.active { border-color: var(--brand); background: var(--brand-subtle); }
.opt.off { opacity: 0.6; cursor: not-allowed; border-style: dashed; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 12.5px; font-weight: 600; color: var(--text-muted); }
.req { color: var(--danger-text); }
.odd__foot { display: flex; justify-content: flex-end; gap: 8px; }
:deep(.p-togglebutton-content) { gap: 6px; }
</style>
