<script setup lang="ts">
/**
 * Conferência do recebimento, de dois jeitos:
 *  - Leitura: o conferente lê cada código (leitor ou CÂMERA, botão ao lado do campo) e o
 *    sistema compara com o documento. Unidade em várias caixas só conta quando TODAS as
 *    caixas foram lidas; as soltas aparecem para procurar.
 *  - Manual (se a Logística permitir): item a item, "Correto" ou "Incorreto". Incorreto pede
 *    o motivo, quantos chegaram e quantos entram no estoque, e um campo para descrever o erro.
 *    Produto em volumes (guarda-roupa em 3 caixas) mostra quantas caixas devem chegar e uma
 *    lista para marcar cada volume; volume desmarcado vira "Incorreto · faltou" com a caixa
 *    na descrição. Na aprovação a entrada vai ajustada e o erro de entrada fica registrado.
 */
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import { computed, nextTick, onMounted, ref } from "vue";

import { type Conference, type ManualLine, stockApi } from "@/api/operations";
import CameraScanner from "@/components/common/CameraScanner.vue";
import { useNotify } from "@/composables/useNotify";
import { divergenceReason } from "@/resources/stock";
import type { FormActionContext } from "@/resources/types";
import { cameraAvailable } from "@/utils/camera";
import { quantity } from "@/utils/format";

type Volume = { number: number; description: string };
type DocItem = { id: string; variant_name: string; sku: string; expected_quantity: string | null; quantity: string;
                 lot_number?: string; volumes?: Volume[] };
type Answer = { ok: boolean | null; arrived: number | null; accepted: number | null; reason: string; notes: string;
                volumes: number[] };
type ManualRow = { item: DocItem; a: Answer };

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: [] }>();
/** Rascunho pode concluir: o contado vira a quantidade dos itens (entrada da NF-e exige isso para aprovar). */
const canFinish = props.ctx.values.status === "draft";
const manualAllowed = Boolean(props.ctx.values.manual_conference) && canFinish;
const hasCamera = cameraAvailable();
const mode = ref<"scan" | "manual">("scan");
const finishing = ref(false);
const notify = useNotify();
const codes = ref<string[]>([]);
const code = ref("");
const result = ref<Conference | null>(null);
const checking = ref(false);
const input = ref<{ $el: HTMLInputElement }>();
const camera = ref(false);

// ── Leitura ────────────────────────────────────────────────────────────────
async function check() {
  checking.value = true;
  try {
    result.value = await stockApi.conference(props.ctx.id, codes.value);
  } catch (error) {
    notify.error(error, "Não foi possível conferir");
  } finally {
    checking.value = false;
  }
}

async function read(value: string) {
  codes.value = [...codes.value, value.trim()];
  await check();
}

async function add() {
  const value = code.value.trim();
  if (!value) return;
  code.value = "";
  await read(value);
  await nextTick();
  input.value?.$el.focus();
}

function undo() {
  codes.value = codes.value.slice(0, -1);
  void check();
}

// ── Manual ─────────────────────────────────────────────────────────────────
const rows = ref(((props.ctx.values.items ?? []) as DocItem[]).filter((i) => i.expected_quantity != null)
  .map((item) => ({ item, a: { ok: null, arrived: null, accepted: null, reason: "", notes: "", volumes: [] } as Answer })));
const pending = computed(() => rows.value.filter(({ a }) =>
  a.ok === null || (a.ok === false && (!a.reason || a.arrived === null || a.accepted === null))).length);

function mark(row: ManualRow, ok: boolean) {
  row.a.ok = ok;
  if (ok) row.a.volumes = (row.item.volumes ?? []).map((v) => v.number);
  if (!ok && row.a.arrived === null) {
    row.a.arrived = Number(row.item.expected_quantity);
    row.a.accepted = Number(row.item.expected_quantity);
  }
}
const volumeLabel = (row: ManualRow, v: Volume) =>
  `Vol ${v.number}/${row.item.volumes?.length}${v.description ? ` · ${v.description}` : ""}`;
