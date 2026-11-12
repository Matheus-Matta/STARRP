<script setup lang="ts">
/**
 * DANFE no layout de mercado (Manual de Orientação do Contribuinte):
 * - NF-e (55), folha A4: canhoto, emitente, quadro DANFE (entrada/saída, nº, série), chave com
 *   código de barras, natureza da operação e protocolo, destinatário, fatura/duplicatas, cálculo
 *   do imposto, transportador/volumes, produtos com a tributação de cada linha e dados adicionais;
 * - NFC-e (65), bobina 80 mm: DANFE NFC-e com itens, totais, pagamentos e troco, consulta pela
 *   chave, consumidor, protocolo e QR Code.
 * Marcas: homologação (SEM VALOR FISCAL), contingência, nota não autorizada e nota cancelada.
 *
 * `/imprimir/danfe/<nota>`: pela tela de notas (`/fiscal/invoices/<nota>/danfe/`, módulo fiscal);
 * com `?venda=<pedido>`, pelo pedido (quem vê o pedido imprime a nota dele).
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, ref, watchEffect } from "vue";
import { useRoute } from "vue-router";

import { http } from "@/api/http";
import { formatDocument } from "@/utils/documents";
import { date, dateTime, money, quantity } from "@/utils/format";
import { applyMask, formatPhone, MASKS } from "@/utils/masks";

import PrintShell, { type PrintFormat } from "../PrintShell.vue";

type Danfe = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const props = defineProps<{ id: string; initialFormat?: PrintFormat }>();
const route = useRoute();
const saleId = String(route.query.venda ?? "");
const url = saleId ? `/sales/${saleId}/invoices/${props.id}/danfe/` : `/fiscal/invoices/${props.id}/danfe/`;
const format = ref<PrintFormat>(props.initialFormat ?? "a4");
const query = useQuery({
  queryKey: ["print-danfe", saleId, props.id],
  queryFn: async () => (await http.get<Danfe>(url)).data,
});
const n = computed(() => query.data.value);
const nfce = computed(() => Boolean(n.value?.nfce));
// NF-e só sai em A4 (o DANFE simplificado em bobina não é o padrão do pedido).
watchEffect(() => {
  if (n.value && !nfce.value && format.value !== "a4") format.value = "a4";
});
const formats = computed<PrintFormat[]>(() => (nfce.value ? ["80mm", "a4"] : ["a4"]));

const issuer = computed(() => (n.value?.issuer ?? {}) as Record<string, string>);
const dest = computed(() => n.value?.recipient as Record<string, string> | null | undefined);
const taxes = computed(() => (n.value?.tax_totals ?? {}) as Record<string, string>);
const transport = computed(() => (n.value?.transport ?? {}) as Record<string, string>);

const doc = (v: unknown) => (v ? formatDocument(String(v)) : "");
const cep = (v: unknown) => (v ? applyMask(v, MASKS.cep) : "");
const phone = (v: unknown) => (v ? formatPhone(v) : "");
const time = (v: unknown) => (v ? new Date(String(v)).toLocaleTimeString("pt-BR") : "");
/** Valor sem "R$" nos quadros do DANFE (o cabeçalho do campo já diz que é valor). */
const val = (v: unknown) => money(v ?? 0).replace(/^R\$\s?/, "");
const numberFmt = computed(() => String(n.value?.number ?? 0).padStart(9, "0").replace(/(\d{3})(\d{3})(\d{3})/, "$1.$2.$3"));
const seriesFmt = computed(() => String(n.value?.series ?? 0).padStart(3, "0"));
const key = computed(() => String(n.value?.access_key ?? "").replace(/(\d{4})(?=\d)/g, "$1 "));
const city = (o?: Record<string, string> | null) => (o?.city ? o.city : "");

const STATUS: Record<string, string> = { draft: "em rascunho", processing: "em processamento", rejected: "rejeitada",
                                          error: "com erro de comunicação" };
