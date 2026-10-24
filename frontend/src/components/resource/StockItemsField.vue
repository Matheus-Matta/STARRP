<script setup lang="ts">
/**
 * Itens do documento de estoque.
 *
 * Leia o código de barras (ou de volume, ou SKU) no campo de cima: o item entra
 * na lista ou soma 1 na linha que já existe. As colunas mudam com o tipo:
 * entrada pede custo (e lote/validade, se ligado); inventário mostra o que o
 * sistema esperava; movimentação entre endereços pede origem e destino.
 * Documento confirmado fica só para leitura.
 */
import Button from "primevue/button";
import DatePicker from "primevue/datepicker";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import ToggleSwitch from "primevue/toggleswitch";
import { computed, ref } from "vue";

import { salesApi } from "@/api/sales";
import { useNotify } from "@/composables/useNotify";
import { money, quantity } from "@/utils/format";

import RelationSelect from "./RelationSelect.vue";

type Item = {
  id?: string; variant: string | null; variant_name?: string; sku?: string; quantity: string | null;
  expected_quantity?: string | null; unit_cost?: string | null; lot_number?: string; expires_at?: string | null;
  bin?: string | null; destination_bin?: string | null;
};

const props = defineProps<{ context?: Record<string, unknown> }>();
const model = defineModel<Item[]>({ default: () => [] });
const notify = useNotify();

const kind = computed(() => String(props.context?.kind ?? "entry"));
const locked = computed(() => Boolean(props.context?.id) && props.context?.status !== "draft");
const isEntry = computed(() => kind.value === "entry");
const isInventory = computed(() => kind.value === "inventory");
const isRelocation = computed(() => kind.value === "relocation");
const showLots = ref(model.value.some((i) => i.lot_number || i.expires_at));
const showBins = ref(isRelocation.value || model.value.some((i) => i.bin));
const binRelation = computed(() => ({
  endpoint: "/stock/bins/", labelKey: "code",
  params: props.context?.warehouse ? { warehouse: String(props.context.warehouse) } : undefined,
}));
const variantRelation = { endpoint: "/catalog/variants/", labelKey: "display_name", params: { is_active: "true" } };

const code = ref("");
const reading = ref(false);
const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));
const text = (v: number | null, places: number) => (v === null ? null : v.toFixed(places));

function blank(): Item {
  return { variant: null, quantity: "1.000", unit_cost: null, lot_number: "", expires_at: null, bin: null, destination_bin: null };
}

