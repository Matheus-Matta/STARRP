<script setup lang="ts">
/**
 * Redefinição de senha, em duas etapas na mesma rota:
 * - sem token: pede o e-mail e manda o link;
 * - com token (link do e-mail, depois do `#`): escolhe a senha nova.
 */
import Button from "primevue/button";
import IconField from "primevue/iconfield";
import InputIcon from "primevue/inputicon";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

import { authApi } from "@/api/auth";
import { toApiError } from "@/api/errors";
import { resetTokenFrom } from "@/utils/resetToken";

const route = useRoute();
const token = ref(resetTokenFrom(route.hash));
// O link não fica na barra de endereço nem no histórico do navegador.
if (token.value) window.history.replaceState(window.history.state, "", route.path);

const email = ref("");
const password = ref("");
const repeat = ref("");
const error = ref("");
const loading = ref(false);
const done = ref(false);

const title = computed(() => {
  if (done.value) return token.value ? "Senha alterada" : "Confira seu e-mail";
  return token.value ? "Criar nova senha" : "Esqueci minha senha";
});

async function submit() {
  error.value = "";
  if (token.value && password.value !== repeat.value) {
    error.value = "As senhas não são iguais.";
    return;
  }
  loading.value = true;
  try {
    if (token.value) await authApi.confirmReset(token.value, password.value);
    else await authApi.requestReset(email.value.trim());
    done.value = true;
  } catch (e) {
    const apiError = toApiError(e);
    error.value = apiError.status === 429 ? "Muitas tentativas. Espere alguns minutos." : apiError.message;
    if (apiError.code === "reset_invalid") token.value = "";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="reset">
    <form class="box" @submit.prevent="submit">
      <img src="/brand/logo.png" alt="Starrp" class="logo logo--light" height="34" />
      <img src="/brand/logo-light.png" alt="" class="logo logo--dark" height="34" aria-hidden="true" />
      <h2>{{ title }}</h2>
      <Message v-if="error" severity="error" :closable="false" icon="pi pi-exclamation-circle">{{ error }}</Message>

      <template v-if="done">
        <p class="muted">{{ token ? "Entre com a senha nova. As sessões abertas com a anterior foram encerradas."
          : "Se o e-mail estiver cadastrado, o link chega em instantes. Sem e-mail no seu usuário? Peça a senha nova ao administrador." }}</p>
      </template>
      <template v-else-if="token">
        <label class="field">
          <span>Senha nova</span>
          <Password v-model="password" :feedback="false" toggle-mask fluid size="large" required
                    :input-props="{ autocomplete: 'new-password' }" />
        </label>
        <label class="field">
          <span>Repita a senha nova</span>
          <Password v-model="repeat" :feedback="false" toggle-mask fluid size="large" required
                    :input-props="{ autocomplete: 'new-password' }" />
        </label>
        <Button type="submit" label="Salvar senha" icon="pi pi-check" :loading="loading"
                :disabled="!password || !repeat" size="large" fluid />
      </template>
      <template v-else>
        <p class="muted">Informe o e-mail do seu usuário para receber o link.</p>
        <label class="field">
          <span>E-mail</span>
          <IconField><InputIcon class="pi pi-envelope" />
            <InputText v-model="email" type="email" autocomplete="email" required autofocus fluid size="large" /></IconField>
        </label>
        <Button type="submit" label="Enviar link" icon="pi pi-send" :loading="loading" :disabled="!email.trim()" size="large" fluid />
      </template>
      <RouterLink to="/login" class="back">Voltar para o login</RouterLink>
    </form>
  </main>
</template>

<style scoped>
.reset { min-height: 100%; display: grid; place-items: center; padding: 2rem; background: var(--surface-ground); }
.box { width: min(400px, 100%); display: flex; flex-direction: column; gap: 1.1rem; animation: srp-fade-up var(--dur-slow) var(--ease-out); }
.box h2 { font: 800 28px/1.1 var(--font-sans); letter-spacing: -0.02em; }
.logo { height: 34px; width: auto; align-self: flex-start; object-fit: contain; }
.logo--dark { display: none; }
:root[data-theme="dark"] .logo--light { display: none; }
:root[data-theme="dark"] .logo--dark { display: block; }
.field { display: flex; flex-direction: column; gap: 0.4rem; font-size: 13px; font-weight: 600; color: var(--text-strong); }
.back { align-self: center; font-size: 13px; color: var(--brand-600); }
</style>
