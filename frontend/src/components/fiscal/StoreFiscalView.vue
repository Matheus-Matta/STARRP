<script setup lang="ts">
/**
 * Aba "Nota fiscal" da filial: tudo que a emissão de NFC-e/NF-e precisa, no cadastro da filial.
 *
 * Grava nos dados fiscais vinculados (o emitente, um por CNPJ; cria pelo CNPJ da filial se faltar).
 * Os dois PDVs usam o mesmo cadastro:
 * - PDV web: o servidor manda emitente + certificado A1 + CSC, cifrados, ao comunicador em nuvem (Docker);
 * - PDV desktop: baixa o kit (emitente, ambiente, séries, perfis — sem segredo) e grava no Comunicador
 *   Fiscal do caixa só o CNPJ + certificado + CSC, uma vez ("Gravar certificado no comunicador").
 */
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Password from "primevue/password";
import Select from "primevue/select";
import SelectButton from "primevue/selectbutton";
import Skeleton from "primevue/skeleton";
import ToggleSwitch from "primevue/toggleswitch";
import { computed, onMounted, ref } from "vue";

import { storeFiscalApi, type StoreFiscal } from "@/api/fiscal";
import { useNotify } from "@/composables/useNotify";
import { crt, environment } from "@/resources/fiscal";
import { date } from "@/utils/format";

const props = defineProps<{ id: string; values: Record<string, unknown> }>();
const notify = useNotify();

const state = ref<StoreFiscal | null>(null);
const failed = ref("");
const saving = ref(false);
const form = ref({ environment: "2", crt: "1", local_fiscal_enabled: false, local_fiscal_contingency: false,
                   csc_id: "", csc_token: "" });
const file = ref<File | null>(null);
const password = ref("");
const sending = ref(false);

function fill(data: StoreFiscal) {
  state.value = data;
  const c = data.config;
  if (c) {
    form.value = { environment: c.environment, crt: c.crt, local_fiscal_enabled: c.local_fiscal_enabled,
                   local_fiscal_contingency: c.local_fiscal_contingency, csc_id: c.csc_id, csc_token: "" };
  }
}

async function load() {
  try {
    fill(await storeFiscalApi.get(props.id));
  } catch (error) {
    failed.value = error instanceof Error ? error.message : "Não foi possível carregar.";
  }
}
onMounted(load);

const config = computed(() => state.value?.config ?? null);
const checks = computed(() => state.value?.checks ?? []);
const pending = computed(() => checks.value.filter((c) => !c.ok && c.scope !== "cloud").length);
const cloud = computed(() => checks.value.find((c) => c.scope === "cloud"));
const certWarn = computed(() => (config.value?.certificate_days ?? 999) < 30);

async function save() {
  saving.value = true;
  try {
    fill(await storeFiscalApi.save(props.id, { ...form.value }));
    notify.success(config.value ? "Nota fiscal da filial salva" : "Dados fiscais criados");
  } catch (error) {
    notify.error(error, "Não salvou");
  } finally {
    saving.value = false;
  }
}

