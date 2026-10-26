<script setup lang="ts">
/**
 * Casca de todo documento impresso: o que aparece na tela é EXATAMENTE o que sai
 * no papel (ou no PDF, com "Salvar como PDF" na janela de impressão).
 *
 * - formato: A4 retrato, A4 paisagem ou bobina térmica de 80 mm (`@page` muda junto);
 * - cabeçalho com a loja (nome, razão social, CNPJ, endereço) e o título do documento;
 * - rodapé com quem emitiu e quando, e "Página X de Y" (margem da página, no A4);
 * - `?auto=1` na URL abre a impressão sozinha assim que os dados chegam.
 * A barra de cima (voltar, formato, imprimir) não sai na impressão e segue o tema
 * (claro/escuro) do sistema; a FOLHA é sempre papel branco, nos dois temas.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import SelectButton from "primevue/selectbutton";
import { computed, onBeforeUnmount, watch, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";

import { resourceApi } from "@/api/resource";
import { useSession } from "@/stores/session";
import { onlyDigits } from "@/utils/documents";

import { type PrintFormat, rememberFormat } from "./format";

export type { PrintFormat } from "./format";

const props = defineProps<{
  title: string;
  subtitle?: string;
  /** Nome sugerido do arquivo ao salvar PDF (sem extensão). */
  filename: string;
  formats: PrintFormat[];
  ready: boolean;
  storeId?: string | null;
}>();
const format = defineModel<PrintFormat>("format", { required: true });
const route = useRoute();
const router = useRouter();
const session = useSession();

const LABELS: Record<PrintFormat, string> = { a4: "Folha A4", "a4-landscape": "A4 deitado", "80mm": "Bobina 80 mm" };
const ICONS: Record<PrintFormat, string> = { a4: "pi pi-file", "a4-landscape": "pi pi-file", "80mm": "pi pi-receipt" };
const PAGE: Record<PrintFormat, string> = {
  a4: "size: A4 portrait; margin: 14mm 12mm 16mm;",
  "a4-landscape": "size: A4 landscape; margin: 12mm 12mm 14mm;",
  "80mm": "size: 80mm auto; margin: 3mm 3mm 6mm;",
};
const options = computed(() => props.formats.map((f) => ({ label: LABELS[f], value: f, icon: ICONS[f] })));
// Guarda a escolha (só quando a pessoa troca na barra, não o formato que veio na URL).
watch(format, (next, before) => {
  if (before) rememberFormat(String(route.params.doc), next);
});
const thermal = computed(() => format.value === "80mm");

const storeId = computed(() => props.storeId ?? (session.activeStore?.id ?? null));
const store = useQuery({
  queryKey: computed(() => ["print-store", storeId.value]),
  queryFn: () => resourceApi.get("/stores/", storeId.value!),
  enabled: computed(() => Boolean(storeId.value)),
  staleTime: 10 * 60_000,
});
/** Logo da empresa (Configurações da conta); sem ele, o do Starrp. */
const logo = computed(() => session.me?.account?.logo_url || "/logo.svg");

const company = computed(() => {
  const s = (store.data.value ?? {}) as Record<string, string>;
  const cnpj = onlyDigits(s.cnpj ?? "");
  return {
    name: s.name || session.me?.account?.name || "Starrp",
    legal: s.legal_name && s.legal_name !== s.name ? s.legal_name : "",
    cnpj: cnpj.length === 14 ? cnpj.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5") : "",
    address: [[s.street, s.number].filter(Boolean).join(", "), s.district, [s.city, s.state].filter(Boolean).join(" - ")]
      .filter(Boolean).join(" · "),
    phone: s.phone || "",
  };
});
const issued = new Date().toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });

