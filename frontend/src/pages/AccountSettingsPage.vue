<script setup lang="ts">
/**
 * Configurações da conta — uma página só, do administrador:
 * empresa · PDV e caixa (vale para TODAS as lojas) · estoque · plano e módulos (leitura).
 * Ajuste fino de uma loja continua em Configurações → Lojas. Ctrl+S salva.
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import Button from "primevue/button";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { http } from "@/api/http";
import PageHeader from "@/components/common/PageHeader.vue";
import SectionCard from "@/components/common/SectionCard.vue";
import FormField from "@/components/resource/FormField.vue";
import { useNotify } from "@/composables/useNotify";
import { useSession } from "@/stores/session";
import { choices, type FieldDef } from "@/resources/types";

type Settings = {
  account: Record<string, unknown>; pdv: Record<string, unknown>; stock: Record<string, unknown>;
  plan: { name: string; status: string; modules: string[]; stores: number };
};
type Section = "account" | "pdv" | "stock";

const notify = useNotify();
const client = useQueryClient();
const query = useQuery({
  queryKey: ["account-settings"],
  queryFn: async () => (await http.get<Settings>("/account/settings/")).data,
});
const values = ref<Record<Section, Record<string, unknown>>>({ account: {}, pdv: {}, stock: {} });
const original = ref("");
const errors = ref<Record<string, string>>({});
const saving = ref(false);

/* Logo: o servidor recorta o centro e deixa em 1080×1080 (quadrado, PNG). */
const session = useSession();
const logoInput = ref<HTMLInputElement>();
const logoBusy = ref(false);
const logoUrl = computed(() => (query.data.value?.account.logo_url as string | null) ?? null);
async function sendLogo(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  logoBusy.value = true;
  try {
    await http.post("/account/logo/", form);
    await Promise.all([query.refetch(), session.load()]);
    notify.success("Logo atualizado", "Já aparece nas impressões.");
  } catch (error) {
    notify.error(error, "Logo não enviado");
  } finally {
    logoBusy.value = false;
    if (logoInput.value) logoInput.value.value = "";
  }
}
async function removeLogo() {
  logoBusy.value = true;
  try {
    await http.delete("/account/logo/");
    await Promise.all([query.refetch(), session.load()]);
    notify.success("Logo removido", "As impressões voltam a usar o logo do Starrp.");
  } catch (error) {
    notify.error(error, "Logo não removido");
  } finally {
    logoBusy.value = false;
  }
}

watch(() => query.data.value, (data) => {
  if (!data) return;
  values.value = { account: { ...data.account }, pdv: { ...data.pdv }, stock: { ...data.stock } };
  original.value = JSON.stringify(values.value);
}, { immediate: true });
const dirty = computed(() => original.value !== "" && JSON.stringify(values.value) !== original.value);