const status = computed(() => String(n.value?.status ?? ""));
const cancelled = computed(() => status.value === "cancelled");
const notAuthorized = computed(() => !["authorized", "cancelled"].includes(status.value));
const watermark = computed(() => (cancelled.value ? "CANCELADA" : n.value?.homologation || notAuthorized.value ? "SEM VALOR FISCAL" : ""));
const banners = computed(() => {
  const out: string[] = [];
  if (cancelled.value) out.push(`NOTA CANCELADA${n.value?.cancelled_at ? ` EM ${dateTime(n.value.cancelled_at)}` : ""}`
    + (n.value?.cancel_protocol ? ` · PROTOCOLO ${n.value.cancel_protocol}` : ""));
  if (notAuthorized.value) out.push(`NOTA ${(STATUS[status.value] ?? status.value).toUpperCase()} — SEM VALOR FISCAL`);
  if (n.value?.homologation) out.push(`EMITIDA EM AMBIENTE DE HOMOLOGAÇÃO — SEM VALOR FISCAL`);
  if (n.value?.contingency) out.push(nfce.value ? "EMITIDA EM CONTINGÊNCIA — Pendente de autorização"
                                                 : "DANFE EM CONTINGÊNCIA — impresso em decorrência de problemas técnicos");
  return out;
});
const cst = (item: Record<string, string>) => `${item.origin ?? "0"}${item.csosn || item.cst_icms || ""}`;
const additional = computed(() => {
  const parts: string[] = [];
  if (n.value?.additional_info) parts.push(String(n.value.additional_info));
  if (issuer.value.crt === "1") parts.push("DOCUMENTO EMITIDO POR ME OU EPP OPTANTE PELO SIMPLES NACIONAL. NÃO GERA DIREITO A CRÉDITO FISCAL DE IPI.");
  if (Number(n.value?.approx_tax_total)) parts.push(`Valor aproximado dos tributos: R$ ${val(n.value!.approx_tax_total)} (Lei 12.741/2012).`);
  if (n.value?.sale_number) parts.push(`Pedido ${n.value.sale_number}.`);
  if (n.value?.homologation) parts.push("NF-e emitida em ambiente de homologação — sem valor fiscal.");
  return parts;
});
const paymentsTotal = computed(() => (n.value?.payments ?? []).reduce((a: number, p: { amount: string }) => a + Number(p.amount), 0));
</script>

