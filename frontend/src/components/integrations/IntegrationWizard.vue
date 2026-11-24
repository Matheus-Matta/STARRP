<script setup lang="ts">
/**
 * Assistente de integração: 1. Tipo → 2. Configuração → 3. O que vai fazer?
 *
 * Os campos de cada tipo vêm do backend (`/integrations/types/`): nomes fixos, obrigatórios e opcionais,
 * segredos (a chave nunca volta: em branco mantém a guardada). Editar abre direto na configuração.
 */
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Step from "primevue/step";
import StepList from "primevue/steplist";
import StepPanel from "primevue/steppanel";
import StepPanels from "primevue/steppanels";
import Stepper from "primevue/stepper";
import Textarea from "primevue/textarea";
import ToggleSwitch from "primevue/toggleswitch";
import { computed, ref, watch } from "vue";

import { toApiError } from "@/api/errors";
import {
  type CheckResult, type Integration, type IntegrationField, integrationsApi, type IntegrationType, SECRET_MASK,
} from "@/api/integrations";
import FormField from "@/components/resource/FormField.vue";
import IntegrationLogo from "./IntegrationLogo.vue";
import { useNotify } from "@/composables/useNotify";
import type { FieldDef } from "@/resources/types";

const props = defineProps<{ types: IntegrationType[]; existing: Integration[]; editing?: Integration | null }>();
const visible = defineModel<boolean>("visible", { default: false });
const emit = defineEmits<{ saved: [Integration] }>();
const notify = useNotify();

const step = ref("1");
const kind = ref<string>("");
const name = ref("");
const values = ref<Record<string, unknown>>({});
const purposes = ref<string[]>([]);
const isActive = ref(true);
const isDefault = ref(false);
const notes = ref("");
const errors = ref<Record<string, string>>({});
const check = ref<CheckResult | null>(null);
const checking = ref(false);
const saving = ref(false);

const type = computed(() => props.types.find((t) => t.key === kind.value) ?? null);
const sameKind = computed(() => props.existing.filter((i) => i.kind === kind.value && i.id !== props.editing?.id));
const categories = computed(() => {
  const groups = new Map<string, IntegrationType[]>();
  for (const t of props.types) groups.set(t.category, [...(groups.get(t.category) ?? []), t]);
  return [...groups.entries()];
});
const blocked = (t: IntegrationType) => !t.multiple && props.existing.some((i) => i.kind === t.key);

/* Abrir: novo começa no tipo; edição vem preenchida e começa na configuração. */
watch(visible, (open) => {
  if (!open) return;
  errors.value = {};
  check.value = null;
  const e = props.editing;
  if (e) {
    kind.value = e.kind;
    name.value = e.name;
    values.value = Object.fromEntries(Object.entries(e.fields).map(([k, v]) => [k, v === SECRET_MASK ? "" : v]));
    purposes.value = [...e.purposes];
    isActive.value = e.is_active;
    isDefault.value = e.is_default;
    notes.value = e.notes ?? "";
    step.value = "2";
  } else {
    kind.value = "";
    name.value = "";
    values.value = {};
    purposes.value = [];
    isActive.value = true;
    isDefault.value = false;
    notes.value = "";
    step.value = "1";
  }
});

function choose(t: IntegrationType) {
  if (blocked(t)) return;
  kind.value = t.key;
  values.value = Object.fromEntries(t.fields.map((f) => [f.name, f.type === "number" && f.default != null ? Number(f.default)
    : f.default ?? (f.type === "boolean" ? false : "")]));
  purposes.value = t.purposes.filter((p) => p.default).map((p) => p.key);
  const n = props.existing.filter((i) => i.kind === t.key).length;
  name.value = n ? `${t.label} ${n + 1}` : t.label;
  isDefault.value = n === 0;
  check.value = null;
  step.value = "2";
}