const picking = choices({ fefo: "FEFO (vence primeiro, sai primeiro)", fifo: "FIFO (entrou primeiro, sai primeiro)" });
const SECTIONS: { key: Section; title: string; icon: string; description: string; fields: FieldDef[] }[] = [
  { key: "account", title: "Empresa", icon: "pi pi-building",
    description: "Dados da empresa titular da conta (cada filial tem os seus em Filiais).", fields: [
      { name: "name", label: "Nome da empresa", type: "text", required: true, span: 3 },
      { name: "document", label: "CNPJ / CPF", type: "document", span: 3 },
      { name: "email", label: "E-mail", type: "email", span: 3 },
      { name: "phone", label: "Telefone", type: "phone", span: 2 },
      { name: "timezone", label: "Fuso horário", type: "select", span: 1, options: [
        { label: "Brasília", value: "America/Sao_Paulo" }, { label: "Manaus", value: "America/Manaus" },
        { label: "Cuiabá", value: "America/Cuiaba" }, { label: "Rio Branco", value: "America/Rio_Branco" },
        { label: "Fernando de Noronha", value: "America/Noronha" }] },
    ] },
  { key: "pdv", title: "PDV e caixa", icon: "pi pi-shopping-cart",
    description: "Vale para TODAS as filiais ao salvar. Uma filial diferente das outras se ajusta em Filiais.", fields: [
      { name: "require_open_cash_session", label: "Exige caixa aberto para vender", type: "boolean", span: 3 },
      { name: "cash_closing_tolerance", label: "Tolerância no fechamento (R$)", type: "money", span: 3,
        hint: "Diferença até este valor fecha direto; acima, vai para o gerente aprovar." },
      { name: "require_seller", label: "Exige vendedor em toda venda", type: "boolean", span: 3 },
      { name: "pdv_lock_minutes", label: "Bloquear a tela do caixa parado (min)", type: "number", span: 3,
        hint: "0 = não bloqueia sozinho. Volta com a senha do operador." },
      { name: "auto_print_receipt", label: "Imprimir o recibo ao concluir a venda", type: "boolean", span: 3 },
      { name: "print_cancellation_receipt", label: "Imprimir comprovante de cancelamento", type: "boolean", span: 3 },
    ] },
  { key: "stock", title: "Estoque", icon: "pi pi-box",
    description: "Como o estoque sai e o que acontece com vencidos e saldo negativo.", fields: [
      { name: "picking_strategy", label: "Ordem de saída", type: "select", options: picking.options, span: 3 },
      { name: "expiry_warning_days", label: "Avisar vencimento com (dias)", type: "number", span: 3 },
      { name: "block_expired", label: "Bloquear venda de lote vencido", type: "boolean", span: 3 },
      { name: "allow_negative_stock", label: "Permitir vender sem saldo (estoque negativo)", type: "boolean", span: 3 },
    ] },
];

async function save() {
  if (!dirty.value || saving.value) return;
  saving.value = true;
  errors.value = {};
  try {
    const { data } = await http.patch<Settings>("/account/settings/", values.value);
    client.setQueryData(["account-settings"], data);
    notify.success("Configurações salvas", "O PDV das filiais pega as novas regras na próxima abertura.");
  } catch (error) {
    const details = (error as { response?: { data?: { error?: { message?: Record<string, Record<string, string[]>> } } } })
      .response?.data?.error?.message;
    if (details && typeof details === "object") {
      for (const [section, fields] of Object.entries(details)) {
        for (const [field, msgs] of Object.entries(fields ?? {})) errors.value[`${section}.${field}`] = [msgs].flat().join(" ");
      }
    }
    notify.error(error, "Configurações não salvas");
  } finally {
    saving.value = false;
  }
}
function discard() {
  if (original.value) values.value = JSON.parse(original.value);
}
function onKey(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void save();
  }
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

const MODULES: Record<string, string> = {
  stock: "Estoque e compras", finance: "Financeiro", fiscal: "Fiscal (NFC-e/NF-e)", inbound_nfe: "NF-e de entrada",
  assets: "Patrimônio", sync: "Servidor local", base: "Base (PDV, vendas, produtos, clientes)",
};
</script>

