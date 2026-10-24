<script setup lang="ts">
/**
 * Certificado digital A1 dos dados fiscais: mostra o atual (titular, CNPJ,
 * validade) e envia um novo (.pfx + senha). O servidor confere a senha e se o
 * certificado é da mesma empresa antes de guardar.
 */
import Button from "primevue/button";
import Password from "primevue/password";
import { computed, ref } from "vue";

import { fiscalApi } from "@/api/fiscal";
import { useNotify } from "@/composables/useNotify";
import type { FormActionContext } from "@/resources/types";
import { date } from "@/utils/format";

const props = defineProps<{ ctx: FormActionContext }>();
const emit = defineEmits<{ done: [] }>();
const notify = useNotify();
const file = ref<File | null>(null);
const password = ref("");
const sending = ref(false);

const v = computed(() => props.ctx.values);
const daysLeft = computed(() => {
  const until = v.value.certificate_valid_until;
  return until ? Math.floor((new Date(String(until)).getTime() - Date.now()) / 86_400_000) : null;
});

function pick(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null;
}

async function send() {
  if (!file.value) return;
  sending.value = true;
  try {
    await fiscalApi.certificate(props.ctx.id, file.value, password.value);
    notify.success("Certificado guardado");
    emit("done");
  } catch (error) {
    notify.error(error, "Certificado não aceito");
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <div class="cert">
    <div v-if="v.has_certificate" class="current" :class="{ warn: daysLeft !== null && daysLeft < 30 }">
      <i class="pi pi-shield" />
      <div>
        <strong>{{ v.certificate_name || "Certificado A1" }}</strong>
        <small>CNPJ {{ v.certificate_cnpj || "—" }} · válido até {{ date(v.certificate_valid_until) }}
          <template v-if="daysLeft !== null"> ({{ daysLeft < 0 ? "vencido" : `${daysLeft} dias` }})</template></small>
      </div>
    </div>
    <p v-else class="muted">Sem certificado. Ele é o que autoriza buscar as notas na SEFAZ e emitir.</p>

    <label class="drop" :class="{ chosen: file }">
      <input type="file" accept=".pfx,.p12" @change="pick">
      <i class="pi pi-upload" />
      <span>{{ file ? file.name : "Escolha o arquivo .pfx do certificado A1" }}</span>
    </label>
    <div class="field">
      <label for="cert-password">Senha do certificado</label>
      <Password v-model="password" input-id="cert-password" :feedback="false" toggle-mask fluid @keydown.enter="send" />
    </div>
    <div class="foot">
      <Button :label="v.has_certificate ? 'Trocar certificado' : 'Enviar certificado'" icon="pi pi-check" :loading="sending"
              :disabled="!file" @click="send" />
    </div>
  </div>
</template>

<style scoped>
.cert { display: flex; flex-direction: column; gap: 0.85rem; }
.cert p { margin: 0; font-size: 13px; }
.current {
  display: flex; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 8px;
  background: var(--success-subtle); color: var(--success-text);
}
.current.warn { background: var(--warning-subtle); color: var(--warning-text); }
.current i { font-size: 20px; }
.current div { display: flex; flex-direction: column; }
.current strong { font-size: 13.5px; }
.current small { font-size: 12px; opacity: 0.9; }
.drop {
  display: flex; align-items: center; gap: 10px; padding: 18px; border: 1.5px dashed var(--border-strong);
  border-radius: 10px; cursor: pointer; color: var(--text-muted); font-size: 13px;
}
.drop:hover, .drop.chosen { border-color: var(--brand); color: var(--text-strong); }
.drop input { display: none; }
.foot { display: flex; justify-content: flex-end; }
</style>