/* Campo do tipo → campo do formulário do sistema. */
const stored = (f: IntegrationField) => props.editing?.fields[f.name] === SECRET_MASK;
function toFieldDef(f: IntegrationField): FieldDef {
  const base = { name: f.name, label: f.label, required: f.required && !(f.type === "secret" && stored(f)),
                 hint: f.help || undefined, placeholder: f.placeholder || undefined, span: 3 as const };
  switch (f.type) {
    case "secret":
      return { ...base, type: "password", placeholder: stored(f) ? "Guardada — em branco mantém a atual" : base.placeholder };
    case "select": return { ...base, type: "select", options: f.options.map((o) => ({ label: o.label, value: o.value })) };
    case "relation": return { ...base, type: "relation", relation: { endpoint: f.relation ?? "" } };
    case "boolean": return { ...base, type: "boolean" };
    case "number": return { ...base, type: "number" };
    case "email": return { ...base, type: "email" };
    default: return { ...base, type: "text" };
  }
}
const applies = (f: IntegrationField) => !f.when || Object.entries(f.when).every(([k, allowed]) => allowed.includes(String(values.value[k] ?? "")));
const required = computed(() => (type.value?.fields ?? []).filter((f) => f.required && applies(f)));
const optional = computed(() => (type.value?.fields ?? []).filter((f) => !f.required && applies(f)));

function payloadFields() {
  return Object.fromEntries(Object.entries(values.value).map(([k, v]) => [k, v === null || v === undefined ? "" : v]));
}
function validateConfig() {
  const out: Record<string, string> = {};
  if (!name.value.trim()) out.name = "Dê um nome (ex.: Asaas — Empresa A).";
  else if (props.existing.some((i) => i.name.trim().toLowerCase() === name.value.trim().toLowerCase() && i.id !== props.editing?.id)) {
    out.name = "Já existe uma integração com este nome.";
  }
  for (const f of required.value) {
    if (f.type === "secret" && stored(f)) continue;
    if (values.value[f.name] === "" || values.value[f.name] == null) out[f.name] = `Informe ${f.label}.`;
  }
  errors.value = out;
  return !Object.keys(out).length;
}

async function runCheck() {
  if (!type.value || !validateConfig()) return;
  checking.value = true;
  try {
    check.value = await integrationsApi.check(kind.value, payloadFields(), props.editing?.id);
  } catch (error) {
    const api = toApiError(error);
    errors.value = { ...errors.value, ...api.fields };
    check.value = { ok: false, message: api.message, data: {} };
  } finally {
    checking.value = false;
  }
}

function next() {
  if (validateConfig()) step.value = "3";
}

function togglePurpose(key: string, on: boolean) {
  purposes.value = on ? [...new Set([...purposes.value, key])] : purposes.value.filter((p) => p !== key);
}

