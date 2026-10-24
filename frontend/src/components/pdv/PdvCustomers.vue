<script setup lang="ts">
/**
 * Clientes DENTRO do PDV (no lugar do modal): a mesma lista das telas da retaguarda,
 * com busca; clicar no cliente vincula à venda e volta para a venda.
 *
 * - "CPF na nota": só o documento, sem cadastrar (vai na nota fiscal);
 * - "Novo cliente": cadastro rápido com os mesmos campos (e máscaras) do formulário.
 */
import Button from "primevue/button";
import { computed, ref } from "vue";

import { resourceApi, type Row } from "@/api/resource";
import FormField from "@/components/resource/FormField.vue";
import EmbeddedList from "@/components/resource/EmbeddedList.vue";
import { useNotify } from "@/composables/useNotify";
import type { FieldDef, ListViewDef } from "@/resources/types";
import { documentError } from "@/utils/documents";
import { formatDocument } from "@/utils/documents";

defineProps<{ current: { name: string; document: string } | null; busy: boolean }>();
const emit = defineEmits<{ pick: [body: { customer?: string | null; customer_document?: string }]; back: [] }>();
const notify = useNotify();

const view: ListViewDef = {
  endpoint: "/customers/",
  params: () => ({ is_active: "true" }),
  ordering: "name",
  columns: [
    { key: "name", label: "Cliente", title: true },
    { key: "document", label: "CPF/CNPJ" },
    { key: "phone", label: "Telefone" },
    { key: "email", label: "E-mail" },
    { key: "credit_balance", label: "Vale-troca", type: "money", sortable: false },
  ],
};

const mode = ref<"list" | "document" | "new">("list");
const documentValue = ref("");
const draft = ref<Record<string, unknown>>({ person_type: "F", name: "", document: "", phone: "" });
const saving = ref(false);
const FIELDS: FieldDef[] = [
  { name: "name", label: "Nome", type: "text", required: true, span: 3 },
  { name: "document", label: "CPF", type: "document", span: 3 },
  { name: "phone", label: "Telefone", type: "phone", span: 3 },
  { name: "email", label: "E-mail", type: "email", span: 3 },
];
const docField: FieldDef = { name: "document", label: "CPF ou CNPJ na nota", type: "document" };
const docError = computed(() => (documentValue.value ? documentError(documentValue.value) : null));

function pick(row: Row) {
  emit("pick", { customer: String(row.id) });
}

function useDocument() {
  if (!documentValue.value || docError.value) return;
  emit("pick", { customer: null, customer_document: documentValue.value });
  documentValue.value = "";
  mode.value = "list";
}

async function create() {
  if (!String(draft.value.name ?? "").trim()) return notify.warn("Informe o nome do cliente.");
  saving.value = true;
  try {
    const created = await resourceApi.create("/customers/", draft.value);
    notify.success("Cliente cadastrado e vinculado à venda");
    emit("pick", { customer: String(created.id) });
    draft.value = { person_type: "F", name: "", document: "", phone: "" };
    mode.value = "list";
  } catch (error) {
    notify.error(error, "Não foi possível cadastrar o cliente");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="panel">
    <header class="panel__head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" aria-label="Voltar para a venda" @click="emit('back')" />
      <div>
        <h2>Cliente da venda</h2>
        <p v-if="current">Vinculado: <b>{{ current.name || formatDocument(current.document) }}</b></p>
        <p v-else>Escolha na lista, informe só o CPF na nota ou cadastre na hora.</p>
      </div>
      <Button v-if="current" label="Tirar cliente" icon="pi pi-user-minus" severity="secondary" text :disabled="busy"
              @click="emit('pick', { customer: null, customer_document: '' })" />
    </header>

    <div v-if="mode === 'document'" class="quick">
      <FormField v-model="documentValue" :field="docField" :error="docError ?? undefined" />
      <div class="quick__actions">
        <Button label="Voltar" severity="secondary" text @click="mode = 'list'" />
        <Button label="Usar na nota" icon="pi pi-check" :disabled="!documentValue || !!docError" @click="useDocument" />
      </div>
    </div>
    <div v-else-if="mode === 'new'" class="quick">
      <div class="grid-form">
        <FormField v-for="field in FIELDS" :key="field.name" v-model="draft[field.name]" :field="field" :context="draft" />
      </div>
      <div class="quick__actions">
        <Button label="Voltar" severity="secondary" text @click="mode = 'list'" />
        <Button label="Cadastrar e vincular" icon="pi pi-user-plus" :loading="saving" @click="create" />
      </div>
    </div>

    <EmbeddedList v-show="mode === 'list'" :view="view" id="" :values="{}" title="Clientes" pick compact
                  placeholder="Buscar por nome, CPF ou telefone…" @pick="pick">
      <template #toolbar>
        <Button label="CPF na nota" icon="pi pi-id-card" severity="secondary" outlined size="small" @click="mode = 'document'" />
        <Button label="Novo cliente" icon="pi pi-user-plus" size="small" @click="mode = 'new'" />
      </template>
    </EmbeddedList>
  </section>
</template>

<style scoped>
.panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 12px; overflow-y: auto; }
.panel__head { display: flex; align-items: center; gap: 10px; }
.panel__head > div { flex: 1; }
.panel__head h2 { margin: 0; font: 700 17px/1.2 var(--font-sans); color: var(--text-strong); }
.panel__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.quick { padding: 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface-card); display: flex; flex-direction: column; gap: 12px; }
.quick__actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
