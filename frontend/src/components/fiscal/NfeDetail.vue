<script setup lang="ts">
/**
 * A nota de entrada inteira numa tela: em que etapa está, o que fazer agora e
 * os itens com o vínculo ao produto do sistema.
 *
 * Etapas: Recebida (resumo) → XML com os itens (ciência) → Vincular itens →
 * Conferência (a entrada de estoque já existe em rascunho) → Aprovada.
 * O vínculo é aprendido: a próxima nota do mesmo fornecedor já vem casada.
 *
 * Toda etapa volta: desvincular / voltar a usar um item, "Voltar para os vínculos"
 * (descarta a conferência em rascunho) e "Desfazer recebimento" (estorna o estoque e
 * cancela as contas a pagar). Mexer num item com a conferência aberta refaz a entrada.
 */
import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import Menu from "primevue/menu";
import { useConfirm } from "primevue/useconfirm";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { nfeApi } from "@/api/fiscal";
import PromptDialog, { type PromptAnswer, type PromptSpec } from "@/components/common/PromptDialog.vue";
import RelationSelect from "@/components/resource/RelationSelect.vue";
import { useNotify } from "@/composables/useNotify";
import { fiscalStatus, manifestation, nfeStage } from "@/resources/fiscal";
import type { FormActionContext } from "@/resources/types";
import { date, dateTime, money, quantity } from "@/utils/format";

type Item = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Entry = { id: string; number: number; status: string; checked: boolean } | null;

const props = defineProps<{ ctx: FormActionContext }>();
const router = useRouter();
const notify = useNotify();
const confirm = useConfirm();
const busy = ref<string | null>(null);
const more = ref<InstanceType<typeof Menu>>();
const prompt = ref<PromptSpec | null>(null);
let answered: (value: PromptAnswer | null) => void = () => undefined;

const v = computed(() => props.ctx.values as Item);
const stage = computed(() => String(v.value.stage ?? ""));
const items = computed(() => (v.value.items ?? []) as Item[]);
const entry = computed(() => v.value.entry as Entry);
const variantRelation = { endpoint: "/catalog/variants/", labelKey: "display_name", params: { is_active: "true" } };
/** Vínculo muda até o recebimento; com a conferência aberta, mexer descarta o rascunho e refaz. */
const draftEntry = computed(() => (entry.value?.status === "draft" ? entry.value : null));
const canMap = computed(() => v.value.xml_status === "available" && (!entry.value || Boolean(draftEntry.value))
  && !["cancelled", "ignored", "received"].includes(stage.value));

const STEPS = [
  { key: "summary", label: "Nota recebida" },
  { key: "xml", label: "XML com os itens" },
  { key: "mapping", label: "Vincular itens" },
  { key: "checking", label: "Conferência" },
  { key: "received", label: "Aprovada" },
];
const reached = computed(() => ({
  summary: 0, pending_mapping: 2, pending_receipt: 3, checking: 3, received: 5,
})[stage.value] ?? (v.value.xml_status === "available" ? 2 : 1));

async function act(label: string, call: () => Promise<unknown>, success?: string) {
  busy.value = label;
  try {
    await call();
    if (success) notify.success(success);
    await props.ctx.reload();
  } catch (error) {
    notify.error(error, `Não foi possível: ${label.toLowerCase()}`);
  } finally {
    busy.value = null;
  }
}

function ask(spec: PromptSpec) {
  prompt.value = spec;
  return new Promise<PromptAnswer | null>((resolve) => (answered = resolve));
}
function onAnswer(value: PromptAnswer | null) {
  prompt.value = null;
  answered(value);
}

const science = () => act("Dar ciência", () => nfeApi.science(props.ctx.id), "Ciência registrada");
const download = () => act("Baixar XML", () => nfeApi.download(props.ctx.id));
const rematch = () => act("Casar itens", () => nfeApi.rematch(props.ctx.id), "Itens conferidos com o cadastro");