async function save() {
  if (!validateConfig()) {
    step.value = "2";
    return;
  }
  saving.value = true;
  const input = { name: name.value.trim(), fields: payloadFields(), purposes: purposes.value, is_active: isActive.value,
                  is_default: isDefault.value, notes: notes.value };
  try {
    const saved = props.editing
      ? await integrationsApi.update(props.editing.id, input)
      : await integrationsApi.create({ ...input, kind: kind.value });
    notify.success(props.editing ? "Integração salva" : "Integração criada", saved.name);
    emit("saved", saved);
    visible.value = false;
  } catch (error) {
    const api = toApiError(error);
    errors.value = api.fields;
    if (Object.keys(api.fields).some((k) => k === "name" || type.value?.fields.some((f) => f.name === k))) step.value = "2";
    notify.error(error, "Não salvou");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog v-model:visible="visible" modal :header="editing ? `Editar ${editing.name}` : 'Nova integração'"
          :style="{ width: 'min(760px, calc(100vw - 32px))' }" :draggable="false">
    <Stepper v-model:value="step" linear>
      <StepList>
        <Step value="1" :disabled="Boolean(editing)">Tipo</Step>
        <Step value="2" :disabled="!kind">Configuração</Step>
        <Step value="3" :disabled="!kind">O que vai fazer?</Step>
      </StepList>
      <StepPanels>
        <!-- 1. Tipo -->
        <StepPanel value="1">
          <div v-for="[category, list] in categories" :key="category" class="iw__group">
            <h4>{{ category }}</h4>
            <div class="iw__types">
              <button v-for="t in list" :key="t.key" type="button" class="iw__type"
                      :class="{ active: kind === t.key, blocked: blocked(t) }" :disabled="blocked(t)" @click="choose(t)">
                <IntegrationLogo :logo="t.logo" :icon="t.icon" :label="t.label" :size="40" />
                <span>
                  <strong>{{ t.label }}</strong>
                  <small>{{ t.description }}</small>
                  <em v-if="!t.available">Só a configuração por enquanto</em>
                  <em v-else-if="existing.some((i) => i.kind === t.key)">
                    {{ existing.filter((i) => i.kind === t.key).length }} já configurada(s){{ t.multiple ? " — pode adicionar outra" : "" }}
                  </em>
                </span>
              </button>
            </div>
          </div>
        </StepPanel>

        <!-- 2. Configuração -->
        <StepPanel value="2">
          <div v-if="type" class="iw__body">
            <div class="iw__head">
              <IntegrationLogo :logo="type.logo" :icon="type.icon" :label="type.label" :size="44" />
              <p><strong>{{ type.label }}</strong> {{ type.description }}
                <a v-if="type.docs_url" :href="type.docs_url" target="_blank" rel="noopener">Documentação</a></p>
            </div>
            <div class="grid-form">
              <div class="field span-6">
                <label for="iw-name">Nome <span class="req">*</span></label>
                <InputText id="iw-name" v-model="name" fluid :invalid="Boolean(errors.name)"
                           placeholder="Ex.: Asaas — Empresa A" />
                <small v-if="errors.name" class="err">{{ errors.name }}</small>
                <small v-else-if="sameKind.length" class="muted">Já existe(m): {{ sameKind.map((i) => i.name).join(", ") }}.
                  O nome distingue as contas.</small>
              </div>
            </div>
            <h5 v-if="required.length">Obrigatórios</h5>
            <div class="grid-form">
              <FormField v-for="f in required" :key="f.name" v-model="values[f.name]" :field="toFieldDef(f)"
                         :context="values" :error="errors[f.name]" />
            </div>
            <h5 v-if="optional.length">Opcionais</h5>
            <div class="grid-form">
              <FormField v-for="f in optional" :key="f.name" v-model="values[f.name]" :field="toFieldDef(f)"
                         :context="values" :error="errors[f.name]" />
            </div>
            <div v-if="check" class="iw__check" :class="check.ok ? 'ok' : 'bad'">
              <i :class="check.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" /> {{ check.message }}
            </div>
          </div>
          <div class="iw__foot">
            <Button v-if="!editing" label="Voltar" text icon="pi pi-arrow-left" @click="step = '1'" />
            <span class="grow" />
            <Button v-if="type?.testable" label="Testar conexão" icon="pi pi-bolt" severity="secondary" outlined
                    :loading="checking" @click="runCheck" />
            <Button label="Próximo" icon="pi pi-arrow-right" icon-pos="right" @click="next" />
          </div>
        </StepPanel>

        <!-- 3. O que vai fazer? -->
        <StepPanel value="3">
          <div v-if="type" class="iw__body">
            <div class="iw__head">
              <IntegrationLogo :logo="type.logo" :icon="type.icon" :label="type.label" :size="44" />
              <p>Escolha o que <strong>{{ name || type.label }}</strong> faz no sistema. Dá para mudar depois.</p>
            </div>
            <div class="iw__purposes">
              <label v-for="p in type.purposes" :key="p.key" class="iw__purpose" :class="{ on: purposes.includes(p.key) }">
                <Checkbox :model-value="purposes.includes(p.key)" binary
                          @update:model-value="(on: boolean) => togglePurpose(p.key, on)" />
                <span><strong>{{ p.label }}</strong><small v-if="p.description">{{ p.description }}</small></span>
              </label>
            </div>
            <p v-if="!type.available" class="muted">Este tipo ainda só guarda a configuração: as ações escolhidas passam a
              valer quando a integração for liberada.</p>
            <div class="iw__switches">
              <label><ToggleSwitch v-model="isActive" /> <span><strong>Ativa</strong>
                <small>Desligada, nada é enviado ao serviço.</small></span></label>
              <label v-if="type.multiple"><ToggleSwitch v-model="isDefault" /> <span><strong>Padrão do {{ type.label }}</strong>
                <small>A usada quando o título não escolhe a conta{{ sameKind.length ? "" : " (é a única)" }}.</small></span></label>
            </div>
            <div class="field">
              <label for="iw-notes">Observações</label>
              <Textarea id="iw-notes" v-model="notes" rows="2" auto-resize fluid placeholder="Ex.: conta do CNPJ da filial Centro" />
            </div>
          </div>
          <div class="iw__foot">
            <Button label="Voltar" text icon="pi pi-arrow-left" @click="step = '2'" />
            <span class="grow" />
            <Button :label="editing ? 'Salvar' : 'Criar integração'" icon="pi pi-check" :loading="saving" @click="save" />
          </div>
        </StepPanel>
      </StepPanels>
    </Stepper>
  </Dialog>
</template>

<style scoped>
.iw__group + .iw__group { margin-top: 14px; }
.iw__group h4 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); }
.iw__types { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.iw__type { display: flex; gap: 12px; align-items: flex-start; padding: 14px; text-align: left; border: 1px solid var(--border);
            border-radius: 10px; background: var(--surface-card); cursor: pointer; color: var(--text-body);
            transition: border-color var(--dur-fast) ease, background-color var(--dur-fast) ease; }
.iw__type:hover:not(:disabled), .iw__type.active { border-color: var(--brand); background: var(--brand-subtle); }
.iw__type.blocked { opacity: 0.55; cursor: not-allowed; }
.iw__type span { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.iw__type small { color: var(--text-muted); font-size: 12px; }
.iw__type em { font-size: 11.5px; color: var(--info-text); font-style: normal; }
.iw__body { display: flex; flex-direction: column; gap: 10px; }
.iw__body h5 { margin: 6px 0 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); }
.iw__head { display: flex; gap: 12px; align-items: center; }
.iw__head p { margin: 0; font-size: 13px; color: var(--text-muted); }
.iw__head strong { color: var(--text-strong); margin-right: 4px; }
.iw__check { display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
.iw__check.ok { background: var(--success-subtle); color: var(--success-text); }
.iw__check.bad { background: var(--danger-subtle); color: var(--danger-text); }
.iw__purposes { display: flex; flex-direction: column; gap: 8px; }
.iw__purpose { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--border);
               border-radius: 8px; cursor: pointer; }
.iw__purpose.on { border-color: var(--brand); background: var(--brand-subtle); }
.iw__purpose span, .iw__switches span { display: flex; flex-direction: column; font-size: 13px; }
.iw__purpose small, .iw__switches small { color: var(--text-muted); font-weight: 400; }
.iw__switches { display: flex; flex-wrap: wrap; gap: 16px; }
.iw__switches label { display: flex; gap: 10px; align-items: center; }
.iw__foot { display: flex; gap: 8px; align-items: center; margin-top: 16px; flex-wrap: wrap; }
.grow { flex: 1; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 13px; font-weight: 600; }
.req { color: var(--danger-text); }
.err { color: var(--danger-text); }
.muted { color: var(--text-muted); font-size: 12.5px; }
</style>