function update(index: number, patch: Partial<Item>) {
  model.value = model.value.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

function remove(index: number) {
  model.value = model.value.filter((_, i) => i !== index);
}

/** Leitor: achou a variante? soma na linha dela; senão, linha nova. */
async function read() {
  const value = code.value.trim();
  if (!value) return;
  reading.value = true;
  try {
    const found = await salesApi.lookup(value);
    const qty = Number(found.scale_quantity ?? 1);
    const index = model.value.findIndex((row) => row.variant === found.id);
    if (index >= 0) update(index, { quantity: text((num(model.value[index]!.quantity) ?? 0) + qty, 3) });
    else model.value = [...model.value, { ...blank(), variant: found.id, variant_name: found.display_name, sku: found.sku,
                                          quantity: text(qty, 3) }];
    code.value = "";
  } catch (error) {
    notify.error(error, "Código não encontrado");
  } finally {
    reading.value = false;
  }
}

const totals = computed(() => ({
  quantity: model.value.reduce((sum, row) => sum + (num(row.quantity) ?? 0), 0),
  cost: model.value.reduce((sum, row) => sum + (num(row.quantity) ?? 0) * (num(row.unit_cost) ?? 0), 0),
}));
</script>

<template>
  <div class="items">
    <div v-if="!locked" class="items__bar">
      <span class="scan">
        <i class="pi pi-barcode" />
        <InputText v-model="code" placeholder="Leia o código de barras, de volume ou SKU e tecle Enter" size="small" fluid
                   :disabled="reading" @keydown.enter.prevent="read" />
      </span>
      <label v-if="isEntry" class="toggle"><ToggleSwitch v-model="showLots" /> Lote e validade</label>
      <label class="toggle"><ToggleSwitch v-model="showBins" /> Endereços</label>
      <Button label="Linha" icon="pi pi-plus" size="small" severity="secondary" outlined @click="model = [...model, blank()]" />
    </div>

    <div class="table" role="table">
      <div class="row head" role="row" :class="{ lots: showLots && isEntry, bins: showBins, cost: isEntry }">
        <span>Produto</span>
        <span v-if="isInventory" class="right">Sistema</span>
        <span class="right">{{ isInventory ? "Contado" : kind === "adjustment" ? "Diferença (±)" : "Quantidade" }}</span>
        <span v-if="isEntry" class="right">Custo unit.</span>
        <template v-if="showLots && isEntry"><span>Lote</span><span>Validade</span></template>
        <template v-if="showBins"><span>{{ isRelocation ? "De" : "Endereço" }}</span><span v-if="isRelocation">Para</span></template>
        <span />
      </div>
      <p v-if="!model.length" class="empty muted">Nenhum item. Leia um código acima ou adicione uma linha.</p>
      <div v-for="(row, index) in model" :key="row.id ?? index" class="row" role="row"
           :class="{ lots: showLots && isEntry, bins: showBins, cost: isEntry }">
        <RelationSelect v-if="!locked" :model-value="row.variant" :relation="variantRelation" placeholder="Produto"
                        @update:model-value="update(index, { variant: $event as string })" />
        <span v-else class="name">{{ row.variant_name }} <small>{{ row.sku }}</small></span>
        <span v-if="isInventory" class="right muted">{{ row.expected_quantity == null ? "—" : quantity(row.expected_quantity) }}</span>
        <InputNumber :model-value="num(row.quantity)" :disabled="locked" :min-fraction-digits="0" :max-fraction-digits="3"
                     locale="pt-BR" size="small" fluid input-class="right"
                     @update:model-value="update(index, { quantity: text($event, 3) })" />
        <InputNumber v-if="isEntry" :model-value="num(row.unit_cost)" :disabled="locked" mode="currency" currency="BRL"
                     locale="pt-BR" :max-fraction-digits="4" size="small" fluid input-class="right"
                     @update:model-value="update(index, { unit_cost: text($event, 4) })" />
        <template v-if="showLots && isEntry">
          <InputText :model-value="row.lot_number" :disabled="locked" size="small" placeholder="Lote" fluid
                     @update:model-value="update(index, { lot_number: String($event ?? '') })" />
          <DatePicker :model-value="row.expires_at ? new Date(`${row.expires_at}T00:00:00`) : null" :disabled="locked"
                      date-format="dd/mm/yy" size="small" fluid placeholder="Validade"
                      @update:model-value="update(index, { expires_at: $event ? ($event as Date).toLocaleDateString('sv-SE') : null })" />
        </template>
        <template v-if="showBins">
          <RelationSelect :model-value="row.bin" :relation="binRelation" placeholder="Endereço"
                          @update:model-value="update(index, { bin: $event as string })" />
          <RelationSelect v-if="isRelocation" :model-value="row.destination_bin" :relation="binRelation" placeholder="Destino"
                          @update:model-value="update(index, { destination_bin: $event as string })" />
        </template>
        <Button v-if="!locked" icon="pi pi-trash" text rounded size="small" severity="danger" aria-label="Remover item"
                @click="remove(index)" />
        <span v-else />
      </div>
    </div>
    <div v-if="model.length" class="items__foot">
      <span>{{ model.length }} {{ model.length === 1 ? "item" : "itens" }} · {{ quantity(totals.quantity) }} un.</span>
      <strong v-if="isEntry">Total {{ money(totals.cost) }}</strong>
    </div>
  </div>
</template>

<style scoped>
.items { display: flex; flex-direction: column; gap: 0.6rem; }
.items__bar { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.scan { flex: 1 1 320px; display: flex; align-items: center; gap: 0.5rem; }
.scan i { color: var(--text-muted); }
.toggle { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 12.5px; color: var(--text-body); cursor: pointer; }
.table { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.row {
  display: grid; gap: 0.5rem; align-items: center; padding: 6px 10px; border-top: 1px solid var(--border-subtle);
  grid-template-columns: minmax(220px, 3fr) minmax(110px, 1fr) 40px;
}
.row.cost { grid-template-columns: minmax(220px, 3fr) minmax(110px, 1fr) minmax(120px, 1fr) 40px; }
.row.cost.lots { grid-template-columns: minmax(220px, 3fr) minmax(110px, 1fr) minmax(120px, 1fr) minmax(100px, 1fr) minmax(130px, 1fr) 40px; }
.row.bins { grid-template-columns: minmax(220px, 3fr) minmax(110px, 1fr) minmax(150px, 1fr) minmax(150px, 1fr) 40px; }
.row.cost.bins { grid-template-columns: minmax(220px, 3fr) minmax(110px, 1fr) minmax(120px, 1fr) minmax(150px, 1fr) 40px; }
.row.cost.lots.bins { grid-template-columns: minmax(200px, 3fr) 110px 120px 100px 130px 150px 40px; }
.head { border-top: 0; background: var(--surface-sunken); font: 650 11.5px/1.3 var(--font-sans); letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted); }
.right { text-align: right; }
:deep(.right) { text-align: right; }
.name { font-weight: 600; color: var(--text-strong); }
.name small { margin-left: 6px; font-weight: 500; color: var(--text-muted); }
.empty { margin: 0; padding: 14px; text-align: center; font-size: 13px; }
.items__foot { display: flex; justify-content: space-between; font-size: 13px; color: var(--text-muted); }
.items__foot strong { color: var(--text-strong); }
@media (max-width: 900px) { .table { overflow-x: auto; } .row { min-width: 760px; } }
</style>
