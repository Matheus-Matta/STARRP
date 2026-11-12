<script setup lang="ts">
/**
 * Extratos do caixa (como o "Histórico de aberturas e fechamentos" do StarChef): cada turno
 * aberto → fechado é um extrato próprio, agrupado pelo dia da abertura. Clicar abre o extrato
 * completo daquele turno; "Z" imprime o fechamento na bobina. Serve ao PDV e ao cadastro do caixa.
 * O esperado e a diferença vêm `null` para quem fecha às cegas (o backend já tira).
 */
import { useInfiniteQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import SelectButton from "primevue/selectbutton";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { resourceApi } from "@/api/resource";
import type { CashSession } from "@/api/types";
import { money } from "@/utils/format";
import { openPrint } from "@/utils/print";

/**
 * PDV: `register` (+ `current`, o turno aberto); clicar abre o extrato A4 numa aba.
 * Retaguarda (aba do cadastro do caixa): `id` do caixa; clicar abre a tela do extrato do turno.
 */
const props = defineProps<{ register?: string | null; current?: string | null; id?: string }>();
const router = useRouter();
const registerId = computed(() => props.register ?? props.id ?? null);

const STATUS: Record<string, [string, string]> = {
  open: ["Aberto", "warning"], pending_opening: ["Abertura aguardando gerente", "info"],
  pending_approval: ["Aguardando gerente", "info"], closed: ["Fechado", "success"], cancelled: ["Cancelado", "danger"],
};
const PERIODS = [{ label: "7 dias", value: 7 }, { label: "30 dias", value: 30 }, { label: "90 dias", value: 90 },
                 { label: "Tudo", value: 0 }];
const days = ref(30);
const since = computed(() => {
  if (!days.value) return undefined;
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - days.value + 1);
  return d.toISOString();
});

const query = useInfiniteQuery({
  queryKey: computed(() => ["cash-shift-history", registerId.value, since.value]),
  queryFn: ({ pageParam }) => resourceApi.list<CashSession>("/cash/sessions/", {
    register: registerId.value!, opened_at__gte: since.value, ordering: "-opened_at", page: pageParam, page_size: 30 }),
  initialPageParam: 1,
  getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  enabled: computed(() => Boolean(registerId.value)),
  refetchInterval: 60_000,
});
const sessions = computed(() => (query.data.value?.pages ?? []).flatMap((p) => p.results));
const total = computed(() => query.data.value?.pages[0]?.count ?? 0);

const dayFmt = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
const timeFmt = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const shortFmt = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const dayKey = (iso: string) => new Date(iso).toLocaleDateString("sv-SE"); // AAAA-MM-DD local

const groups = computed(() => {
  const out: { key: string; label: string; items: CashSession[]; counted: number }[] = [];
  for (const s of sessions.value) {
    const key = dayKey(s.opened_at);
    let group = out[out.length - 1];
    if (!group || group.key !== key) {
      group = { key, label: dayFmt.format(new Date(s.opened_at)), items: [], counted: 0 };
      out.push(group);
    }
    group.items.push(s);
    group.counted += Number(s.counted_amount ?? 0);
  }
  return out;
});

/** "08:02 → 14:30"; fechado noutro dia mostra a data do fechamento. */
function span(s: CashSession) {
  const start = timeFmt.format(new Date(s.opened_at));
  if (!s.closed_at) return `${start} → em aberto`;
  const end = new Date(s.closed_at);
  return `${start} → ${dayKey(s.closed_at) === dayKey(s.opened_at) ? timeFmt.format(end) : shortFmt.format(end)}`;
}
const diffTone = (v: unknown) => (v === null || v === undefined ? "" : Number(v) === 0 ? "ok" : "bad");
const show = (sid: string) => (props.id ? router.push(`/cadastros/turnos-de-caixa/${sid}/extrato`)
                                          : openPrint("turno", sid, { formato: "a4" }));
</script>