// `@page` não é reativo dentro de <style scoped>: um <style> próprio, trocado a cada formato.
const pageStyle = document.createElement("style");
document.head.appendChild(pageStyle);
watchEffect(() => {
  pageStyle.textContent = `@page { ${PAGE[format.value]} ${thermal.value ? "" : `
    @bottom-left { content: "${company.value.name.replace(/"/g, "")} · ${props.title.replace(/"/g, "")}"; font: 8pt Arial; color: #777; }
    @bottom-right { content: "Página " counter(page) " de " counter(pages); font: 8pt Arial; color: #777; }`} }`;
});
// O nome do arquivo do "Salvar como PDF" sai do título da página.
const previousTitle = document.title;
watchEffect(() => (document.title = props.filename));
onBeforeUnmount(() => {
  pageStyle.remove();
  document.title = previousTitle;
});

function print() {
  window.print();
}
watch(() => props.ready, (ok) => {
  if (ok && route.query.auto === "1") setTimeout(print, 400);
}, { immediate: true });

function back() {
  if (window.opener || history.length <= 1) window.close();
  else router.back();
}
</script>

<template>
  <div class="print-root" :class="`fmt-${format}`">
    <div class="toolbar no-print">
      <Button icon="pi pi-arrow-left" label="Voltar" text severity="secondary" size="small" @click="back" />
      <strong class="toolbar__title">{{ title }}</strong>
      <SelectButton v-if="options.length > 1" v-model="format" :options="options" option-label="label" option-value="value"
                    :allow-empty="false" size="small" class="toolbar__formats" aria-label="Papel">
        <template #option="{ option }"><i :class="option.icon" /> {{ option.label }}</template>
      </SelectButton>
      <span class="toolbar__hint">Para PDF, escolha <b>Salvar como PDF</b> na impressão.</span>
      <Button icon="pi pi-print" label="Imprimir / PDF" size="small" :disabled="!ready" @click="print" />
    </div>

    <div class="sheet">
      <header class="doc-head" :class="{ 'doc-head--thermal': thermal }">
        <div class="company">
          <strong>{{ company.name }}</strong>
          <span v-if="company.legal">{{ company.legal }}</span>
          <span v-if="company.cnpj">CNPJ {{ company.cnpj }}</span>
          <span v-if="company.address">{{ company.address }}</span>
          <span v-if="company.phone">Tel. {{ company.phone }}</span>
        </div>
        <div class="doc-title">
          <h1>{{ title }}</h1>
          <p v-if="subtitle">{{ subtitle }}</p>
        </div>
        <img :src="logo" alt="" class="doc-logo" />
      </header>

      <main class="doc-body">
        <div v-if="!ready" class="loading">Carregando o documento…</div>
        <slot v-else :thermal="thermal" />
      </main>

      <footer class="doc-foot">
        Emitido em {{ issued }} por {{ session.me?.name ?? "—" }} · Starrp
      </footer>
    </div>
  </div>
</template>

<style>
/* Em volta da folha: o tema do sistema (claro/escuro). A folha: cores fixas de papel. */
:root:has(.print-root) body { background: var(--surface-ground); }
.print-root { min-height: 100vh; background: var(--surface-ground); color: #111; font: 10pt/1.4 Arial, Helvetica, sans-serif; }
.print-root .toolbar {
  position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 12px; padding: 8px 16px; flex-wrap: wrap;
  background: var(--surface-card); border-bottom: 1px solid var(--border); font-family: var(--font-sans); color: var(--text-body);
}
.print-root .toolbar__title { font-size: 14px; color: var(--text-strong); }
.print-root .toolbar__hint { margin-left: auto; font-size: 12px; color: var(--text-muted); }
.print-root .toolbar__hint b { color: var(--text-strong); }
.print-root .toolbar__formats .p-togglebutton-content { gap: 6px; }
.print-root .sheet {
  margin: 20px auto; background: #fff; color: #111; color-scheme: light; padding: 14mm 12mm 16mm;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12), 0 0 0 1px var(--border);
}
@media (max-width: 860px) {
  .print-root .toolbar__hint { display: none; }
  .print-root .sheet { margin: 12px auto; max-width: calc(100vw - 24px); overflow-x: auto; }
}
.print-root.fmt-a4 .sheet { width: 210mm; min-height: 297mm; }
.print-root.fmt-a4-landscape .sheet { width: 297mm; min-height: 210mm; padding: 12mm; }
.print-root.fmt-80mm .sheet { width: 80mm; padding: 4mm 3mm; font-size: 8.5pt; }

.doc-head { display: flex; justify-content: space-between; gap: 16px; padding-bottom: 8px; margin-bottom: 12px; border-bottom: 2px solid #111; }
.doc-head .company { display: flex; flex-direction: column; font-size: 8.5pt; color: #444; }
.doc-head .company strong { font-size: 12pt; color: #111; }
.doc-head .doc-title { text-align: right; }
.doc-head h1 { margin: 0; font-size: 15pt; letter-spacing: -0.01em; color: #111; }
.doc-head p { margin: 2px 0 0; font-size: 9pt; color: #444; }
.doc-head { align-items: flex-start; }
.doc-head .doc-title { margin-left: auto; }
.doc-logo { width: 22mm; height: 22mm; object-fit: contain; flex-shrink: 0; }
.doc-head--thermal .doc-logo { order: -1; width: 16mm; height: 16mm; }
.doc-head--thermal .doc-title { margin-left: 0; }
.doc-head--thermal { flex-direction: column; align-items: center; text-align: center; gap: 4px; border-bottom: 1px dashed #111; }
.doc-head--thermal .company { align-items: center; }
.doc-head--thermal .company strong { font-size: 10.5pt; }
.doc-head--thermal .doc-title { text-align: center; }
.doc-head--thermal h1 { font-size: 10pt; text-transform: uppercase; }

.doc-body { display: flex; flex-direction: column; gap: 12px; }
.doc-foot { margin-top: 14px; padding-top: 6px; border-top: 1px solid #ccc; font-size: 7.5pt; color: #666; text-align: center; }
.loading { padding: 40px; text-align: center; color: #666; }

/* Peças comuns dos documentos */
.doc-section h2 { margin: 0 0 6px; font-size: 10.5pt; text-transform: uppercase; letter-spacing: 0.04em; color: #111;
                  border-bottom: 1px solid #999; padding-bottom: 3px; }
.doc-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.doc-kpis > div { border: 1px solid #bbb; border-radius: 4px; padding: 6px 8px; }
.doc-kpis small { display: block; font-size: 7.5pt; color: #555; text-transform: uppercase; }
.doc-kpis b { font-size: 12pt; }
.doc-note { font-size: 8.5pt; color: #444; }
.doc-signatures { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr)); gap: 24px; margin-top: 28px; }
.doc-signatures div { border-top: 1px solid #111; padding-top: 4px; text-align: center; font-size: 8.5pt; }
.doc-total-box { margin-left: auto; min-width: 230px; border: 1.5px solid #111; border-radius: 4px; }
.doc-total-box div { display: flex; justify-content: space-between; padding: 4px 8px; border-bottom: 1px solid #ddd; }
.doc-total-box div:last-child { border-bottom: 0; font-size: 12pt; font-weight: 700; background: #f3f4f6; }
.neg { color: #b91c1c; }

/* Tabelas dos documentos (PrintTable e tabelas montadas à mão, como a DRE) */
.pt { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
.pt th { text-align: left; padding: 4px 6px; background: #f3f4f6; border-top: 1px solid #999; border-bottom: 1px solid #999;
         font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.03em; color: #333; }
.pt td { padding: 4px 6px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
.pt tbody tr:nth-child(even) td { background: #fafafa; }
.pt tfoot td { border-top: 1.5px solid #111; border-bottom: 0; font-weight: 700; background: #f3f4f6; }
.pt .r { text-align: right; white-space: nowrap; }
.pt-empty { margin: 0; padding: 8px; font-size: 8.5pt; color: #666; font-style: italic; }
.pt-thermal { list-style: none; margin: 0; padding: 0; }
.pt-thermal li { padding: 3px 0; border-bottom: 1px dotted #999; }
.pt-thermal__main { font-weight: 700; }
.pt-thermal__rest { display: flex; flex-wrap: wrap; gap: 0 8px; font-size: 7.5pt; }

/* Bobina: tudo em coluna, sem caixas */
.fmt-80mm .doc-kpis { grid-template-columns: 1fr 1fr; }
.fmt-80mm .doc-section h2 { font-size: 8.5pt; border-bottom: 1px dashed #111; }
.fmt-80mm .doc-total-box { min-width: 0; width: 100%; border: 0; border-radius: 0; border-top: 1px dashed #111; }
.fmt-80mm .doc-foot { border-top: 1px dashed #111; }

@media print {
  .no-print { display: none !important; }
  html, body, #app { height: auto !important; background: #fff !important; color-scheme: light; }
  .print-root { background: #fff; min-height: 0; }
  .print-root .sheet { margin: 0; box-shadow: none; padding: 0 !important; width: auto !important; min-height: 0 !important; }
  /* No A4 o rodapé vai na margem da página (com o número); este só aparece na bobina. */
  .print-root:not(.fmt-80mm) .doc-foot { display: none; }
  .doc-section, .doc-kpis, .doc-total-box, .doc-signatures { break-inside: avoid; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
}
</style>