async function receive() {
  busy.value = "Gerar entrada";
  try {
    const doc = await nfeApi.receive(props.ctx.id);
    notify.success(`Entrada nº ${doc.number} criada: confira os itens`);
    void router.push(`/cadastros/entradas-e-saidas/${doc.id}`);
  } catch (error) {
    notify.error(error, "Não foi possível gerar a entrada");
  } finally {
    busy.value = null;
  }
}

/** Com a conferência aberta, avisa antes: a entrada em rascunho é descartada e refeita. */
function guarded(label: string, run: () => void) {
  if (!draftEntry.value) return run();
  confirm.require({
    header: label,
    message: `A entrada nº ${draftEntry.value.number} está em conferência. Ela será descartada e gerada de novo com o item corrigido (a contagem feita até agora se perde).`,
    icon: "pi pi-exclamation-triangle", acceptProps: { label: "Continuar" },
    rejectProps: { label: "Voltar", severity: "secondary", outlined: true }, accept: run,
  });
}

function mapItem(item: Item, variant: unknown, factor?: number | null) {
  if (!variant) return item.variant ? unmapItem(item) : undefined; // limpou o campo = desvincular
  guarded("Trocar o vínculo", () => void act("Vincular",
    () => nfeApi.mapItem(props.ctx.id, String(item.id), String(variant), factor ?? item.conversion_factor)));
}

function unmapItem(item: Item) {
  confirm.require({
    header: "Desvincular item",
    message: `Tirar o vínculo de "${item.description}" com ${item.variant_name}? O vínculo aprendido com este fornecedor também é esquecido.`
      + (draftEntry.value ? ` A entrada nº ${draftEntry.value.number} em conferência será descartada.` : ""),
    icon: "pi pi-link", acceptProps: { label: "Desvincular", severity: "danger" },
    rejectProps: { label: "Voltar", severity: "secondary", outlined: true },
    accept: () => act("Desvincular", () => nfeApi.unmapItem(String(item.id)), "Item desvinculado: escolha o produto certo"),
  });
}

async function createProduct(item: Item) {
  const answer = await ask({ title: "Cadastrar produto", label: `Preço de venda de "${item.description}"`, kind: "text",
                             confirmLabel: "Cadastrar e vincular" });
  if (answer) void act("Cadastrar produto", () => nfeApi.createProduct(String(item.id), answer.text?.replace(",", ".")),
                       "Produto cadastrado e vinculado");
}

function toggleIgnore(item: Item) {
  if (item.ignored) {
    return guarded("Voltar a usar o item", () => void act("Voltar a usar", () => nfeApi.unignoreItem(String(item.id)),
                                                            "O item volta a entrar no estoque"));
  }
  guarded("Ignorar item", () => void act("Ignorar item", () => nfeApi.ignoreItem(String(item.id), "Não entra no estoque"),
                                         "Item fora do estoque"));
}

function discardEntry() {
  if (!draftEntry.value) return;
  confirm.require({
    header: "Voltar para os vínculos",
    message: `Descartar a entrada nº ${draftEntry.value.number} (em conferência)? Ela não moveu o estoque. Os vínculos ficam como estão para você revisar e gerar a entrada de novo.`,
    icon: "pi pi-undo", acceptProps: { label: "Descartar conferência", severity: "danger" },
    rejectProps: { label: "Voltar", severity: "secondary", outlined: true },
    accept: () => act("Voltar para os vínculos", () => nfeApi.discardEntry(props.ctx.id), "Conferência descartada"),
  });
}

async function undoReceipt() {
  const answer = await ask({
    title: "Desfazer recebimento",
    label: `O estoque da entrada nº ${entry.value?.number} é estornado e as contas a pagar da nota são canceladas. Por quê?`,
    kind: "text", required: true, danger: true, confirmLabel: "Desfazer recebimento",
    options: ["Produto vinculado errado", "Quantidade lançada errada", "Fator de conversão errado", "Depósito errado"],
  });
  if (answer) void act("Desfazer recebimento", () => nfeApi.undoReceipt(props.ctx.id, answer.text ?? ""),
                       "Recebimento desfeito: corrija e receba de novo");
}