<template>
  <section class="hist">
    <header class="hist__head">
      <div>
        <h3>Extratos do caixa</h3>
        <p>Cada abertura → fechamento é um extrato. Clique para ver, imprimir ou exportar.</p>
      </div>
      <SelectButton v-model="days" :options="PERIODS" option-label="label" option-value="value" :allow-empty="false" size="small" />
    </header>

    <div v-if="!registerId" class="hist__empty">Nenhum caixa vinculado.</div>
    <div v-else-if="query.isPending.value" class="hist__empty"><i class="pi pi-spin pi-spinner" /> Carregando turnos…</div>
    <div v-else-if="!sessions.length" class="hist__empty">Nenhum turno no período.</div>

    <div v-for="g in groups" :key="g.key" class="day">
      <div class="day__head">
        <strong>{{ g.label }}</strong>
        <span>{{ g.items.length }} {{ g.items.length === 1 ? "turno" : "turnos" }}<template v-if="g.counted">
          · contado {{ money(g.counted) }}</template></span>
      </div>
      <div v-for="s in g.items" :key="s.id" class="shift" :class="{ current: s.id === current }" role="button" tabindex="0"
           @click="show(s.id)" @keydown.enter="show(s.id)">
        <div class="shift__main">
          <strong>{{ span(s) }}</strong>
          <small>{{ s.opened_by_name || "—" }}<template v-if="s.id === current"> · turno atual</template></small>
        </div>
        <span class="tag" :class="`tag--${STATUS[s.status]?.[1] ?? 'info'}`">{{ STATUS[s.status]?.[0] ?? s.status }}</span>
        <div class="shift__num"><small>Troco inicial</small><span>{{ money(s.opening_amount) }}</span></div>
        <div class="shift__num"><small>Contado</small><span>{{ s.counted_amount == null ? "—" : money(s.counted_amount) }}</span></div>
        <div class="shift__num"><small>Diferença</small>
          <span :class="diffTone(s.difference)">{{ s.difference == null ? "—" : money(s.difference) }}</span></div>
        <div class="shift__acts" @click.stop>
          <Button icon="pi pi-file" text rounded size="small" aria-label="Extrato completo" title="Extrato (A4)"
                  @click="show(s.id)" />
          <Button icon="pi pi-print" text rounded size="small" aria-label="Imprimir o Z" title="Z na bobina"
                  @click="openPrint('turno', s.id, { formato: '80mm' })" />
        </div>
      </div>
    </div>

    <Button v-if="query.hasNextPage.value" :label="`Carregar mais (${sessions.length} de ${total})`" text size="small"
            :loading="query.isFetchingNextPage.value" @click="query.fetchNextPage()" />
  </section>
</template>

<style scoped>
.hist { display: flex; flex-direction: column; gap: 10px; }
.hist__head { display: flex; justify-content: space-between; align-items: flex-end; gap: 10px; flex-wrap: wrap; }
.hist__head h3 { margin: 0; font: 700 15px/1.2 var(--font-sans); color: var(--text-strong); }
.hist__head p { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); }
.hist__empty { padding: 16px; text-align: center; color: var(--text-muted); font-size: 13px; }
.day { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
       background: var(--surface-card); }
.day__head { display: flex; justify-content: space-between; gap: 8px; padding: 8px 12px; background: var(--surface-ground);
             font-size: 12.5px; color: var(--text-muted); border-bottom: 1px solid var(--border); }
.day__head strong { color: var(--text-strong); text-transform: capitalize; }
.shift { display: grid; grid-template-columns: minmax(150px, 1.4fr) auto repeat(3, minmax(90px, 1fr)) auto; align-items: center;
         gap: 10px; padding: 8px 12px; cursor: pointer; border-top: 1px solid var(--border); }
.shift:first-of-type { border-top: 0; }
.shift:hover { background: var(--brand-subtle); }
.shift.current { box-shadow: inset 3px 0 0 var(--brand); }
.shift__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.shift__main strong { font-size: 13.5px; color: var(--text-strong); }
.shift__main small, .shift__num small { font-size: 11.5px; color: var(--text-muted); }
.shift__num { display: flex; flex-direction: column; gap: 2px; font-size: 13px; text-align: right; }
.shift__acts { display: flex; }
.ok { color: var(--success-text); }
.bad { color: var(--danger-text); font-weight: 700; }
.tag { padding: 2px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 600; white-space: nowrap; }
.tag--success { background: var(--success-subtle, #dcfce7); color: var(--success-text); }
.tag--warning { background: var(--warning-subtle, #fef3c7); color: var(--warning-text); }
.tag--info { background: var(--info-subtle, #dbeafe); color: var(--info-text, #1d4ed8); }
.tag--danger { background: var(--danger-subtle, #fee2e2); color: var(--danger-text); }
@media (max-width: 720px) {
  .shift { grid-template-columns: 1fr auto; }
  .shift__num { display: none; }
}
</style>