/** Caixas que devem chegar: unidades × volumes por unidade. */
const boxes = (row: ManualRow) => Number(row.item.expected_quantity) * (row.item.volumes?.length ?? 0);
/** Marcou/desmarcou um volume: todos marcados = correto; faltando algum = incorreto, motivo
 *  "faltou" e as caixas que faltam já escritas na descrição (dá para completar). */
function toggleVolume(row: ManualRow, number: number, checked: boolean) {
  row.a.volumes = checked ? [...row.a.volumes, number] : row.a.volumes.filter((n) => n !== number);
  const missing = (row.item.volumes ?? []).filter((v) => !row.a.volumes.includes(v.number));
  if (!missing.length) return mark(row, true);
  mark(row, false);
  if (!row.a.reason) row.a.reason = "missing";
  const text = `Faltou: ${missing.map((v) => volumeLabel(row, v)).join(", ")}`;
  row.a.notes = row.a.notes && !row.a.notes.startsWith("Faltou:") ? row.a.notes : text;
}
/** Mudou quantos chegaram: o que entra acompanha (dá para baixar depois, ex.: avariados). */
function setArrived(answer: Answer, value: number | null) {
  if (answer.accepted === null || answer.accepted === answer.arrived) answer.accepted = value;
  answer.arrived = value;
}
const allOk = () => rows.value.forEach((row) => mark(row, true));

// ── Concluir ───────────────────────────────────────────────────────────────
async function finish() {
  finishing.value = true;
  try {
    if (mode.value === "manual") {
      const lines: ManualLine[] = rows.value.map(({ item, a }) => (a.ok ? { item: item.id, ok: true }
        : { item: item.id, ok: false, arrived: String(a.arrived), accepted: String(a.accepted), reason: a.reason, notes: a.notes }));
      await stockApi.check(props.ctx.id, { lines });
      const wrong = rows.value.filter(({ a }) => a.ok === false).length;
      notify.success(wrong ? `Conferência concluída: ${wrong} item(ns) com diferença` : "Conferência concluída: tudo confere",
                     wrong ? "Na aprovação a entrada vai ajustada e o erro fica registrado." : undefined);
    } else {
      await stockApi.check(props.ctx.id, { codes: codes.value });
      notify.success(result.value?.ok ? "Conferência concluída: tudo confere" : "Conferência concluída com diferenças");
    }
    emit("done");
  } catch (error) {
    notify.error(error, "Não foi possível concluir a conferência");
  } finally {
    finishing.value = false;
  }
}

onMounted(() => {
  void check();
  input.value?.$el.focus();
});
</script>

