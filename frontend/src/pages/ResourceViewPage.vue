<script setup lang="ts">
/**
 * Página de uma consulta do registro (`/cadastros/produtos/<id>/vendas`): o mesmo
 * cabeçalho e abas do formulário, e no corpo a lista filtrada ou o componente da
 * consulta (extrato do caixa, extrato da conta...).
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Skeleton from "primevue/skeleton";
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { resourceApi } from "@/api/resource";
import EmbeddedList from "@/components/resource/EmbeddedList.vue";
import RecordTabs from "@/components/resource/RecordTabs.vue";
import { detailKey } from "@/composables/usePrefetch";
import { findResource } from "@/resources";
import type { ResourceDef } from "@/resources/types";

const route = useRoute();
const router = useRouter();
const resource = computed(() => findResource(String(route.params.resource)) as ResourceDef);
const id = computed(() => String(route.params.id));
const view = computed(() => resource.value.views?.find((v) => v.name === route.params.view));

const record = useQuery({
  queryKey: computed(() => detailKey(resource.value.endpoint, id.value)),
  queryFn: () => resourceApi.get(resource.value.endpoint, id.value),
});
const values = computed(() => record.data.value ?? {});
const title = computed(() => {
  const v = values.value as Record<string, unknown>;
  const named = v.name ?? v.display_name ?? v.description ?? v.code ?? v.register_name ?? v.variant_name;
  return named ? String(named) : v.number ? `${resource.value.singular} ${v.number}` : resource.value.title;
});
</script>

<template>
  <section class="page view-page">
    <header class="head">
      <Button icon="pi pi-arrow-left" text rounded severity="secondary" size="small" :aria-label="`Voltar para ${resource.title}`"
              @click="router.push(`/cadastros/${resource.name}`)" />
      <div class="head__text">
        <Skeleton v-if="record.isPending.value" width="14rem" height="1.2rem" />
        <h1 v-else>{{ title }}</h1>
        <p>{{ resource.title }} · {{ view?.label }}</p>
      </div>
    </header>
    <RecordTabs :resource="resource" :id="id" :active="String(route.params.view)" />
    <p v-if="view?.description" class="lead">{{ view.description }}</p>

    <p v-if="!view" class="muted">Consulta não encontrada.</p>
    <template v-else-if="record.isSuccess.value">
      <EmbeddedList v-if="view.list" :key="view.name" :view="view.list" :id="id" :values="values" :title="`${title} - ${view.label}`"
                    :resource-name="resource.name" :view-name="view.name" />
      <component :is="view.component" v-else-if="view.component" :id="id" :values="values" />
    </template>
    <div v-else class="stack"><Skeleton v-for="n in 6" :key="n" height="2.2rem" /></div>
  </section>
</template>

<style scoped>
.view-page { max-width: none; }
.head { display: flex; align-items: center; gap: 0.5rem; }
.head__text { min-width: 0; }
h1 { font: 700 19px/1.2 var(--font-sans); letter-spacing: -0.01em; }
.head__text p { font-size: 12.5px; color: var(--text-muted); }
.lead { margin: 0; font-size: 13px; color: var(--text-muted); }
.stack { display: flex; flex-direction: column; gap: 8px; }
</style>
