<script setup lang="ts">
/**
 * Entrega DENTRO do PDV: o endereço do cliente da venda (ou um novo, cadastrado aqui
 * e já guardado no cliente) e a cotação de TODAS as tabelas de frete ativas para o CEP
 * dele — cada uma com valor e prazo; as que não atendem dizem por quê. Escolher uma
 * lança o frete no total. "Retirar na loja" tira a entrega.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import Button from "primevue/button";
import { computed, ref, watch } from "vue";

import { http } from "@/api/http";
import { resourceApi } from "@/api/resource";
import type { Sale } from "@/api/types";
import AddressListField, { type Address } from "@/components/resource/AddressListField.vue";
import { useNotify } from "@/composables/useNotify";
import { money } from "@/utils/format";
import { applyMask, MASKS } from "@/utils/masks";

type FreightQuote = { table: string; table_name: string; value: string | null; lead_days: number | null; detail: string;
                      error: string; distance_km: string | null };

const props = defineProps<{ sale: Sale | null; busy: boolean }>();
const emit = defineEmits<{ apply: [address: string, table: string]; pickup: []; customer: []; back: [] }>();
const notify = useNotify();
const client = useQueryClient();

const customerId = computed(() => (props.sale?.customer as string | null) ?? null);
const customer = useQuery({
  queryKey: computed(() => ["pdv-delivery-customer", customerId.value]),
  queryFn: () => resourceApi.get<{ id: string; name: string; addresses: Address[] }>("/customers/", customerId.value!),
  enabled: computed(() => Boolean(customerId.value)),
});
const addresses = computed(() => customer.data.value?.addresses ?? []);
const chosen = ref<string | null>(null);
watch([addresses, () => props.sale?.shipping_address], () => {
  const current = props.sale?.shipping_address as string | null;
  if (current && addresses.value.some((a) => a.id === current)) chosen.value = current;
  else if (!addresses.value.some((a) => a.id === chosen.value)) {
    chosen.value = (addresses.value.find((a) => a.is_default) ?? addresses.value[0])?.id ?? null;
  }
}, { immediate: true });
const address = computed(() => addresses.value.find((a) => a.id === chosen.value) ?? null);

const quotes = useQuery({
  queryKey: computed(() => ["pdv-freight", address.value?.zip_code]),
  queryFn: async () => (await http.get<FreightQuote[]>("/logistics/freight-tables/quote/",
                                                      { params: { zip: address.value!.zip_code } })).data,
  enabled: computed(() => (address.value?.zip_code ?? "").length === 8),
  staleTime: 60_000,
});
const delivery = computed(() => ((props.sale?.metafields ?? {}) as Record<string, unknown>)._entrega as
  { table: string } | undefined);

/* Endereço novo: o mesmo editor do cadastro, guardado no cliente ao confirmar. */
const adding = ref<Address[] | null>(null);
const saving = ref(false);
function startNew() {
  adding.value = [{ label: addresses.value.length ? "" : "Casa", zip_code: "", street: "", number: "", complement: "",
                    district: "", city: "", state: "", reference: "", is_default: !addresses.value.length }];
}
async function saveNew() {
  const row = adding.value?.[0];
  if (!row || row.zip_code.length !== 8 || !row.street || !row.number) {
    notify.error(new Error("Preencha CEP, logradouro e número."), "Endereço incompleto");
    return;
  }
  saving.value = true;
  try {
    const saved = await resourceApi.update<{ addresses: Address[] }>("/customers/", customerId.value!, {
      addresses: [...addresses.value.map((a) => ({ ...a, is_default: row.is_default ? false : a.is_default })), row],
    });
    client.setQueryData(["pdv-delivery-customer", customerId.value], saved);
    const fresh = saved.addresses.find((a) => a.zip_code === row.zip_code && a.street === row.street && a.number === row.number);
    chosen.value = fresh?.id ?? chosen.value;
    adding.value = null;
  } catch (error) {
    notify.error(error, "Endereço não salvo");
  } finally {
    saving.value = false;
  }
}

const line = (a: Address) => [[a.street, a.number].filter(Boolean).join(", "), a.complement].filter(Boolean).join(" · ");
const place = (a: Address) => [a.district, [a.city, a.state].filter(Boolean).join(" - ")].filter(Boolean).join(" · ");
</script>