<template>
  <PrintShell v-model:format="format" :title="n ? `DANFE ${nfce ? 'NFC-e' : 'NF-e'}` : 'DANFE'" :formats="formats" :ready="!!n"
              :store-id="n?.store" :filename="`danfe-${n?.access_key || n?.number || id}`" bare>
    <template v-if="n" #default="{ thermal }">
      <!-- ============ NFC-e (bobina e A4 no mesmo desenho) ============ -->
      <div v-if="nfce" class="nfce" :class="{ 'nfce--a4': !thermal }">
        <div v-if="watermark" class="wm wm--small">{{ watermark }}</div>
        <header class="nfce__head">
          <strong>{{ issuer.legal_name || n.fiscal_config_name }}</strong>
          <span>CNPJ {{ doc(issuer.cnpj) }}<template v-if="issuer.state_registration"> · IE {{ issuer.state_registration }}</template></span>
          <span>{{ issuer.address }}</span>
          <p class="nfce__title">Documento Auxiliar da Nota Fiscal de Consumidor Eletrônica</p>
        </header>
        <p v-for="b in banners" :key="b" class="nfce__banner">{{ b }}</p>

        <table class="nfce__items">
          <thead><tr><th>Código</th><th>Descrição</th><th class="r">Qtde</th><th>UN</th><th class="r">Vl Unit</th><th class="r">Vl Total</th></tr></thead>
          <tbody>
            <tr v-for="item in n.items" :key="item.id">
              <td>{{ item.code }}</td><td>{{ item.description }}</td><td class="r">{{ quantity(item.quantity) }}</td>
              <td>{{ item.unit }}</td><td class="r">{{ val(item.unit_price) }}</td><td class="r">{{ val(item.total) }}</td>
            </tr>
          </tbody>
        </table>

        <div class="nfce__totals">
          <div><span>Qtde. total de itens</span><span>{{ n.items.length }}</span></div>
          <div><span>Valor total R$</span><span>{{ val(n.products_total) }}</span></div>
          <div v-if="Number(n.discount_total)"><span>Desconto R$</span><span>{{ val(n.discount_total) }}</span></div>
          <div v-if="Number(n.freight_total)"><span>Frete R$</span><span>{{ val(n.freight_total) }}</span></div>
          <div class="strong"><span>Valor a pagar R$</span><span>{{ val(n.total) }}</span></div>
          <div class="head"><span>FORMA DE PAGAMENTO</span><span>VALOR PAGO R$</span></div>
          <div v-for="p in n.payments" :key="p.id"><span>{{ p.method_name }}<template v-if="p.installments > 1"> ({{ p.installments }}x)</template></span>
            <span>{{ val(p.amount) }}</span></div>
          <div v-if="Number(n.change_amount)"><span>Troco R$</span><span>{{ val(n.change_amount) }}</span></div>
        </div>

        <section class="nfce__block">
          <b>Consulte pela Chave de Acesso em</b>
          <span>{{ n.consult_url || issuer.portal_url || "o portal da SEFAZ do estado" }}</span>
          <span class="key">{{ key || "—" }}</span>
        </section>
        <section class="nfce__block">
          <b>CONSUMIDOR</b>
          <template v-if="dest?.document || dest?.name">
            <span>{{ dest.document ? `${dest.document.replace(/\D/g, '').length > 11 ? 'CNPJ' : 'CPF'} ${doc(dest.document)}` : "" }}
              {{ dest.name }}</span>
            <span v-if="dest.address_line">{{ dest.address_line }}, {{ dest.district }}, {{ city(dest) }}/{{ dest.state }}</span>
          </template>
          <span v-else>CONSUMIDOR NÃO IDENTIFICADO</span>
        </section>
        <section class="nfce__block">
          <b>NFC-e nº {{ String(n.number ?? 0).padStart(9, "0") }} Série {{ seriesFmt }} {{ dateTime(n.issued_at) }}</b>
          <span v-if="n.protocol">Protocolo de autorização: {{ n.protocol }}</span>
          <span v-if="n.authorized_at">Data de autorização: {{ dateTime(n.authorized_at) }}</span>
        </section>
        <!-- SVG gerado no backend (labels.qr_svg) a partir do QR da nota. -->
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div v-if="n.qr_svg" class="nfce__qr" v-html="n.qr_svg" />
        <p v-if="Number(n.approx_tax_total)" class="nfce__note">Tributos totais incidentes (Lei Federal 12.741/2012):
          R$ {{ val(n.approx_tax_total) }}</p>
        <p v-if="n.additional_info" class="nfce__note">{{ n.additional_info }}</p>
      </div>

      <!-- ============ NF-e — DANFE retrato A4 ============ -->
      <div v-else class="danfe">
        <div v-if="watermark" class="wm">{{ watermark }}</div>

        <!-- Canhoto -->
        <div class="row stub">
          <div class="box grow">
            <label>Recebemos de {{ issuer.legal_name }} os produtos/serviços constantes da nota fiscal indicada ao lado.
              Emissão: {{ date(n.issued_at) }} · Destinatário: {{ dest?.name || "—" }} · Valor total: R$ {{ val(n.total) }}</label>
            <div class="row inner">
              <div class="box w30"><label>Data de recebimento</label><span>&nbsp;</span></div>
              <div class="box grow"><label>Identificação e assinatura do recebedor</label><span>&nbsp;</span></div>
            </div>
          </div>
          <div class="box w20 center"><strong>NF-e</strong><span>Nº {{ numberFmt }}</span><span>Série {{ seriesFmt }}</span></div>
        </div>
        <div class="cut" />

        <p v-for="b in banners" :key="b" class="banner">{{ b }}</p>

        <!-- Emitente / DANFE / Chave -->
        <div class="row head">
          <div class="box w40 issuer">
            <strong>{{ issuer.legal_name || n.fiscal_config_name }}</strong>
            <span v-if="issuer.trade_name && issuer.trade_name !== issuer.legal_name">{{ issuer.trade_name }}</span>
            <span>{{ issuer.address_line }}</span>
            <span>{{ issuer.district }}<template v-if="issuer.zip_code"> · CEP {{ cep(issuer.zip_code) }}</template></span>
            <span>{{ issuer.city }}<template v-if="issuer.state"> - {{ issuer.state }}</template>
              <template v-if="issuer.phone"> · Fone {{ phone(issuer.phone) }}</template></span>
          </div>
          <div class="box w20 center danfe-box">
            <strong class="big">DANFE</strong>
            <small>Documento Auxiliar da Nota Fiscal Eletrônica</small>
            <div class="io"><small>0 - Entrada<br />1 - Saída</small><b class="io__box">{{ n.direction }}</b></div>
            <b>Nº {{ numberFmt }}</b><b>Série {{ seriesFmt }}</b><small>Folha 1/1</small>
          </div>
          <div class="box grow">
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div v-if="n.barcode_svg" class="barcode" v-html="n.barcode_svg" />
            <label>Chave de acesso</label>
            <span class="key">{{ key || "—" }}</span>
            <small class="center">Consulta de autenticidade no portal nacional da NF-e www.nfe.fazenda.gov.br/portal ou no
              site da SEFAZ autorizadora</small>
          </div>
        </div>
        <div class="row">
          <div class="box w60"><label>Natureza da operação</label><span>{{ n.operation_nature }}</span></div>
          <div class="box grow"><label>Protocolo de autorização de uso</label>
            <span>{{ n.protocol || "—" }}<template v-if="n.authorized_at"> · {{ dateTime(n.authorized_at) }}</template></span></div>
        </div>
        <div class="row">
          <div class="box w33"><label>Inscrição estadual</label><span>{{ issuer.state_registration || "—" }}</span></div>
          <div class="box w33"><label>Inscrição estadual do subst. trib.</label><span>&nbsp;</span></div>
          <div class="box grow"><label>CNPJ</label><span>{{ doc(issuer.cnpj) }}</span></div>
        </div>

        <h3>Destinatário / remetente</h3>
        <div class="row">
          <div class="box grow"><label>Nome / razão social</label><span>{{ dest?.name || "CONSUMIDOR NÃO IDENTIFICADO" }}</span></div>
          <div class="box w20"><label>CNPJ / CPF</label><span>{{ doc(dest?.document) || "—" }}</span></div>
          <div class="box w15"><label>Data da emissão</label><span>{{ date(n.issued_at) }}</span></div>
        </div>
        <div class="row">
          <div class="box grow"><label>Endereço</label><span>{{ dest?.address_line || "—" }}</span></div>
          <div class="box w20"><label>Bairro / distrito</label><span>{{ dest?.district || "—" }}</span></div>
          <div class="box w10"><label>CEP</label><span>{{ cep(dest?.zip_code) || "—" }}</span></div>
          <div class="box w15"><label>Data da saída</label><span>{{ date(n.authorized_at || n.issued_at) }}</span></div>
        </div>
        <div class="row">
          <div class="box grow"><label>Município</label><span>{{ city(dest) || "—" }}</span></div>
          <div class="box w15"><label>Fone / fax</label><span>{{ phone(dest?.phone) || "—" }}</span></div>
          <div class="box w5"><label>UF</label><span>{{ dest?.state || "—" }}</span></div>
          <div class="box w15"><label>Inscrição estadual</label><span>{{ dest?.state_registration || "—" }}</span></div>
          <div class="box w15"><label>Hora da saída</label><span>{{ time(n.authorized_at || n.issued_at) }}</span></div>
        </div>

        <template v-if="n.duplicates.length">
          <h3>Fatura / duplicatas</h3>
          <div class="row dups">
            <div v-for="d in n.duplicates" :key="d.number" class="box dup">
              <span>Nº {{ d.number }}</span><span>Venc. {{ date(d.due_date) }}</span><b>R$ {{ val(d.amount) }}</b>
            </div>
          </div>
        </template>

        <h3>Cálculo do imposto</h3>
        <div class="row">
          <div class="box grow r"><label>Base de cálc. do ICMS</label><span>{{ val(taxes.icms_base) }}</span></div>
          <div class="box grow r"><label>Valor do ICMS</label><span>{{ val(taxes.icms_value) }}</span></div>
          <div class="box grow r"><label>Base de cálc. ICMS S.T.</label><span>{{ val(taxes.icms_st_base) }}</span></div>
          <div class="box grow r"><label>Valor do ICMS subst.</label><span>{{ val(taxes.icms_st_value) }}</span></div>
          <div class="box grow r"><label>V. aprox. tributos</label><span>{{ val(n.approx_tax_total) }}</span></div>
          <div class="box grow r"><label>Valor total dos produtos</label><span>{{ val(n.products_total) }}</span></div>
        </div>
        <div class="row">
          <div class="box grow r"><label>Valor do frete</label><span>{{ val(n.freight_total) }}</span></div>
          <div class="box grow r"><label>Valor do seguro</label><span>{{ val(taxes.insurance) }}</span></div>
          <div class="box grow r"><label>Desconto</label><span>{{ val(n.discount_total) }}</span></div>
          <div class="box grow r"><label>Outras despesas</label><span>{{ val(taxes.other_expenses) }}</span></div>
          <div class="box grow r"><label>Valor total do IPI</label><span>{{ val(taxes.ipi_value) }}</span></div>
          <div class="box grow r total"><label>Valor total da nota</label><span>{{ val(n.total) }}</span></div>
        </div>

        <h3>Transportador / volumes transportados</h3>
        <div class="row">
          <div class="box grow"><label>Nome / razão social</label><span>{{ transport.name }}&nbsp;</span></div>
          <div class="box w25"><label>Frete</label><span>{{ transport.mode }}</span></div>
          <div class="box w10"><label>Código ANTT</label><span>{{ transport.antt || "" }}&nbsp;</span></div>
          <div class="box w10"><label>Placa do veículo</label><span>{{ transport.plate || "" }}&nbsp;</span></div>
          <div class="box w5"><label>UF</label><span>{{ transport.plate_state || "" }}&nbsp;</span></div>
          <div class="box w15"><label>CNPJ / CPF</label><span>{{ doc(transport.document) }}&nbsp;</span></div>
        </div>
        <div class="row">
          <div class="box grow"><label>Quantidade</label><span>{{ transport.volumes || "" }}&nbsp;</span></div>
          <div class="box grow"><label>Espécie</label><span>{{ transport.species || "" }}&nbsp;</span></div>
          <div class="box grow"><label>Marca</label><span>{{ transport.brand || "" }}&nbsp;</span></div>
          <div class="box grow"><label>Numeração</label><span>{{ transport.numbering || "" }}&nbsp;</span></div>
          <div class="box grow"><label>Peso bruto</label><span>{{ transport.gross_weight || "" }}&nbsp;</span></div>
          <div class="box grow"><label>Peso líquido</label><span>{{ transport.net_weight || "" }}&nbsp;</span></div>
        </div>

        <h3>Dados dos produtos / serviços</h3>
        <table class="items">
          <thead>
            <tr><th>Código</th><th>Descrição do produto / serviço</th><th>NCM/SH</th><th>O/CST</th><th>CFOP</th><th>UN</th>
              <th class="r">Qtde</th><th class="r">V. unit.</th><th class="r">V. desc.</th><th class="r">V. total</th>
              <th class="r">BC ICMS</th><th class="r">V. ICMS</th><th class="r">V. IPI</th><th class="r">Alíq. ICMS</th>
              <th class="r">Alíq. IPI</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in n.items" :key="item.id">
              <td>{{ item.code }}</td><td class="desc">{{ item.description }}</td><td>{{ item.ncm }}</td><td>{{ cst(item) }}</td>
              <td>{{ item.cfop }}</td><td>{{ item.unit }}</td><td class="r">{{ quantity(item.quantity) }}</td>
              <td class="r">{{ val(item.unit_price) }}</td><td class="r">{{ val(item.discount) }}</td><td class="r">{{ val(item.total) }}</td>
              <td class="r">{{ val(item.icms_base) }}</td><td class="r">{{ val(item.icms_value) }}</td><td class="r">0,00</td>
              <td class="r">{{ Number(item.icms_rate ?? 0).toLocaleString("pt-BR", { minimumFractionDigits: 2 }) }}</td>
              <td class="r">0,00</td>
            </tr>
          </tbody>
        </table>

        <h3>Dados adicionais</h3>
        <div class="row extra">
          <div class="box w65"><label>Informações complementares</label>
            <p v-for="(line, i) in additional" :key="i">{{ line }}</p>
            <p v-if="!additional.length">&nbsp;</p>
          </div>
          <div class="box grow"><label>Reservado ao fisco</label><span>&nbsp;</span></div>
        </div>
        <p v-if="Number(paymentsTotal)" class="pays">Pagamento:
          <template v-for="(p, i) in n.payments" :key="p.id">{{ i ? " · " : "" }}{{ p.method_name }}
            <template v-if="p.installments > 1">({{ p.installments }}x) </template>R$ {{ val(p.amount) }}</template>
        </p>
      </div>
    </template>
  </PrintShell>