const restore = () => act("Restaurar nota", () => nfeApi.restore(props.ctx.id), "A nota voltou para o fluxo");

async function manifest(code: string, label: string) {
  let reason = "";
  if (code === "210240") {
    const answer = await ask({ title: label, label: "Por que a operação não aconteceu? (mín. 15 letras)", kind: "text",
                               required: true, confirmLabel: "Enviar à SEFAZ" });
    if (!answer) return;
    reason = answer.text ?? "";
  }
  confirm.require({
    header: label, message: `Enviar "${label}" para a SEFAZ? A manifestação fica registrada no CNPJ do emitente.`,
    icon: "pi pi-send", acceptProps: { label: "Enviar" }, rejectProps: { label: "Voltar", severity: "secondary", outlined: true },
    accept: () => act(label, () => nfeApi.manifest(props.ctx.id, code, reason), "Manifestação registrada"),
  });
}

async function ignoreNote() {
  const answer = await ask({ title: "Ignorar nota", label: "Motivo (ex.: nota de uso e consumo)", kind: "text",
                             confirmLabel: "Ignorar" });
  if (answer) void act("Ignorar nota", () => nfeApi.ignore(props.ctx.id, answer.text), "Nota ignorada");
}

const menu = computed(() => [
  { label: "Manifestar", items: [
    { label: "Confirmar a operação", icon: "pi pi-check", command: () => manifest("210200", "Confirmação da operação") },
    { label: "Desconhecer a operação", icon: "pi pi-question-circle", command: () => manifest("210220", "Desconhecimento da operação") },
    { label: "Operação não realizada", icon: "pi pi-ban", command: () => manifest("210240", "Operação não realizada") },
  ] },
  { label: "Nota", items: [
    { label: "Baixar o XML de novo", icon: "pi pi-download", command: download, visible: v.value.xml_status !== "available" },
    { label: "Casar itens de novo", icon: "pi pi-sync", command: rematch, visible: canMap.value },
    { label: "Ignorar esta nota", icon: "pi pi-eye-slash", command: ignoreNote, visible: !v.value.ignored_at && !entry.value },
  ] },
  { label: "Voltar etapa", items: [
    { label: "Voltar para os vínculos", icon: "pi pi-undo", command: discardEntry, visible: Boolean(draftEntry.value) },
    { label: "Desfazer recebimento", icon: "pi pi-replay", command: undoReceipt, visible: stage.value === "received" },
    { label: "Restaurar a nota", icon: "pi pi-eye", command: restore, visible: Boolean(v.value.ignored_at) },
  ] },
]);

function copyKey() {
  void navigator.clipboard?.writeText(String(v.value.access_key ?? ""));
  notify.success("Chave copiada");
}
/** Dica com as caixas: "Vol 1 · Laterais", "Vol 2 · Portas"... */
const volumesHint = (item: Item) => (item.volumes as { number: number; description: string }[])
  .map((vol) => `Vol ${vol.number}${vol.description ? ` · ${vol.description}` : ""}`).join(" | ");
const formatKey = (key: unknown) => String(key ?? "").replace(/(\d{4})(?=\d)/g, "$1 ");
</script>