<template>
  <section class="panel">
    <header class="panel__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para a venda" @click="emit('back')" />
      <div>
        <h2>Entrega</h2>
        <p>{{ sale?.customer_name ? `Para ${sale.customer_name}` : "Escolha o endereço e a forma de entrega." }}</p>
      </div>
      <Button label="Retirar na loja" icon="pi pi-shop" severity="secondary" outlined class="pickup"
              :disabled="busy || !sale?.shipping_address" @click="emit('pickup')" />
    </header>

    <div v-if="!customerId" class="empty">
      <i class="pi pi-user" />
      <p>Para entregar, identifique o cliente da venda (o endereço fica no cadastro dele).</p>
      <Button label="Escolher cliente (F3)" icon="pi pi-user-plus" @click="emit('customer')" />
    </div>

    <template v-else>
      <h3 class="step"><span>1</span> Endereço</h3>
      <div v-if="customer.isPending.value" class="muted"><i class="pi pi-spin pi-spinner" /> Carregando os endereços…</div>
      <div v-else class="addrs" role="radiogroup" aria-label="Endereço de entrega">
        <button v-for="a in addresses" :key="a.id" type="button" class="addr" role="radio" :aria-checked="chosen === a.id"
                :class="{ active: chosen === a.id }" @click="chosen = a.id ?? null">
          <span class="addr__top"><i :class="chosen === a.id ? 'pi pi-check-circle' : 'pi pi-map-marker'" />
            <strong>{{ a.label }}</strong><small v-if="a.is_default" class="star">★ padrão</small></span>
          <span class="addr__line">{{ line(a) || "Sem logradouro" }}</span>
          <span class="addr__place">{{ place(a) }} · {{ applyMask(a.zip_code, MASKS.cep) }}</span>
          <small v-if="a.reference" class="addr__ref">Ref.: {{ a.reference }}</small>
        </button>
        <button v-if="!adding" type="button" class="addr addr--new" @click="startNew">
          <i class="pi pi-plus" /> <strong>Novo endereço</strong><small>Fica guardado no cadastro do cliente</small>
        </button>
      </div>
      <div v-if="adding" class="new">
        <AddressListField v-model="adding" />
        <div class="new__actions">
          <Button label="Cancelar" severity="secondary" text @click="adding = null" />
          <Button label="Salvar endereço" icon="pi pi-check" :loading="saving" @click="saveNew" />
        </div>
      </div>

      <template v-if="address">
        <h3 class="step"><span>2</span> Frete para {{ applyMask(address.zip_code, MASKS.cep) }}</h3>
        <div v-if="quotes.isPending.value" class="muted"><i class="pi pi-spin pi-spinner" /> Cotando as tabelas de frete…</div>
        <p v-else-if="!quotes.data.value?.length" class="muted">
          Nenhuma tabela de frete ativa. Cadastre em <b>Configurações → Tabelas de frete</b>.
        </p>
        <div v-else class="quotes">
          <button v-for="q in quotes.data.value" :key="q.table" type="button" class="quote"
                  :class="{ off: q.value === null, active: delivery?.table === q.table && sale?.shipping_address === address.id }"
                  :disabled="q.value === null || busy" @click="emit('apply', address.id!, q.table)">
            <span class="quote__name"><i class="pi pi-truck" /> {{ q.table_name }}</span>
            <strong v-if="q.value !== null" class="quote__value">{{ Number(q.value) ? money(q.value) : "Grátis" }}</strong>
            <span v-if="q.value !== null" class="quote__days">
              {{ q.lead_days === 0 ? "No mesmo dia" : `${q.lead_days} dia(s) útil(eis)` }}<template v-if="q.detail"> · {{ q.detail }}</template>
            </span>
            <span v-else class="quote__error"><i class="pi pi-ban" /> {{ q.error }}</span>
          </button>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 12px; overflow-y: auto; }
.panel__head { display: flex; align-items: center; gap: 10px; }
.panel__head h2 { margin: 0; font: 700 17px/1.2 var(--font-sans); color: var(--text-strong); }
.panel__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.pickup { margin-left: auto; }
.step { margin: 6px 0 0; display: flex; align-items: center; gap: 8px; font: 700 14px/1 var(--font-sans); color: var(--text-strong); }
.step span { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; background: var(--brand-subtle);
             color: var(--text-brand); font-size: 12px; }
.muted { color: var(--text-muted); font-size: 13px; display: flex; gap: 6px; align-items: center; margin: 0; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 12px; text-align: center; color: var(--text-muted); }
.empty i { font-size: 2rem; }
.addrs, .quotes { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; }
.addr, .quote {
  display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; text-align: left; cursor: pointer; min-width: 0;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); font-family: var(--font-sans);
  transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease;
}
.addr:hover, .quote:hover:enabled { border-color: var(--brand-border); }
.addr.active, .quote.active { border-color: var(--brand); background: var(--brand-subtle); }
.addr__top { display: flex; align-items: center; gap: 6px; color: var(--text-strong); }
.addr__top i { color: var(--brand); }
.star { margin-left: auto; color: var(--warning-text); font-weight: 600; }
.addr__line, .addr__place { font-size: 12.5px; color: var(--text-body); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.addr__place { color: var(--text-muted); }
.addr__ref { font-size: 12px; color: var(--text-muted); }
.addr--new { border-style: dashed; justify-content: center; align-items: center; color: var(--text-brand); text-align: center; }
.addr--new small { color: var(--text-muted); }
.new { padding: 10px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-sunken); }
.new__actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.new :deep(.add), .new :deep(.empty) { display: none; }
.quote__name { display: flex; gap: 6px; align-items: center; font-weight: 700; font-size: 13.5px; color: var(--text-strong); }
.quote__name i { color: var(--brand); }
.quote__value { font: 800 20px/1.1 var(--font-sans); color: var(--text-strong); }
.quote__days { font-size: 12px; color: var(--text-muted); }
.quote.off { opacity: 0.6; cursor: not-allowed; border-style: dashed; }
.quote__error { font-size: 12px; color: var(--text-muted); display: flex; gap: 6px; }
</style>