</template>

<style scoped>
/* ---------- marca d'água ---------- */
.danfe, .nfce { position: relative; }
.wm { position: absolute; inset: 30% 0 auto; text-align: center; font: 900 54pt/1 Arial, sans-serif; color: rgba(185, 28, 28, 0.13);
      transform: rotate(-28deg); pointer-events: none; z-index: 0; white-space: nowrap; }
.wm--small { font-size: 26pt; inset: 40% 0 auto; }

/* ---------- NF-e A4 ---------- */
.danfe { font: 7.5pt/1.25 Arial, Helvetica, sans-serif; color: #000; }
.danfe h3 { margin: 5px 0 1px; font: 700 7pt/1 Arial, sans-serif; text-transform: uppercase; }
.row { display: flex; }
.row + .row, .head + .row { margin-top: -1px; }
.box { border: 1px solid #000; padding: 1px 4px 2px; min-height: 22px; display: flex; flex-direction: column; min-width: 0; }
.box + .box { margin-left: -1px; }
.box label { font-size: 5.6pt; text-transform: uppercase; color: #222; line-height: 1.2; }
.box span, .box p { font-size: 8pt; margin: 0; overflow-wrap: anywhere; }
.box.r span { text-align: right; }
.box.total span { font-weight: 700; }
.grow { flex: 1; }
.w5 { width: 5%; } .w10 { width: 10%; } .w15 { width: 15%; } .w20 { width: 20%; } .w25 { width: 25%; } .w30 { width: 30%; }
.w33 { width: 33.3%; } .w40 { width: 40%; } .w60 { width: 60%; } .w65 { width: 65%; }
.center { align-items: center; justify-content: center; text-align: center; }
.stub .inner { margin-top: 3px; }
.stub .inner .box { border-width: 1px 1px 0 0; }
.stub .inner .box:first-child { border-left: 0; }
.cut { border-top: 1px dashed #000; margin: 5px 0; }
.banner { margin: 0 0 4px; padding: 3px; border: 2px solid #b91c1c; color: #b91c1c; font: 700 8.5pt Arial, sans-serif; text-align: center; }
.issuer { justify-content: center; gap: 1px; }
.issuer strong { font-size: 10pt; }
.issuer span { font-size: 7.5pt; }
.danfe-box { gap: 1px; }
.danfe-box .big { font-size: 13pt; }
.danfe-box small { font-size: 6.5pt; }
.io { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
.io__box { border: 1px solid #000; padding: 1px 6px; font-size: 11pt; }
.barcode { margin: 2px auto; width: 100%; max-width: 95mm; }
.barcode :deep(svg) { width: 100%; height: 12mm; display: block; }
.key { font: 700 8.5pt/1.3 monospace; text-align: center; letter-spacing: 0.02em; }
.dups { flex-wrap: wrap; }
.dup { width: 16.66%; font-size: 7pt; }
.dup span { font-size: 7pt; }
.items { width: 100%; border-collapse: collapse; font-size: 6.6pt; }
.items th, .items td { border: 1px solid #000; padding: 1px 2px; vertical-align: top; }
.items th { font-size: 5.6pt; text-transform: uppercase; font-weight: 400; }
.items .desc { width: 30%; }
.items .r, .r { text-align: right; }
.extra .box { min-height: 26mm; }
.extra p { font-size: 7pt; }
.pays { margin: 4px 0 0; font-size: 7pt; }

/* ---------- NFC-e ---------- */
.nfce { font: 8pt/1.3 Arial, Helvetica, sans-serif; color: #000; }
.nfce--a4 { max-width: 110mm; margin: 0 auto; font-size: 9pt; }
.nfce__head { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 1px; padding-bottom: 4px;
              border-bottom: 1px dashed #000; }
.nfce__head strong { font-size: 9.5pt; }
.nfce__title { margin: 4px 0 0; font-weight: 700; }
.nfce__banner { margin: 4px 0; padding: 2px; border: 1px solid #000; font-weight: 700; text-align: center; }
.nfce__items { width: 100%; border-collapse: collapse; margin-top: 4px; font-size: 7.2pt; }
.nfce__items th { text-align: left; border-bottom: 1px solid #000; font-weight: 700; }
.nfce__items td { padding: 1px 0; vertical-align: top; }
.nfce__items .r { text-align: right; }
.nfce__totals { border-top: 1px dashed #000; margin-top: 4px; padding-top: 3px; }
.nfce__totals > div { display: flex; justify-content: space-between; }
.nfce__totals .strong { font-weight: 700; }
.nfce__totals .head { margin-top: 3px; font-weight: 700; font-size: 7pt; }
.nfce__block { display: flex; flex-direction: column; align-items: center; text-align: center; border-top: 1px dashed #000;
               margin-top: 4px; padding-top: 3px; overflow-wrap: anywhere; }
.nfce__qr { width: 32mm; margin: 4px auto; }
.nfce__qr :deep(svg) { width: 100%; height: auto; display: block; }
.nfce__note { margin: 3px 0 0; text-align: center; font-size: 7pt; }

@media print {
  .danfe .row, .items tr { break-inside: avoid; }
}
</style>