<template>
  <div class="nfe">
    <!-- Etapas -->
    <ol class="steps" :class="{ off: ['cancelled', 'ignored'].includes(stage) }">
      <li v-for="(step, index) in STEPS" :key="step.key"
          :class="{ done: index < reached, current: index === reached && stage !== 'received' }">
        <span class="dot"><i v-if="index < reached" class="pi pi-check" /><template v-else>{{ index + 1 }}</template></span>
        <span class="steps__label">{{ step.label }}</span>
      </li>
    </ol>

    <!-- O que fazer agora -->
    <div class="next" :class="`next--${stage}`">
      <template v-if="stage === 'cancelled'">
        <i class="pi pi-ban" />
        <p><b>Nota cancelada pelo fornecedor.</b> Não entra no estoque.
          {{ entry?.status === "posted" ? "Ela já tinha entrado: veja a pendência aberta e combine com o fornecedor." : "" }}</p>
      </template>
      <template v-else-if="stage === 'ignored'">
        <i class="pi pi-eye-slash" /><p><b>Nota ignorada.</b> {{ v.ignored_reason }}</p>
        <Button label="Restaurar a nota" icon="pi pi-eye" size="small" severity="secondary" outlined
                :loading="busy === 'Restaurar nota'" @click="restore" />
      </template>
      <template v-else-if="stage === 'summary'">
        <i class="pi pi-envelope" />
        <p><b>A SEFAZ mandou só o resumo.</b> Dê ciência da operação para baixar o XML com os itens.
          <template v-if="v.xml_status === 'pending'"> A ciência já foi dada: o XML deve chegar na próxima busca.</template></p>
        <Button v-if="v.manifestation === 'none' || v.manifestation === 'error'" label="Dar ciência e baixar XML"
                icon="pi pi-download" size="small" :loading="busy === 'Dar ciência'" @click="science" />
        <Button v-else label="Baixar XML" icon="pi pi-download" size="small" :loading="busy === 'Baixar XML'" @click="download" />
      </template>
      <template v-else-if="stage === 'pending_mapping'">
        <i class="pi pi-link" />
        <p><b>{{ v.pending_count }} {{ v.pending_count === 1 ? "item sem produto" : "itens sem produto" }}.</b>
          Escolha o produto de cada um (ou cadastre). O vínculo fica gravado para as próximas notas deste fornecedor.</p>
      </template>
      <template v-else-if="stage === 'pending_receipt'">
        <i class="pi pi-box" />
        <p><b>Itens vinculados.</b> Gere a entrada de estoque para conferir e aprovar.</p>
        <Button label="Gerar entrada" icon="pi pi-arrow-right" size="small" :loading="busy === 'Gerar entrada'" @click="receive" />
      </template>
      <template v-else-if="entry">
        <i :class="stage === 'received' ? 'pi pi-check-circle' : 'pi pi-qrcode'" />
        <p v-if="stage === 'received'"><b>Recebida na entrada nº {{ entry.number }}.</b>
          {{ v.receiving === "divergent" ? "A conferência achou diferença com a nota." : "Tudo conforme a nota." }}</p>
        <p v-else><b>Entrada nº {{ entry.number }} {{ entry.checked ? "conferida: falta aprovar." : "esperando a conferência." }}</b>
          Leia os códigos na conferência e aprove para o estoque entrar.</p>
        <Button v-if="stage === 'received'" label="Desfazer recebimento" icon="pi pi-replay" size="small"
                severity="danger" outlined :loading="busy === 'Desfazer recebimento'" @click="undoReceipt" />
        <Button v-else label="Voltar para os vínculos" icon="pi pi-undo" size="small" severity="secondary" outlined
                :loading="busy === 'Voltar para os vínculos'" @click="discardEntry" />
        <Button :label="`Abrir entrada nº ${entry.number}`" icon="pi pi-external-link" size="small"
                @click="router.push(`/cadastros/entradas-e-saidas/${entry.id}`)" />
      </template>
      <Button icon="pi pi-ellipsis-v" text rounded severity="secondary" size="small" aria-label="Mais ações"
              class="next__more" @click="more?.toggle($event)" />
      <Menu ref="more" :model="menu" popup />
    </div>

    <!-- Cabeçalho da nota -->
    <section class="card head">
      <div class="kv kv--wide">
        <span>Fornecedor</span>
        <strong>{{ v.supplier_name || "—" }}</strong>
        <small>CNPJ {{ v.supplier_document || "—" }}</small>
      </div>
      <div class="kv"><span>Número / série</span><strong>{{ v.number || "—" }} / {{ v.series || "—" }}</strong></div>
      <div class="kv"><span>Emissão</span><strong>{{ dateTime(v.issued_at) }}</strong></div>
      <div class="kv"><span>Valor da nota</span><strong class="money">{{ money(v.total) }}</strong>
        <small v-if="Number(v.products_total)">produtos {{ money(v.products_total) }}</small></div>
      <div class="kv"><span>Situação na SEFAZ</span><strong>{{ fiscalStatus.map[v.fiscal_status] ?? "—" }}</strong>
        <small>{{ manifestation.map[v.manifestation] }}</small></div>
      <div class="kv"><span>Destino</span><strong>{{ v.store_name }}</strong><small>{{ v.fiscal_config_name ?? "" }}</small></div>
      <div class="kv kv--key">
        <span>Chave de acesso</span>
        <button type="button" class="key" title="Copiar" @click="copyKey">{{ formatKey(v.access_key) }} <i class="pi pi-copy" /></button>
      </div>
      <div v-if="v.installments?.length" class="kv kv--wide">
        <span>Duplicatas (viram contas a pagar na aprovação)</span>
        <div class="dups">
          <span v-for="dup in v.installments" :key="dup.number" class="dup">{{ date(dup.due_date) }} · <b>{{ money(dup.amount) }}</b></span>
        </div>
      </div>
    </section>

    <!-- Itens -->
    <section class="card">
      <header class="items-head">
        <h2><i class="pi pi-list" /> Itens <small>{{ items.length }}</small></h2>
        <span class="muted">{{ nfeStage.map[stage] }}</span>
      </header>
      <p v-if="!items.length" class="empty">Os itens aparecem quando o XML completo chegar.</p>
      <div v-else class="table-wrap">
        <table class="items">
          <thead>
            <tr>
              <th>#</th><th>Na nota</th><th class="r">Qtd.</th><th class="r">Valor un.</th><th class="r">Total</th>
              <th class="map">Produto no sistema</th><th class="r">Fator</th><th class="r">Entra</th><th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id" :class="{ pending: !item.variant && !item.ignored, ignored: item.ignored }">
              <td class="n">{{ item.item_number }}</td>
              <td class="desc">
                <strong>{{ item.description }}</strong>
                <small>Cód. {{ item.supplier_code || "—" }} · EAN {{ item.barcode || "sem" }}
                  <template v-if="item.taxable_barcode && item.taxable_barcode !== item.barcode"> · trib. {{ item.taxable_barcode }}</template>
                  · NCM {{ item.ncm || "—" }}</small>
                <!-- Produto em volumes (móvel em várias caixas): quantas caixas devem chegar. -->
                <span v-if="item.volumes?.length && !item.ignored" class="vols" :title="volumesHint(item)">
                  <i class="pi pi-box" /> {{ item.volumes.length }} volumes por unidade ·
                  <b>{{ Number(item.stock_quantity) * item.volumes.length }} caixas</b>
                </span>
              </td>
              <td class="r" data-label="Qtd.">{{ quantity(item.quantity) }} <small>{{ item.unit }}</small></td>
              <td class="r" data-label="Valor un.">{{ money(item.unit_value) }}</td>
              <td class="r b" data-label="Total">{{ money(item.total) }}</td>
              <td class="map" data-label="Produto no sistema">
                <span v-if="item.ignored" class="pill pill--neutral">Fora do estoque</span>
                <RelationSelect v-else-if="canMap" :model-value="item.variant" :relation="variantRelation" size="small"
                                placeholder="Escolha o produto" @update:model-value="mapItem(item, $event)" />
                <span v-else-if="item.variant" class="linked"><i class="pi pi-link" /> {{ item.variant_name }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td class="r" data-label="Fator">
                <InputNumber v-if="canMap && item.variant" :model-value="Number(item.conversion_factor)" :min="0.000001"
                             :max-fraction-digits="6" size="small" class="factor" input-class="factor__input"
                             title="Quantas unidades de estoque vêm em 1 unidade da nota (1 CX = 12 UN → 12)"
                             @update:model-value="mapItem(item, item.variant, $event)" />
                <span v-else>{{ item.ignored ? "—" : quantity(item.conversion_factor) }}</span>
              </td>
              <td class="r b" data-label="Entra no estoque">{{ item.ignored ? "—" : quantity(item.stock_quantity) }}</td>
              <td class="act">
                <template v-if="canMap">
                  <Button v-if="item.variant && !item.ignored" icon="pi pi-times" text rounded size="small" severity="danger"
                          title="Desvincular (esquece o vínculo aprendido)" aria-label="Desvincular" @click="unmapItem(item)" />
                  <Button v-if="!item.variant && !item.ignored" icon="pi pi-plus" text rounded size="small"
                          title="Cadastrar produto a partir do item" aria-label="Cadastrar produto"
                          @click="createProduct(item)" />
                  <Button :icon="item.ignored ? 'pi pi-undo' : 'pi pi-eye-slash'" text rounded size="small" severity="secondary"
                          :title="item.ignored ? 'Voltar a usar' : 'Não entra no estoque (uso e consumo)'"
                          :aria-label="item.ignored ? 'Voltar a usar' : 'Ignorar item'" @click="toggleIgnore(item)" />
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <PromptDialog :spec="prompt" @answer="onAnswer" />
  </div>
</template>

<style scoped>
.nfe { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--surface-card); border: 1px solid var(--border); border-radius: 10px; }

