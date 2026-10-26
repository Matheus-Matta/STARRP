<script setup lang="ts">
/** Rejeitar uma avaliação: o motivo é obrigatório (fica no histórico; o cliente pode avaliar de novo). */
import Button from "primevue/button";
import Textarea from "primevue/textarea";
import { ref } from "vue";

import { reviewsApi } from "@/api/reviews";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: []; close: [] }>();
const notify = useNotify();
const REASONS = ["Linguagem ofensiva", "Comentário com dados pessoais", "Não é sobre o produto", "Spam ou propaganda",
                 "Avaliação duplicada"];
const reason = ref("");
const saving = ref(false);

async function reject() {
  saving.value = true;
  try {
    await reviewsApi.reject(props.ctx.id, reason.value);
    notify.success("Avaliação rejeitada");
    emit("done");
  } catch (error) {
    notify.error(error, "Não foi possível rejeitar");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="reject">
    <p class="muted">Por que esta avaliação não deve contar? O motivo fica registrado.</p>
    <div class="reasons">
      <Button v-for="r in REASONS" :key="r" :label="r" size="small" :severity="reason === r ? undefined : 'secondary'"
              :outlined="reason !== r" @click="reason = r" />
    </div>
    <Textarea v-model="reason" rows="3" auto-resize placeholder="Ou escreva o motivo" maxlength="255" fluid />
    <div class="foot">
      <Button label="Voltar" severity="secondary" text @click="emit('close')" />
      <Button label="Rejeitar avaliação" icon="pi pi-times" severity="danger" :loading="saving"
              :disabled="reason.trim().length < 3" @click="reject" />
    </div>
  </div>
</template>

<style scoped>
.reject { display: flex; flex-direction: column; gap: 12px; }
.reject > p { margin: 0; font-size: 13px; }
.reasons { display: flex; flex-wrap: wrap; gap: 6px; }
.foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
