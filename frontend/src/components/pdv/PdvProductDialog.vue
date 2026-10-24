<script setup lang="ts">
/**
 * Vitrine do produto no PDV, no formato de página de produto da loja virtual:
 * galeria (fotos do produto + da variante escolhida) · nome, preço e saldo ·
 * um botão por valor de cada eixo da grade (Cor, Tamanho) · quantidade (kg na
 * balança) · serviços oferecidos (montagem, garantia) · descrição e ficha técnica.
 *
 * Combinação que não existe fica desabilitada; sem saldo fica tracejada (o
 * backend decide se vende sem estoque). Enter adiciona ao pedido.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputNumber from "primevue/inputnumber";
import Tab from "primevue/tab";
import TabList from "primevue/tablist";
import TabPanel from "primevue/tabpanel";
import TabPanels from "primevue/tabpanels";
import Tabs from "primevue/tabs";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { PdvProductView } from "@/api/types";
import { money, quantity as qty } from "@/utils/format";

type Variant = PdvProductView["variants"][number];

const props = defineProps<{ product: PdvProductView | null; busy: boolean }>();
const emit = defineEmits<{ confirm: [variant: string, quantity: string, services: string[]]; close: [] }>();

const selected = ref<Record<string, string>>({});
const pickedVariant = ref<string | null>(null); // variantes sem grade (nomes soltos)
const amount = ref<number | null>(1);
const services = ref<string[]>([]);
const image = ref(0);
const tab = ref("details");

const p = computed(() => props.product);
const byWeight = computed(() => p.value?.sale_method === "weight");
const fractional = computed(() => byWeight.value || (p.value?.unit ?? "UN") !== "UN");
const hasAxes = computed(() => Boolean(p.value?.axes.length));

const variant = computed<Variant | null>(() => {
  const product = p.value;
  if (!product) return null;
  if (!hasAxes.value) return product.variants.find((v) => v.id === pickedVariant.value) ?? null;
  return product.variants.find((v) => product.axes.every((a) => v.options[a.id] === selected.value[a.id])) ?? null;
});

/** Variantes que ainda casam se o valor `valueId` do eixo `axisId` for escolhido. */
function candidates(axisId: string, valueId: string) {
  return (p.value?.variants ?? []).filter((v) => v.options[axisId] === valueId && (p.value?.axes ?? [])
    .every((a) => a.id === axisId || !selected.value[a.id] || v.options[a.id] === selected.value[a.id]));
}
const exists = (axisId: string, valueId: string) => candidates(axisId, valueId).length > 0;
const inStock = (v: Variant) => v.stock === null || Number(v.stock) > 0;
const available = (axisId: string, valueId: string) => candidates(axisId, valueId).some(inStock);

function choose(axisId: string, valueId: string) {
  selected.value = { ...selected.value, [axisId]: valueId };
  // Combinação inexistente com o resto: ajusta os outros eixos para a 1ª que existe.
  if (!variant.value) {
    const match = (p.value?.variants ?? []).find((v) => v.options[axisId] === valueId && inStock(v))
      ?? (p.value?.variants ?? []).find((v) => v.options[axisId] === valueId);
    if (match) selected.value = { ...match.options };
  }
}

const gallery = computed(() => {
  const own = variant.value?.images ?? [];
  return [...own, ...(p.value?.images ?? []).filter((url) => !own.includes(url))];
});
watch(() => variant.value?.id, () => (image.value = 0));

watch(() => props.product, async (product) => {
  if (!product) return;
  const start = product.variants.find((v) => v.is_default && inStock(v)) ?? product.variants.find(inStock) ?? product.variants[0];
  selected.value = start ? { ...start.options } : {};
  pickedVariant.value = !product.axes.length && product.variants.length > 1 ? null : start?.id ?? null;
  amount.value = product.sale_method === "weight" ? null : 1;
  services.value = [];
  image.value = 0;
  tab.value = "details";
  await nextTick();
  // O foco sai da busca do catálogo (atrás do modal): senão o Enter/leitor iria para ela.
  document.getElementById(product.sale_method === "weight" ? "pdv-view-qty" : "pdv-view-add")?.focus();
});

/** Enter adiciona de qualquer lugar enquanto a vitrine está aberta (mesmo com o foco num
 *  botão de cor/serviço — Espaço marca). Captura antes da busca e dos atalhos do PDV. */
function onEnter(event: KeyboardEvent) {
  if (!props.product || event.key !== "Enter" || event.isComposing) return;
  event.preventDefault();
  event.stopPropagation();
  confirm();
}
onMounted(() => window.addEventListener("keydown", onEnter, true));
onBeforeUnmount(() => window.removeEventListener("keydown", onEnter, true));

