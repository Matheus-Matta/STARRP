<script setup lang="ts">
/** O antes e depois de cada sugestão, para aprovar uma a uma. Nada muda no cadastro sem este clique. */
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import { computed, ref, watch } from "vue";

import { seoApi } from "@/api/seo";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { useSession } from "@/stores/session";

type Suggestion = { field: string; label: string; current: string; suggested: string; from_ai?: boolean };

const props = defineProps<{ ctx: FormActionContext }>();
const notify = useNotify();
const session = useSession();
const saving = ref(false);
const chosen = ref<string[]>([]);

const canApply = computed(() => session.can("catalog.manage") && !props.ctx.values.reading);
const suggestions = computed(() => (props.ctx.values.suggestions ?? []) as Suggestion[]);
watch(suggestions, (rows) => {
  chosen.value = rows.map((row) => row.field).filter((name) => name !== "slug");  // o endereço só com escolha consciente
}, { immediate: true });

async function apply() {
  saving.value = true;
  try {
    await seoApi.apply(props.ctx.id, chosen.value);
    notify.success("Cadastro do produto atualizado");
    await props.ctx.reload();
  } catch (error) {
    notify.error(error, "Não foi possível aplicar");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section v-if="suggestions.length" class="seo-sug" aria-label="Sugestões para o cadastro">
    <header>
      <h2><i class="pi pi-sparkles" /> Sugestões para o cadastro</h2>
      <p>Marque o que quer aplicar. Nada muda no produto sem a sua aprovação.</p>
    </header>
    <div v-for="row in suggestions" :key="row.field" class="seo-sug__row">
      <Checkbox v-model="chosen" :value="row.field" :input-id="`seo-${row.field}`" :disabled="!canApply" />
      <div class="seo-sug__text">
        <label :for="`seo-${row.field}`">{{ row.label }}
          <span v-if="row.from_ai" class="seo-sug__ai"><i class="pi pi-sparkles" /> Sugestão da Cosmos</span></label>
        <p class="seo-sug__before"><span>Hoje</span> {{ row.current || "(vazio)" }}</p>
        <p class="seo-sug__after"><span>Sugestão</span> {{ row.suggested }}</p>
        <small v-if="row.field === 'slug'"><i class="pi pi-exclamation-triangle" /> Se o endereço já foi publicado, trocar exige
          redirecionar o antigo.</small>
      </div>
    </div>
    <div v-if="canApply" class="seo-sug__actions">
      <Button label="Aplicar selecionadas" icon="pi pi-check" size="small" severity="success" :loading="saving"
              :disabled="!chosen.length" @click="apply" />
    </div>
  </section>
</template>

<style scoped>
.seo-sug {
  display: flex; flex-direction: column; gap: 0.75rem; padding: 14px 18px; border-radius: 10px;
  background: var(--surface-card); border: 1px solid var(--border); box-shadow: var(--shadow-xs);
}
header { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
h2 { margin: 0; display: flex; align-items: center; gap: 0.45rem; font: 600 14px/1.3 var(--font-sans); color: var(--text-strong); }
h2 i { font-size: 13px; color: var(--brand); }
header p { margin: 0; font-size: 13px; color: var(--text-muted); }
.seo-sug__row { display: flex; gap: 0.75rem; align-items: flex-start; padding-top: 0.75rem; border-top: 1px solid var(--border-subtle); }
.seo-sug__text { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 0.2rem; }
.seo-sug__text label { font-size: 13px; font-weight: 600; color: var(--text-strong); cursor: pointer; }
.seo-sug__text p { margin: 0; font-size: 13.5px; overflow-wrap: anywhere; }
.seo-sug__text p span { display: inline-block; min-width: 4.5rem; font-size: 12px; font-weight: 600; color: var(--text-muted); }
.seo-sug__ai { margin-left: 0.4rem; font-size: 11.5px; font-weight: 600; color: var(--text-brand); }
.seo-sug__before { color: var(--text-muted); }
.seo-sug__after { color: var(--text-strong); font-weight: 600; }
.seo-sug__text small { font-size: 12px; color: var(--warning-text); }
.seo-sug__actions { display: flex; justify-content: flex-end; }
</style>
