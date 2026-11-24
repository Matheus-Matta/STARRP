<script setup lang="ts">
/**
 * Integrações da conta (só o administrador): a lista e o botão de adicionar, que abre o assistente
 * (tipo → configuração → o que vai fazer). Pode haver várias do mesmo tipo (duas contas do Asaas).
 */
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Tag from "primevue/tag";
import { useConfirm } from "primevue/useconfirm";
import { computed, ref } from "vue";

import { type Integration, integrationsApi } from "@/api/integrations";
import EmptyState from "@/components/common/EmptyState.vue";
import PageHeader from "@/components/common/PageHeader.vue";
import IntegrationLogo from "@/components/integrations/IntegrationLogo.vue";
import IntegrationWizard from "@/components/integrations/IntegrationWizard.vue";
import { useNotify } from "@/composables/useNotify";
import { dateTime } from "@/utils/format";

const notify = useNotify();
const confirm = useConfirm();
const client = useQueryClient();
const typesQuery = useQuery({ queryKey: ["integration-types"], queryFn: integrationsApi.types, staleTime: 600_000 });
const listQuery = useQuery({ queryKey: ["integrations"], queryFn: integrationsApi.list });
const types = computed(() => typesQuery.data.value ?? []);
const rows = computed(() => listQuery.data.value ?? []);
const typeOf = (kind: string) => types.value.find((t) => t.key === kind);

const wizard = ref(false);
const editing = ref<Integration | null>(null);
const testing = ref<string | null>(null);

function add() {
  editing.value = null;
  wizard.value = true;
}
function edit(row: Integration) {
  editing.value = row;
  wizard.value = true;
}
const refresh = () => client.invalidateQueries({ queryKey: ["integrations"] });

async function test(row: Integration) {
  testing.value = row.id;
  try {
    const result = await integrationsApi.test(row.id);
    if (result.ok) notify.success("Conexão ok", result.message);
    else notify.warn("Conexão recusada", result.message);
    await refresh();
  } catch (error) {
    notify.error(error, "Teste não concluído");
  } finally {
    testing.value = null;
  }
}

function remove(row: Integration) {
  confirm.require({
    header: "Excluir integração", message: `Excluir "${row.name}"? A chave guardada é apagada junto.`,
    acceptProps: { label: "Excluir", severity: "danger" }, rejectProps: { label: "Cancelar", text: true },
    accept: async () => {
      try {
        await integrationsApi.remove(row.id);
        notify.success("Integração excluída", row.name);
        await refresh();
      } catch (error) {
        notify.error(error, "Não excluiu");
      }
    },
  });
}
</script>

<template>
  <div class="page integrations">
    <PageHeader title="Integrações" icon="pi pi-link"
                subtitle="Serviços externos ligados à conta: cobrança (Asaas), loja virtual (Shopify) e outros.">
      <Button label="Adicionar integração" icon="pi pi-plus" :disabled="!types.length" @click="add" />
    </PageHeader>

    <DataTable :value="rows" :loading="listQuery.isLoading.value" data-key="id" responsive-layout="stack"
               breakpoint="720px" class="integrations__table" @row-dblclick="(e) => edit(e.data as Integration)">
      <template #empty>
        <EmptyState icon="pi pi-link" title="Nenhuma integração"
                    description="Adicione o Asaas para gerar boletos das contas a receber, ou a sua loja Shopify." />
      </template>
      <Column header="Integração">
        <template #body="{ data }">
          <div class="integrations__name">
            <IntegrationLogo :logo="typeOf(data.kind)?.logo" :icon="typeOf(data.kind)?.icon" :label="data.kind_label" />
            <span><strong>{{ data.name }}</strong><small>{{ data.kind_label }}</small></span>
            <Tag v-if="data.is_default && rows.filter((r) => r.kind === data.kind).length > 1" value="Padrão" severity="info" />
          </div>
        </template>
      </Column>
      <Column header="O que faz">
        <template #body="{ data }">
          <div class="integrations__purposes">
            <span v-for="label in data.purpose_labels" :key="label" class="chip">{{ label }}</span>
            <span v-if="!data.purpose_labels.length" class="muted">Nada ligado</span>
          </div>
        </template>
      </Column>
      <Column header="Situação">
        <template #body="{ data }">
          <Tag :value="data.is_active ? 'Ativa' : 'Desligada'" :severity="data.is_active ? 'success' : 'secondary'" />
        </template>
      </Column>
      <Column header="Última conferência">
        <template #body="{ data }">
          <span v-if="data.last_check_at" class="integrations__check" :class="data.last_check_ok ? 'ok' : 'bad'"
                :title="data.last_check_message">
            <i :class="data.last_check_ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" />
            {{ dateTime(data.last_check_at) }}
          </span>
          <span v-else class="muted">Não testada</span>
        </template>
      </Column>
      <Column header="" class="integrations__actions">
        <template #body="{ data }">
          <Button v-if="typeOf(data.kind)?.testable" icon="pi pi-bolt" text rounded title="Testar conexão"
                  :loading="testing === data.id" aria-label="Testar conexão" @click="test(data)" />
          <Button icon="pi pi-pencil" text rounded title="Editar" aria-label="Editar" @click="edit(data)" />
          <Button icon="pi pi-trash" text rounded severity="danger" title="Excluir" aria-label="Excluir"
                  @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <IntegrationWizard v-model:visible="wizard" :types="types" :existing="rows" :editing="editing" @saved="refresh" />
  </div>
</template>

<style scoped>
.integrations { display: flex; flex-direction: column; gap: 16px; }
.integrations__name { display: flex; gap: 10px; align-items: center; }
.integrations__name span { display: flex; flex-direction: column; }
.integrations__name small, .muted { color: var(--text-muted); font-size: 12px; }
.integrations__purposes { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { padding: 2px 8px; border-radius: 999px; background: var(--surface-sunken); font-size: 12px; }
.integrations__check { display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; }
.integrations__check.ok i { color: var(--success-text); }
.integrations__check.bad i { color: var(--danger-text); }
:deep(.integrations__actions) { width: 1%; white-space: nowrap; text-align: right; }
</style>