const unitPrice = computed(() => Number(variant.value?.current_price ?? 0));
const servicesTotal = computed(() => (p.value?.services ?? [])
  .filter((s) => services.value.includes(s.variant)).reduce((sum, s) => sum + Number(s.price), 0));
const total = computed(() => (amount.value ?? 0) * (unitPrice.value + (byWeight.value ? 0 : servicesTotal.value))
  + (byWeight.value ? servicesTotal.value : 0));

const missing = computed(() => {
  if (!variant.value) return hasAxes.value ? `Escolha ${p.value!.axes.filter((a) => !selected.value[a.id]).map((a) => a.name.toLowerCase()).join(" e ") || "a combinação"}.` : "Escolha a variação.";
  if (!amount.value || amount.value <= 0) return byWeight.value ? "Informe o peso." : "Informe a quantidade.";
  return "";
});

function step(delta: number) {
  amount.value = Math.max(1, (amount.value ?? 0) + delta);
}
function toggle(id: string) {
  services.value = services.value.includes(id) ? services.value.filter((s) => s !== id) : [...services.value, id];
}
function confirm() {
  if (missing.value || props.busy) return;
  emit("confirm", variant.value!.id, amount.value!.toFixed(3), services.value);
}

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const specs = computed(() => [
  ...(p.value?.specs ?? []).map((s) => [s.label, s.text]),
  ["SKU", variant.value?.sku], ["Código de barras", variant.value?.barcode], ["Referência", p.value?.reference],
  ["Categoria", p.value?.category_name], ["Marca", p.value?.brand_name], ["Unidade", p.value?.unit],
  ["Variações", p.value && p.value.variants.length > 1 ? String(p.value.variants.length) : ""],
].filter(([, v]) => v) as [string, string][]);
</script>