<template>
  <div class="page">
    <PageHeader title="Configurações da conta" icon="pi pi-cog"
                subtitle="Tudo que vale para a empresa inteira, num lugar só. Só o administrador vê esta página." />
    <div v-if="query.isPending.value" class="muted"><i class="pi pi-spin pi-spinner" /> Carregando…</div>
    <template v-else-if="query.data.value">
      <SectionCard v-for="section in SECTIONS" :key="section.key" :title="section.title" :icon="section.icon"
                   :description="section.description">
        <div v-if="section.key === 'account'" class="logo">
          <span class="logo__box" :class="{ 'logo__box--empty': !logoUrl }">
            <img :src="logoUrl ?? '/logo.svg'" alt="Logo da empresa" />
          </span>
          <div class="logo__text">
            <strong>Logo da empresa</strong>
            <small>{{ logoUrl ? "Vai no canto superior direito das impressões." : "Sem logo: as impressões usam o do Starrp." }}
              Envie uma imagem quadrada; ajustamos para 1080×1080.</small>
            <span class="logo__actions">
              <Button :label="logoUrl ? 'Trocar logo' : 'Enviar logo'" icon="pi pi-upload" size="small" severity="secondary"
                      outlined :loading="logoBusy" @click="logoInput?.click()" />
              <Button v-if="logoUrl" label="Remover" icon="pi pi-trash" size="small" severity="danger" text :disabled="logoBusy"
                      @click="removeLogo" />
            </span>
            <input ref="logoInput" type="file" accept="image/png,image/jpeg,image/webp" hidden @change="sendLogo" />
          </div>
        </div>
        <div class="grid-form">
          <FormField v-for="field in section.fields" :key="field.name" v-model="values[section.key][field.name]" :field="field"
                     :context="values[section.key]" :error="errors[`${section.key}.${field.name}`]" />
        </div>
      </SectionCard>
      <SectionCard title="Plano e módulos" icon="pi pi-star" description="O que a sua assinatura inclui. Para mudar, fale com o suporte.">
        <dl class="plan">
          <div><dt>Plano</dt><dd>{{ query.data.value.plan.name }}</dd></div>
          <div><dt>Situação</dt><dd>{{ query.data.value.plan.status }}</dd></div>
          <div><dt>Filiais</dt><dd>{{ query.data.value.plan.stores }}</dd></div>
          <div class="wide"><dt>Módulos</dt>
            <dd class="chips"><span v-for="m in query.data.value.plan.modules" :key="m" class="chip">{{ MODULES[m] ?? m }}</span></dd></div>
        </dl>
      </SectionCard>
      <footer class="bar">
        <span class="state" :class="{ dirty }"><i :class="dirty ? 'pi pi-circle-fill' : 'pi pi-check-circle'" />
          {{ dirty ? "Alterações não salvas" : "Tudo salvo" }} <kbd>Ctrl S</kbd></span>
        <Button label="Descartar" severity="secondary" text :disabled="!dirty" @click="discard" />
        <Button label="Salvar" icon="pi pi-check" :loading="saving" :disabled="!dirty" @click="save" />
      </footer>
    </template>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; padding-bottom: 80px; }
.muted { color: var(--text-muted); display: flex; gap: 8px; align-items: center; }
.logo { display: flex; gap: 16px; align-items: center; margin-bottom: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--border-subtle); }
.logo__box { width: 96px; height: 96px; border-radius: 14px; overflow: hidden; flex-shrink: 0; display: grid; place-items: center;
             border: 1px solid var(--border); background: #fff; }
.logo__box img { width: 100%; height: 100%; object-fit: contain; }
.logo__box--empty { opacity: 0.7; border-style: dashed; }
.logo__box--empty img { width: 70%; height: 70%; }
.logo__text { display: flex; flex-direction: column; gap: 6px; }
.logo__text strong { color: var(--text-strong); font-size: 14px; }
.logo__text small { color: var(--text-muted); font-size: 12.5px; max-width: 520px; }
.logo__actions { display: flex; gap: 6px; }
.plan { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 18px; margin: 0; }
.plan .wide { grid-column: 1 / -1; }
.plan dt { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.plan dd { margin: 4px 0 0; color: var(--text-strong); font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { padding: 4px 10px; border-radius: 999px; background: var(--brand-subtle); color: var(--text-brand); font-size: 12.5px; }
.bar {
  position: sticky; bottom: 12px; display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 12px;
  border: 1px solid var(--border); background: var(--surface-card); box-shadow: var(--shadow-md);
}
.state { margin-right: auto; display: flex; gap: 8px; align-items: center; font-size: 13px; font-weight: 600; color: var(--success-text); }
.state.dirty { color: var(--warning-text); }
.state i { font-size: 11px; }
kbd { font: 600 10.5px/1 var(--font-mono); padding: 3px 6px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-muted); }
@media (max-width: 760px) { .plan { grid-template-columns: 1fr 1fr; } }
</style>