.steps { display: flex; list-style: none; margin: 0; padding: 0; gap: 4px; overflow-x: auto; }
.steps li {
  flex: 1 1 0; min-width: 120px; display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  border-bottom: 3px solid var(--border); color: var(--text-muted); font-size: 12.5px; font-weight: 600; white-space: nowrap;
}
.steps .dot {
  display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; font-size: 11px;
  background: var(--surface-hover); color: var(--text-muted);
}
.steps .done { border-color: var(--success); color: var(--text-strong); }
.steps .done .dot { background: var(--success); color: #fff; }
.steps .done .dot i { font-size: 10px; }
.steps .current { border-color: var(--brand); color: var(--text-brand); }
.steps .current .dot { background: var(--brand); color: #fff; }
.steps.off li { opacity: 0.45; }

.next {
  display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 10px;
  background: var(--brand-subtle); color: var(--text-brand); border: 1px solid var(--brand-border);
}
.next > i { font-size: 20px; }
.next p { margin: 0; flex: 1; font-size: 13.5px; color: var(--text-body); }
.next p b { color: var(--text-strong); }
.next--pending_mapping { background: var(--warning-subtle); border-color: transparent; color: var(--warning-text); }
.next--received { background: var(--success-subtle); border-color: transparent; color: var(--success-text); }
.next--cancelled { background: var(--danger-subtle); border-color: transparent; color: var(--danger-text); }
.next--ignored { background: var(--surface-hover); border-color: transparent; color: var(--text-muted); }
.next__more { margin-left: -6px; }

.head { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px 18px; padding: 14px 16px; }
.kv { display: flex; flex-direction: column; gap: 2px; min-width: 0; grid-column: span 1; }
.kv--wide { grid-column: span 2; }
.kv--key { grid-column: span 3; }
.kv > span { font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-subtle); }
.kv strong { font-size: 14px; color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kv small { font-size: 12px; color: var(--text-muted); }
.kv .money { font-size: 16px; }
.key {
  border: 0; background: none; padding: 0; text-align: left; cursor: pointer; color: var(--text-body);
  font: 500 12.5px/1.4 var(--font-mono, monospace);
}
.key i { font-size: 11px; color: var(--text-subtle); }
.dups { display: flex; flex-wrap: wrap; gap: 6px; }
.dup { font-size: 12.5px; padding: 2px 8px; border-radius: 6px; background: var(--surface-hover); }

.items-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px 8px; }
.items-head h2 { margin: 0; font-size: 14.5px; display: flex; align-items: center; gap: 8px; color: var(--text-strong); }
.items-head h2 small { font-size: 12px; color: var(--text-muted); font-weight: 600; }
.empty { padding: 24px 16px; margin: 0; color: var(--text-muted); font-size: 13px; }
.table-wrap { overflow-x: auto; }
.items { width: 100%; border-collapse: collapse; font-size: 13px; }
.items th {
  text-align: left; padding: 8px 10px; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--text-muted); background: var(--surface-sunken, var(--surface-hover)); border-block: 1px solid var(--border-subtle);
}
.items td { padding: 8px 10px; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
.items tr:last-child td { border-bottom: 0; }
.items .r { text-align: right; white-space: nowrap; }
.items .b { font-weight: 600; color: var(--text-strong); }
.items .n { color: var(--text-subtle); width: 32px; }
.items .desc { min-width: 220px; }
.items .desc strong { display: block; color: var(--text-strong); font-weight: 600; }
.items .desc small, .items td small { color: var(--text-muted); font-size: 11.5px; }
.items .map { min-width: 240px; width: 28%; }
.items .act { width: 112px; white-space: nowrap; text-align: right; }
.items tr.pending { background: color-mix(in srgb, var(--warning-subtle) 55%, transparent); }
.items tr.ignored td { color: var(--text-subtle); }
.vols { display: inline-block; margin-top: 4px; padding: 2px 8px; border-radius: 6px;
        background: var(--brand-subtle); color: var(--text-brand); font-size: 11.5px; }
.vols i { font-size: 11px; margin-right: 4px; }
.linked { display: inline-flex; gap: 6px; align-items: center; color: var(--text-strong); font-weight: 600; }
.linked i { color: var(--success-text); font-size: 12px; }
.items .map :deep(.p-select) { width: 100%; }
.factor { width: 84px; }
.factor :deep(.factor__input) { width: 84px; text-align: right; }

@media (max-width: 900px) {
  .head { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kv--wide, .kv--key { grid-column: 1 / -1; }
}
/* Celular: etapas viram só bolinhas (o nome só da etapa atual), o aviso empilha os botões
   e cada item da nota vira um cartão com rótulos. */
@media (max-width: 640px) {
  .steps { gap: 2px; overflow: visible; }
  .steps li { min-width: 0; flex: 0 0 auto; padding: 8px 4px; }
  .steps li.current { flex: 1 1 auto; }
  .steps li:not(.current) .steps__label { display: none; }
  .next { flex-wrap: wrap; position: relative; padding-right: 44px; }
  .next p { flex-basis: calc(100% - 40px); }
  .next > .p-button:not(.next__more) { flex: 1 1 auto; }
  .next__more { position: absolute !important; top: 8px; right: 8px; margin: 0; }
  .head { padding: 12px; gap: 12px; }
  .items thead { display: none; }
  .items, .items tbody, .items tr, .items td { display: block; width: auto; }
  .items tr { position: relative; padding: 10px 12px; border-bottom: 1px solid var(--border-subtle); }
  .items td { padding: 3px 0; border: 0; }
  .items td[data-label] { display: flex; align-items: center; gap: 4px; }
  .items td[data-label]::before { content: attr(data-label); margin-right: auto; font-size: 12px; font-weight: 500;
                                  color: var(--text-muted); }
  .items .n { position: absolute; top: 10px; left: 12px; width: auto; }
  .items .desc { padding-left: 24px; padding-right: 76px; min-width: 0; }
  .items .map { width: auto; min-width: 0; flex-direction: column; align-items: stretch !important; }
  .items .map::before { margin-top: 4px; }
  .items .act { position: absolute; top: 6px; right: 6px; width: auto; }
}
</style>