<template>
  <Dialog :visible="product !== null" modal :header="undefined" :show-header="false" class="pv-dialog"
          :style="{ width: 'min(1120px, 96vw)' }" :breakpoints="{ '820px': '100vw' }" dismissable-mask
          @update:visible="emit('close')">
    <form v-if="p" class="pv" @submit.prevent="confirm" @keydown.esc="emit('close')">
      <button type="button" class="pv__close" aria-label="Fechar (Esc)" @click="emit('close')"><i class="pi pi-times" /></button>

      <div class="pv__top">
        <!-- Galeria -->
        <div class="gallery">
          <div v-if="gallery.length > 1" class="thumbs" role="tablist" aria-label="Fotos">
            <button v-for="(url, i) in gallery" :key="url" type="button" class="thumb" :class="{ active: i === image }"
                    role="tab" :aria-selected="i === image" @click="image = i">
              <img :src="url" alt="" loading="lazy" />
            </button>
          </div>
          <div class="stage">
            <img v-if="gallery.length" :src="gallery[image]" :alt="p.name" />
            <span v-else class="stage__empty">{{ initials(p.name) }}</span>
          </div>
        </div>

        <!-- Compra -->
        <div class="buy">
          <small class="crumb">{{ [p.category_name, p.brand_name].filter(Boolean).join(" · ") || "Produto" }}</small>
          <h2>{{ p.name }}</h2>
          <div class="price-row">
            <strong class="price">{{ money(unitPrice) }}<small v-if="byWeight"> / kg</small></strong>
            <s v-if="variant && Number(variant.price) > unitPrice" class="was">{{ money(variant.price) }}</s>
            <span v-if="variant && variant.stock !== null" class="stock" :class="{ out: Number(variant.stock) <= 0 }">
              <i :class="Number(variant.stock) > 0 ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'" />
              {{ Number(variant.stock) > 0 ? `${qty(variant.stock)} em estoque` : "Sem estoque" }}
            </span>
          </div>
          <small v-if="variant" class="sku">SKU {{ variant.sku }}</small>

          <div v-for="axis in p.axes" :key="axis.id" class="axis">
            <span class="axis__label">{{ axis.name }}<b v-if="selected[axis.id]">: {{ axis.values.find((v) => v.id === selected[axis.id])?.value }}</b></span>
            <div class="chips">
              <button v-for="value in axis.values" :key="value.id" type="button" class="chip"
                      :class="{ active: selected[axis.id] === value.id, out: !available(axis.id, value.id),
                                faded: !exists(axis.id, value.id) }"
                      :disabled="!p.variants.some((v) => v.options[axis.id] === value.id)"
                      :title="!exists(axis.id, value.id) ? 'Não existe com a escolha atual' : available(axis.id, value.id) ? undefined : 'Sem estoque'"
                      @click="choose(axis.id, value.id)">
                {{ value.value }}
              </button>
            </div>
          </div>
          <div v-if="!hasAxes && p.variants.length > 1" class="axis">
            <span class="axis__label">Variação</span>
            <div class="chips">
              <button v-for="v in p.variants" :key="v.id" type="button" class="chip"
                      :class="{ active: pickedVariant === v.id, out: !inStock(v) }" @click="pickedVariant = v.id">
                {{ v.name }}
              </button>
            </div>
          </div>

          <div class="axis">
            <label class="axis__label" for="pdv-view-qty">{{ byWeight ? "Peso (kg)" : fractional ? `Quantidade (${p.unit.toLowerCase()})` : "Quantidade" }}</label>
            <InputNumber v-if="fractional" v-model="amount" input-id="pdv-view-qty" :min-fraction-digits="byWeight ? 3 : 2"
                         :max-fraction-digits="3" :min="0" locale="pt-BR" class="qty-input" placeholder="0,000" />
            <span v-else class="stepper">
              <button type="button" aria-label="Menos um" :disabled="(amount ?? 1) <= 1" @click="step(-1)"><i class="pi pi-minus" /></button>
              <InputNumber v-model="amount" input-id="pdv-view-qty" :min="1" :use-grouping="false" />
              <button type="button" aria-label="Mais um" @click="step(1)"><i class="pi pi-plus" /></button>
            </span>
          </div>

          <div v-if="p.services.length" class="axis">
            <span class="axis__label">Serviços</span>
            <div class="services">
              <button v-for="s in p.services" :key="s.variant" type="button" class="service" role="checkbox"
                      :aria-checked="services.includes(s.variant)" :class="{ active: services.includes(s.variant) }"
                      @click="toggle(s.variant)">
                <i :class="services.includes(s.variant) ? 'pi pi-check-square' : 'pi pi-stop'" />
                <span class="service__text"><strong>{{ s.name }}</strong><small v-if="s.description">{{ s.description }}</small></span>
                <span class="service__price">+ {{ money(s.price) }}</span>
              </button>
            </div>
          </div>

          <div class="cta">
            <div class="cta__total"><span>Total</span><strong>{{ money(total) }}</strong></div>
            <Button id="pdv-view-add" type="submit" :loading="busy" :disabled="!!missing" class="cta__btn">
              <i class="pi pi-shopping-cart" /> Adicionar ao pedido <kbd>Enter</kbd>
            </Button>
          </div>
          <small v-if="missing" class="hint"><i class="pi pi-info-circle" /> {{ missing }}</small>
        </div>
      </div>

      <Tabs v-model:value="tab" class="pv__tabs">
        <TabList>
          <Tab value="details">Detalhes</Tab>
          <Tab value="specs">Ficha técnica</Tab>
          <Tab v-if="p.services.length" value="services">Serviços</Tab>
        </TabList>
        <TabPanels>
          <TabPanel value="details">
            <!-- eslint-disable-next-line vue/no-v-html -- HTML limpo no backend (core/text.clean_html) -->
            <div v-if="p.description" class="rich" v-html="p.description" />
            <p v-else class="muted">Sem descrição cadastrada.</p>
          </TabPanel>
          <TabPanel value="specs">
            <dl class="specs"><template v-for="[k, v] in specs" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template></dl>
          </TabPanel>
          <TabPanel value="services">
            <ul class="svc-list">
              <li v-for="s in p.services" :key="s.variant"><strong>{{ s.name }}</strong> — {{ money(s.price) }}
                <small v-if="s.description">{{ s.description }}</small></li>
            </ul>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </form>
  </Dialog>
</template>

<style scoped>
.pv { position: relative; display: flex; flex-direction: column; gap: 20px; padding: 8px 0 4px; }
/* Fechar dentro do canto do modal, na faixa reservada pelo padding da coluna de compra. */
.pv__close {
  position: absolute; top: 12px; right: 0; z-index: 2; width: 34px; height: 34px; border-radius: 50%; cursor: pointer;
  display: grid; place-items: center; border: 1px solid var(--border); background: var(--surface-card); color: var(--text-muted);
  transition: color var(--dur-fast) ease, border-color var(--dur-fast) ease;
}
.pv__close:hover { color: var(--text-strong); border-color: var(--border-strong, var(--border)); }
.pv__top { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 32px; }

.gallery { display: flex; gap: 10px; min-width: 0; }
.thumbs { display: flex; flex-direction: column; gap: 8px; max-height: 460px; overflow-y: auto; flex-shrink: 0; }
.thumb { width: 76px; height: 76px; padding: 0; border-radius: 10px; overflow: hidden; cursor: pointer; border: 2px solid transparent; background: var(--surface-sunken); }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb.active { border-color: var(--brand); }
.stage { flex: 1; aspect-ratio: 1; max-height: 460px; border-radius: 14px; overflow: hidden; background: var(--surface-sunken); display: grid; place-items: center; }
.stage img { width: 100%; height: 100%; object-fit: contain; }
.stage__empty { width: 100%; height: 100%; display: grid; place-items: center; background: var(--brand-subtle); color: var(--text-brand); font: 800 64px/1 var(--font-sans); }

