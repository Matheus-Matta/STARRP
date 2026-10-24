<script setup lang="ts">
/** Pede a autorização de um superior (montado uma vez, no App). */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Password from "primevue/password";
import SelectButton from "primevue/selectbutton";
import { computed, ref, watch } from "vue";

import { useApprovalDialog } from "@/composables/useApproval";

const { pending, answer } = useApprovalDialog();
const visible = computed(() => pending.value !== null);
const mode = ref<"manager" | "cash">("manager");
const username = ref("");
const password = ref("");

watch(visible, (open) => {
  if (open) {
    username.value = "";
    password.value = "";
  }
});

function confirm() {
  if (!password.value) return;
  answer(mode.value === "cash" ? { cash_password: password.value } : { username: username.value, password: password.value });
}
</script>

<template>
  <Dialog :visible="visible" modal header="Autorização necessária" :style="{ width: '26rem' }" :closable="false">
    <p class="muted">{{ pending?.message }}</p>
    <SelectButton v-model="mode" :options="[{ label: 'Gerente', value: 'manager' }, { label: 'Senha do caixa', value: 'cash' }]"
                  option-label="label" option-value="value" :allow-empty="false" />
    <form class="form" @submit.prevent="confirm">
      <InputText v-if="mode === 'manager'" v-model="username" placeholder="Usuário do gerente" autofocus />
      <Password v-model="password" :feedback="false" placeholder="Senha" toggle-mask fluid />
      <div class="actions">
        <Button label="Cancelar" severity="secondary" outlined @click="answer(null)" />
        <Button type="submit" label="Autorizar" icon="pi pi-lock-open" />
      </div>
    </form>
  </Dialog>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 1rem; }
.actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