<template>
  <div class="conference">
    <SelectButton v-if="manualAllowed" v-model="mode" :allow-empty="false" option-label="label" option-value="value"
                  :options="[{ label: 'Ler os códigos', value: 'scan' }, { label: 'Conferência manual', value: 'manual' }]"
                  class="modes" />

    <template v-if="mode === 'scan'">
      <div class="scan">
        <InputText ref="input" v-model="code" placeholder="Leia o código e tecle Enter" fluid @keydown.enter.prevent="add" />
        <Button v-if="hasCamera" icon="pi pi-camera" severity="secondary" outlined aria-label="Ler pela câmera"
                title="Ler pela câmera" @click="camera = true" />
        <Button icon="pi pi-undo" label="Desfazer" severity="secondary" outlined size="small" :disabled="!codes.length" @click="undo" />
      </div>
      <p class="muted">{{ codes.length }} leitura(s)</p>
      <div v-if="result" class="status" :class="result.ok ? 'status--ok' : 'status--diff'">
        <i :class="result.ok ? 'pi pi-check-circle' : 'pi pi-exclamation-circle'" />
        {{ result.ok ? "Tudo confere com o documento." : "Há diferenças: confira abaixo." }}
      </div>
      <table v-if="result" class="hide-sm-5 list">
        <thead><tr><th>Produto</th><th class="right">Esperado</th><th class="right">Contado</th><th class="right">Diferença</th><th>Caixas</th></tr></thead>
        <tbody>
          <tr v-for="row in result.rows" :key="row.variant" :class="{ diff: Number(row.difference_quantity) !== 0 || row.loose_volumes.length }">
            <td><strong>{{ row.description }}</strong> <small class="muted">{{ row.sku }}</small>
              <span v-if="row.unexpected" class="pill pill--warning">fora do documento</span></td>
            <td class="right">{{ quantity(row.expected_quantity) }}</td>
            <td class="right"><strong>{{ quantity(row.counted_quantity) }}</strong></td>
            <td class="right">{{ Number(row.difference_quantity) > 0 ? "+" : "" }}{{ quantity(row.difference_quantity) }}</td>
            <td>
              <span v-if="row.loose_volumes.length" class="muted">soltas: {{ row.loose_volumes.join(", ") }}</span>
              <span v-if="row.missing_volumes.length" class="miss"> · falta: {{ row.missing_volumes.join(", ") }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="result?.unknown_codes.length" class="unknown"><i class="pi pi-question-circle" /> Não reconhecidos: {{ result.unknown_codes.join(", ") }}</p>
      <CameraScanner v-model:visible="camera" title="Conferir pela câmera" @read="read" />
    </template>

    <template v-else>
      <div class="manual-head">
        <p class="muted">Confira cada item com a mercadoria na mão. Se a quantidade não bater, marque <b>Incorreto</b>.</p>
        <Button label="Marcar todos corretos" icon="pi pi-check-square" text size="small" @click="allOk" />
      </div>
      <ul class="manual">
        <li v-for="row in rows" :key="row.item.id" :class="{ ok: row.a.ok === true, bad: row.a.ok === false }">
          <div class="manual__row">
            <div class="manual__name">
              <strong>{{ row.item.variant_name }}</strong>
              <small>{{ row.item.sku }}<template v-if="row.item.lot_number"> · lote {{ row.item.lot_number }}</template></small>
            </div>
            <span class="manual__qty">Na nota <b>{{ quantity(row.item.expected_quantity) }}</b>
              <small v-if="row.item.volumes?.length" class="manual__boxes">
                <i class="pi pi-box" /> {{ row.item.volumes.length }} volumes/un · {{ boxes(row) }} caixas
              </small>
            </span>
            <div class="manual__btns">
              <Button label="Correto" icon="pi pi-check" size="small" :severity="row.a.ok === true ? 'success' : 'secondary'"
                      :outlined="row.a.ok !== true" @click="mark(row, true)" />
              <Button label="Incorreto" icon="pi pi-times" size="small" :severity="row.a.ok === false ? 'danger' : 'secondary'"
                      :outlined="row.a.ok !== false" @click="mark(row, false)" />
            </div>
          </div>
          <div v-if="row.item.volumes?.length" class="manual__vols">
            <span class="manual__vols-title">Marque os volumes que chegaram (de todas as {{ quantity(row.item.expected_quantity) }} unidades):</span>
            <label v-for="v in row.item.volumes" :key="v.number" class="vol" :class="{ on: row.a.volumes.includes(v.number) }">
              <Checkbox :model-value="row.a.volumes.includes(v.number)" binary
                        @update:model-value="toggleVolume(row, v.number, Boolean($event))" />
              {{ volumeLabel(row, v) }}
            </label>
          </div>
          <div v-if="row.a.ok === false" class="manual__diff">
            <label>Motivo*
              <Select v-model="row.a.reason" :options="divergenceReason.options" option-label="label"
                      option-value="value" placeholder="Por que não bate?" fluid />
            </label>
            <label>Quantos chegaram*
              <InputNumber :model-value="row.a.arrived" :min="0" :max-fraction-digits="3" fluid
                           @update:model-value="setArrived(row.a, $event)" />
            </label>
            <label>Entram no estoque*
              <InputNumber v-model="row.a.accepted" :min="0" :max-fraction-digits="3" fluid />
            </label>
            <label class="wide">Descreva o erro
              <Textarea v-model="row.a.notes" maxlength="255" rows="2" auto-resize
                        placeholder="ex.: 2 caixas amassadas, Vol 2/3 não veio, fornecedor avisado" fluid />
            </label>
          </div>
        </li>
      </ul>
    </template>

    <div v-if="canFinish" class="foot">
      <span class="muted">
        <template v-if="mode === 'manual'">{{ pending ? `${pending} item(ns) sem marcar ou sem os dados da diferença.` : "Na aprovação a entrada vai com o que foi marcado." }}</template>
        <template v-else>Ao concluir, o contado vira a quantidade de cada item.</template>
      </span>
      <Button label="Concluir conferência" icon="pi pi-check" :loading="finishing"
              :disabled="mode === 'manual' ? pending > 0 : !codes.length" @click="finish" />
    </div>
  </div>
</template>

<style scoped>
.modes { margin-bottom: 0.75rem; }
.scan { display: flex; gap: 0.5rem; }
.conference > p { margin: 0.4rem 0 0.6rem; font-size: 12.5px; }
.status { display: flex; align-items: center; gap: 0.5rem; padding: 8px 10px; border-radius: 8px; font-size: 13px; font-weight: 600; }
.status--ok { background: var(--success-subtle); color: var(--success-text); }
.status--diff { background: var(--warning-subtle); color: var(--warning-text); }
.list { width: 100%; border-collapse: collapse; margin-top: 0.75rem; font-size: 13.5px; }
.list th { text-align: left; padding: 8px; font: 650 11.5px/1.3 var(--font-sans); text-transform: uppercase; letter-spacing: 0.04em;
           color: var(--text-muted); background: var(--surface-sunken); }
.list td { padding: 8px; border-top: 1px solid var(--border-subtle); }
.list tr.diff td { background: var(--warning-subtle); }
.right, .list .right { text-align: right; }
.miss { color: var(--danger-text); }
.unknown { margin-top: 0.75rem; font-size: 13px; color: var(--danger-text); }
.foot { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-top: 1rem; font-size: 12.5px; }

.manual-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.manual-head p { margin: 0; font-size: 12.5px; }
.manual { list-style: none; margin: 0.5rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.manual li { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--surface-card); }
.manual li.ok { border-color: var(--success); background: color-mix(in srgb, var(--success-subtle) 50%, var(--surface-card)); }
.manual li.bad { border-color: var(--danger); }
.manual__row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.manual__name { flex: 1; min-width: 180px; display: flex; flex-direction: column; }
.manual__name strong { color: var(--text-strong); font-size: 13.5px; }
.manual__name small { color: var(--text-muted); font-size: 12px; }
.manual__qty { font-size: 13px; color: var(--text-muted); white-space: nowrap; }
.manual__boxes { display: flex; align-items: center; gap: 4px; margin-top: 2px; font-size: 11.5px; color: var(--text-brand); }
.manual__boxes i { font-size: 11px; }
.manual__vols { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border); }
.manual__vols-title { flex-basis: 100%; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.vol { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
       font-size: 12.5px; color: var(--text-body); cursor: pointer; }
.vol.on { border-color: var(--success); background: var(--success-subtle); color: var(--success-text); }
.manual__qty b { color: var(--text-strong); font-size: 15px; }
.manual__btns { display: flex; gap: 6px; }
.manual__diff { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 8px 10px; margin-top: 10px; padding-top: 10px;
                border-top: 1px dashed var(--border); }
.manual__diff label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.manual__diff .wide { grid-column: 1 / -1; }
@media (max-width: 640px) { .scan :deep(.p-button-label) { display: none; } }
@media (max-width: 560px) { .manual__diff { grid-template-columns: 1fr 1fr; } .manual__diff label:first-child { grid-column: 1 / -1; } }
</style>