.buy { display: flex; flex-direction: column; gap: 14px; min-width: 0; padding-right: 48px; }
.crumb { color: var(--text-muted); font-weight: 600; font-size: 12.5px; }
.buy h2 { margin: -8px 0 0; font: 800 22px/1.25 var(--font-sans); color: var(--text-strong); }
.price-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.price { font: 800 28px/1 var(--font-sans); color: var(--text-strong); }
.price small { font-size: 14px; color: var(--text-muted); }
.was { color: var(--text-muted); font-size: 15px; }
.stock { margin-left: auto; display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; font-weight: 600; color: var(--success-text); }
.stock.out { color: var(--warning-text); }
.sku { color: var(--text-muted); font: 500 12px/1 var(--font-mono); margin-top: -8px; }

.axis { display: flex; flex-direction: column; gap: 8px; }
.axis__label { font-size: 13px; font-weight: 700; color: var(--text-strong); }
.axis__label b { font-weight: 500; color: var(--text-muted); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  min-width: 48px; padding: 9px 14px; border-radius: 8px; cursor: pointer; border: 1px solid var(--border);
  background: var(--surface-card); color: var(--text-body); font: 600 13px/1 var(--font-sans);
  transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease;
}
.chip:enabled:hover { border-color: var(--brand-border); }
.chip.active { border-color: var(--brand); background: var(--brand-subtle); color: var(--text-brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 18%, transparent); }
.chip.out { border-style: dashed; color: var(--text-muted); }
.chip.faded:not(.active) { opacity: 0.55; }
.chip:disabled { opacity: 0.35; cursor: not-allowed; text-decoration: line-through; }

.stepper { display: inline-flex; align-items: center; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; width: max-content; }
.stepper button { width: 40px; height: 40px; border: 0; background: var(--surface-card); color: var(--brand); cursor: pointer; }
.stepper button:disabled { color: var(--text-muted); cursor: default; }
.stepper :deep(.p-inputnumber-input) { width: 56px; height: 40px; text-align: center; border: 0; border-left: 1px solid var(--border); border-right: 1px solid var(--border); border-radius: 0; }
.qty-input { width: 180px; }

.services { display: flex; flex-direction: column; gap: 6px; }
.service {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px; text-align: left; cursor: pointer;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card); font-family: var(--font-sans);
}
.service i { color: var(--text-muted); font-size: 16px; }
.service.active { border-color: var(--brand); background: var(--brand-subtle); }
.service.active i { color: var(--brand); }
.service__text { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.service__text strong { font-size: 13.5px; color: var(--text-strong); }
.service__text small { font-size: 12px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.service__price { font-weight: 700; color: var(--text-strong); font-size: 13.5px; white-space: nowrap; }

.cta { display: flex; align-items: center; gap: 14px; margin-top: 4px; }
.cta__total { display: flex; flex-direction: column; }
.cta__total span { font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); }
.cta__total strong { font: 800 20px/1.1 var(--font-sans); color: var(--text-strong); }
.cta__btn { flex: 1; justify-content: center; gap: 8px; height: 46px; font-size: 15px; }
.cta__btn kbd { font: 600 10px/1 var(--font-mono); padding: 3px 5px; border-radius: 4px; background: color-mix(in srgb, currentColor 18%, transparent); }
.hint { color: var(--text-muted); display: flex; gap: 6px; align-items: center; margin-top: -6px; }

.pv__tabs :deep(.p-tabpanels) { padding: 16px 2px 4px; background: transparent; }
.pv__tabs :deep(.p-tablist-tab-list) { background: transparent; }
.rich { color: var(--text-body); font-size: 14px; line-height: 1.6; max-width: 820px; }
.rich :deep(h1), .rich :deep(h2), .rich :deep(h3) { color: var(--text-strong); margin: 0 0 8px; font-size: 18px; }
.muted { color: var(--text-muted); margin: 0; }
.specs { display: grid; grid-template-columns: max-content 1fr; gap: 8px 24px; margin: 0; font-size: 13.5px; }
.specs dt { color: var(--text-muted); font-weight: 600; }
.specs dd { margin: 0; color: var(--text-strong); }
.svc-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; color: var(--text-body); }
.svc-list small { display: block; color: var(--text-muted); }

@media (max-width: 820px) {
  .pv__top { grid-template-columns: 1fr; gap: 18px; }
  .buy { padding-right: 0; }
  .pv__close { top: 8px; right: 8px; box-shadow: var(--shadow-sm); } /* no celular fica sobre a foto */
  .gallery { flex-direction: column-reverse; }
  .thumbs { flex-direction: row; max-height: none; overflow-x: auto; }
  .thumb { width: 60px; height: 60px; }
}
</style>
