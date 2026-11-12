<script setup lang="ts">
/**
 * Links de avaliação do pedido: um por tipo, o PEDIDO (produtos) e a ENTREGA (quando teve).
 * O cliente abre no celular, sem login. Cada link usa um hash aleatório, vale até a data
 * escolhida e só uma vez: depois de enviado, o tipo fica avaliado no pedido e não gera outro.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import Textarea from "primevue/textarea";
import { reactive, ref, watch } from "vue";

import { reviewsApi, type ReviewLink, type ReviewLinkKind } from "@/api/reviews";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { date, dateTime } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const notify = useNotify();
const client = useQueryClient();
const key = ["review-links", props.ctx.id];
const query = useQuery({ queryKey: key, queryFn: () => reviewsApi.links(props.ctx.id) });

const DAYS = [7, 15, 30, 60, 90, 120].map((d) => ({ label: `${d} dias`, value: d }));
const ICON: Record<ReviewLinkKind, string> = { order: "pi pi-shopping-bag", delivery: "pi pi-truck" };
const HINT: Record<ReviewLinkKind, string> = {
  order: "O cliente dá nota, comenta e manda fotos de cada produto comprado.",
  delivery: "O cliente dá nota para a entrega (prazo, cuidado, atendimento).",
};
const days = reactive<Record<string, number>>({ order: 30, delivery: 30 });
const texts = reactive<Record<string, string>>({});
const generating = ref<ReviewLinkKind | null>(null);
watch(() => query.data.value, (rows) => rows?.forEach((r) => { if (r.text) texts[r.kind] = r.text; }), { immediate: true });

async function generate(kind: ReviewLinkKind) {
  generating.value = kind;
  try {
    client.setQueryData(key, await reviewsApi.generateLink(props.ctx.id, kind, days[kind] ?? 30));
    notify.success("Link gerado", "Copie e envie ao cliente.");
  } catch (error) {
    notify.error(error, "Não foi possível gerar o link");
    await query.refetch();
  } finally {
    generating.value = null;
  }
}

function whatsapp(row: ReviewLink) {
  const phone = row.phone ?? "";
  const number = phone.length >= 10 && !phone.startsWith("55") ? `55${phone}` : phone;
  return `https://wa.me/${number}?text=${encodeURIComponent(texts[row.kind] ?? row.text ?? "")}`;
}

async function copy(value: string, what: string) {
  try {
    await navigator.clipboard.writeText(value);
    notify.success(`${what} copiado`);
  } catch {
    notify.warn("Não deu para copiar: selecione e copie manualmente.");
  }
}
</script>

<template>
  <div class="links">
    <p v-if="query.isError.value" class="error"><i class="pi pi-exclamation-circle" /> {{ (query.error.value as Error)?.message ?? "Não foi possível carregar." }}</p>
    <p v-else-if="!query.data.value" class="muted">Carregando…</p>
    <template v-else>
      <p class="muted">Sem login para o cliente: cada link tem um código único, vale uma vez e até a data escolhida.</p>
      <section v-for="row in query.data.value" :key="row.kind" class="card" :class="`card--${row.state}`">
        <header class="card__head">
          <i :class="ICON[row.kind]" />
          <div>
            <strong>{{ row.label }}</strong>
            <small>{{ HINT[row.kind] }}</small>
          </div>
          <span class="state">
            <template v-if="row.state === 'used'"><i class="pi pi-check-circle" /> Avaliado{{ row.used_at ? ` em ${dateTime(row.used_at)}` : "" }}</template>
            <template v-else-if="row.state === 'active'"><i class="pi pi-clock" /> Válido até {{ date(row.expires_at) }}</template>
            <template v-else-if="row.state === 'expired'"><i class="pi pi-ban" /> Expirou em {{ date(row.expires_at) }}</template>
            <template v-else>Sem link</template>
          </span>
        </header>

        <p v-if="row.state === 'used'" class="muted">{{ row.used_at
          ? "O cliente já enviou esta avaliação: ela está ligada ao pedido e não pode ser feita de novo."
          : row.kind === "order" ? "O cliente já avaliou estes produtos (nesta ou em outra compra): não há o que avaliar de novo."
            : "A entrega deste pedido já foi avaliada." }}</p>

        <template v-else-if="row.state === 'active' && row.url">
          <span class="row">
            <InputText :model-value="row.url" readonly fluid :aria-label="`Link de ${row.label}`"
                       @focus="($event.target as HTMLInputElement).select()" />
            <Button icon="pi pi-copy" label="Copiar" severity="secondary" outlined @click="copy(row.url, 'Link')" />
          </span>
          <Textarea v-model="texts[row.kind]" rows="3" auto-resize fluid :aria-label="`Mensagem de ${row.label}`" />
          <div class="actions">
            <Button label="Copiar mensagem" icon="pi pi-copy" severity="secondary" outlined size="small"
                    @click="copy(texts[row.kind] ?? '', 'Mensagem')" />
            <a :href="whatsapp(row)" target="_blank" rel="noopener" class="p-button p-component p-button-sm wa">
              <i class="pi pi-whatsapp" /> {{ row.phone ? "Enviar no WhatsApp do cliente" : "Abrir no WhatsApp" }}
            </a>
          </div>
        </template>

        <div v-else class="gen">
          <label>Vale por
            <Select v-model="days[row.kind]" :options="DAYS" option-label="label" option-value="value" size="small" />
          </label>
          <Button :label="row.state === 'expired' ? 'Gerar novo link' : 'Gerar link de avaliação'" icon="pi pi-link"
                  :loading="generating === row.kind" :disabled="generating !== null" @click="generate(row.kind)" />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.links { display: flex; flex-direction: column; gap: 12px; min-width: min(560px, 100%); }
.links > p { margin: 0; font-size: 13px; }
.card { display: flex; flex-direction: column; gap: 10px; padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-card); }
.card--used { background: var(--surface-sunken); }
.card__head { display: flex; align-items: flex-start; gap: 10px; }
.card__head > i { font-size: 18px; color: var(--text-brand); margin-top: 2px; }
.card__head > div { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.card__head strong { font-size: 14px; color: var(--text-strong); }
.card__head small { font-size: 12px; color: var(--text-muted); }
.state { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-muted); white-space: nowrap; }
.card--active .state { color: var(--text-brand); }
.card--used .state { color: var(--success-text); }
.card--expired .state { color: var(--danger-text); }
.card > p { margin: 0; font-size: 13px; }
.row { display: flex; gap: 6px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.gen { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 10px; }
.gen label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.wa { display: inline-flex; gap: 8px; align-items: center; background: #1fa855; border-color: #1fa855; color: #fff; text-decoration: none; }
.error { color: var(--danger-text); display: flex; gap: 6px; align-items: center; }
@media (max-width: 640px) {
  .card__head { flex-wrap: wrap; }
  .state { width: 100%; white-space: normal; }
  .row { flex-direction: column; }
}
</style>