function pick(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null;
}
async function sendCertificate() {
  if (!file.value) return;
  sending.value = true;
  try {
    fill(await storeFiscalApi.certificate(props.id, file.value, password.value));
    file.value = null;
    password.value = "";
    notify.success("Certificado guardado");
  } catch (error) {
    notify.error(error, "Certificado não aceito");
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <div class="sf">
    <p v-if="failed" class="sf__error">{{ failed }}</p>
    <div v-else-if="!state" class="sf__stack"><Skeleton v-for="i in 5" :key="i" height="2.4rem" /></div>
    <template v-else>
      <!-- Situação -->
      <div class="sf__status" :class="state.ready ? 'is-ok' : 'is-pending'">
        <i :class="state.ready ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'" />
        <div>
          <strong>{{ state.ready ? "Pronta para emitir NFC-e/NF-e" : `Falta${pending > 1 ? "m" : ""} ${pending} ${pending > 1 ? "itens" : "item"} para emitir` }}</strong>
          <small v-if="config">
            Emitente {{ config.legal_name }} · CNPJ {{ config.cnpj }} · {{ config.state }} ·
            {{ config.environment === "1" ? "Produção" : "Homologação" }}
            <template v-if="config.stores.length > 1"> · também usado por {{ config.stores.filter((s) => s !== values.name).join(", ") }}</template>
          </small>
          <small v-else>A filial ainda não tem dados fiscais. Salvar abaixo cria com o CNPJ, razão social, IE e endereço dela.</small>
        </div>
        <RouterLink v-if="config" :to="`/cadastros/dados-fiscais/${config.id}`" class="sf__link">
          Dados fiscais completos <i class="pi pi-arrow-right" />
        </RouterLink>
      </div>

      <ul class="sf__checks">
        <li v-for="c in checks" :key="c.key" :class="{ ok: c.ok, cloud: c.scope === 'cloud' }">
          <i :class="c.ok ? 'pi pi-check' : c.scope === 'cloud' ? 'pi pi-info-circle' : 'pi pi-times'" />
          <span><strong>{{ c.label }}</strong><small v-if="c.message">{{ c.message }}</small></span>
        </li>
      </ul>

      <!-- Emissão -->
      <section class="sf__card">
        <header><i class="pi pi-send" /> <div><h3>Emissão</h3>
          <p>O que vai em toda nota: ambiente, regime e o CSC da NFC-e. Vale para o PDV web e o desktop.</p></div></header>
        <div class="sf__grid">
          <label class="sf__field"><span>Ambiente</span>
            <SelectButton v-model="form.environment" :options="environment.options" option-label="label" option-value="value"
                          :allow-empty="false" /></label>
          <label class="sf__field"><span>Regime tributário</span>
            <Select v-model="form.crt" :options="crt.options" option-label="label" option-value="value" fluid /></label>
          <label class="sf__toggle"><ToggleSwitch v-model="form.local_fiscal_enabled" />
            <span><strong>Emitir nota no PDV</strong><small>NFC-e/NF-e pelo Comunicador Fiscal (ACBr)</small></span></label>
          <label class="sf__toggle"><ToggleSwitch v-model="form.local_fiscal_contingency" :disabled="!form.local_fiscal_enabled" />
            <span><strong>Contingência offline</strong><small>Sem SEFAZ, o PDV desktop emite em contingência e transmite depois</small></span></label>
          <label class="sf__field"><span>ID do CSC</span>
            <InputText v-model="form.csc_id" maxlength="6" inputmode="numeric" placeholder="000001" /></label>
          <label class="sf__field"><span>CSC (código)</span>
            <Password v-model="form.csc_token" :feedback="false" toggle-mask fluid
                      :placeholder="config?.has_csc_token ? 'Guardado — em branco mantém' : 'Código do portal da SEFAZ'" /></label>
        </div>
        <div class="sf__foot">
          <Button :label="config ? 'Salvar' : 'Criar dados fiscais e salvar'" icon="pi pi-check" :loading="saving" @click="save" />
        </div>
      </section>

      <!-- Certificado -->
      <section class="sf__card">
        <header><i class="pi pi-shield" /> <div><h3>Certificado digital A1</h3>
          <p>Fica guardado no servidor. O PDV desktop não guarda: grava no Comunicador Fiscal do caixa.</p></div></header>
        <div v-if="config?.has_certificate" class="sf__cert" :class="{ warn: certWarn }">
          <i class="pi pi-verified" />
          <div><strong>{{ config.certificate_name || "Certificado A1" }}</strong>
            <small>CNPJ {{ config.certificate_cnpj || "—" }} · válido até {{ date(config.certificate_valid_until) }}
              <template v-if="config.certificate_days !== null">
                ({{ config.certificate_days < 0 ? "vencido" : `${config.certificate_days} dias` }})</template></small></div>
        </div>
        <div class="sf__grid">
          <label class="sf__drop" :class="{ chosen: file }">
            <input type="file" accept=".pfx,.p12" @change="pick">
            <i class="pi pi-upload" /><span>{{ file ? file.name : "Escolha o arquivo .pfx" }}</span>
          </label>
          <label class="sf__field"><span>Senha do certificado</span>
            <Password v-model="password" :feedback="false" toggle-mask fluid @keydown.enter="sendCertificate" /></label>
        </div>
        <div class="sf__foot">
          <Button :label="config?.has_certificate ? 'Trocar certificado' : 'Enviar certificado'" icon="pi pi-upload"
                  severity="secondary" :loading="sending" :disabled="!file" @click="sendCertificate" />
        </div>
      </section>

      <!-- Onde cada coisa vai -->
      <section class="sf__card">
        <header><i class="pi pi-sitemap" /> <div><h3>Como os PDVs usam</h3>
          <p>Um cadastro só: cada PDV recebe apenas o que precisa.</p></div></header>
        <div class="sf__flow">
          <div><h4><i class="pi pi-globe" /> PDV web</h4>
            <p>Monta a nota e manda ao servidor. O servidor junta emitente, certificado e CSC e envia, cifrado, ao
              Comunicador Fiscal em nuvem (Docker). Nada sensível passa pelo navegador.</p>
            <small :class="cloud?.ok ? 'ok' : 'warn'">{{ cloud?.ok ? "Comunicador em nuvem configurado no servidor." : cloud?.message }}</small></div>
          <div><h4><i class="pi pi-desktop" /> PDV desktop</h4>
            <p>Baixa o <strong>kit fiscal</strong> (emitente, UF, ambiente, séries do caixa, perfis — sem segredo) e manda
              esses dados em cada nota. No Comunicador Fiscal do caixa ficam só <strong>CNPJ, certificado e CSC</strong>:
              em Configurações → Nota fiscal → <em>Gravar certificado no comunicador</em> (uma vez, e de novo ao trocar o
              certificado ou o CSC). Emite mesmo sem internet.</p>
            <small>Mudou ambiente, endereço ou série? O PDV desktop baixa o kit de novo ao abrir com o servidor no ar.</small></div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.sf { display: flex; flex-direction: column; gap: 14px; }
.sf__stack { display: flex; flex-direction: column; gap: 8px; }
.sf__error { color: var(--danger-text); }
.sf__status { display: flex; gap: 12px; align-items: center; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border); }
.sf__status > i { font-size: 22px; }
.sf__status div { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.sf__status small { color: var(--text-muted); }
.sf__status.is-ok { background: var(--success-subtle); }
.sf__status.is-ok > i { color: var(--success-text); }
.sf__status.is-pending { background: var(--warning-subtle); }
.sf__status.is-pending > i { color: var(--warning-text); }
.sf__link { font-size: 13px; font-weight: 600; white-space: nowrap; }
.sf__checks { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 6px; }
.sf__checks li { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border-subtle); }
.sf__checks li > i { margin-top: 3px; color: var(--danger-text); }
.sf__checks li.ok > i { color: var(--success-text); }
.sf__checks li.cloud:not(.ok) > i { color: var(--info-text); }
.sf__checks span { display: flex; flex-direction: column; font-size: 13px; }
.sf__checks small { color: var(--text-muted); }
.sf__card { border: 1px solid var(--border); border-radius: 10px; padding: 14px; background: var(--surface-card); display: flex; flex-direction: column; gap: 12px; }
.sf__card header { display: flex; gap: 10px; align-items: flex-start; }
.sf__card header > i { margin-top: 4px; color: var(--brand); }
.sf__card h3 { margin: 0; font-size: 15px; }
.sf__card header p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.sf__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.sf__field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; font-weight: 600; min-width: 0; }
.sf__toggle { display: flex; gap: 10px; align-items: center; }
.sf__toggle span { display: flex; flex-direction: column; font-size: 13px; }
.sf__toggle small { color: var(--text-muted); font-weight: 400; }
.sf__foot { display: flex; justify-content: flex-end; }
.sf__cert { display: flex; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 8px; background: var(--success-subtle); }
.sf__cert.warn { background: var(--warning-subtle); }
.sf__cert div { display: flex; flex-direction: column; }
.sf__cert small { color: var(--text-muted); }
.sf__drop { display: flex; gap: 8px; align-items: center; justify-content: center; padding: 12px; border: 1px dashed var(--border);
            border-radius: 8px; cursor: pointer; font-size: 13px; }
.sf__drop.chosen { border-color: var(--brand); }
.sf__drop input { display: none; }
.sf__flow { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.sf__flow h4 { margin: 0 0 4px; font-size: 14px; display: flex; gap: 6px; align-items: center; }
.sf__flow p { margin: 0 0 6px; font-size: 13px; }
.sf__flow small { font-size: 12px; color: var(--text-muted); }
.sf__flow small.ok { color: var(--success-text); }
.sf__flow small.warn { color: var(--warning-text); }
</style>
