<script setup lang="ts">
import Button from "primevue/button";
import IconField from "primevue/iconfield";
import InputIcon from "primevue/inputicon";
import InputText from "primevue/inputtext";
import Message from "primevue/message";
import Password from "primevue/password";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { toApiError } from "@/api/errors";
import { useTheme } from "@/composables/useTheme";
import { useSession } from "@/stores/session";

const session = useSession();
const router = useRouter();
const route = useRoute();
const theme = useTheme();
const username = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

const features = [
  { icon: "pi pi-shopping-cart", title: "PDV rápido", text: "Leitor de código, balança, vários pagamentos e troco." },
  { icon: "pi pi-box", title: "Estoque com WMS", text: "Endereços, lotes, validade e entrada por NF-e." },
  { icon: "pi pi-chart-line", title: "Financeiro de verdade", text: "Caixa, contas a pagar e receber, DRE e fluxo." },
];

async function submit() {
  error.value = "";
  loading.value = true;
  try {
    const me = await session.login(username.value, password.value);
    if (!me) throw new Error("Seu usuário não está vinculado a nenhuma conta.");
    router.replace(String(route.query.next ?? "/"));
  } catch (e) {
    const apiError = toApiError(e);
    error.value = apiError.status === 401 ? "Usuário ou senha incorretos." : apiError.message || String(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login">
    <aside class="brand">
      <img src="/brand/logo-white.png" alt="Starrp" class="brand__logo" height="38" />
      <div class="brand__copy">
        <h1>Gestão completa para o seu comércio.</h1>
        <p>Da venda no balcão ao fechamento do mês, num lugar só.</p>
      </div>
      <ul>
        <li v-for="f in features" :key="f.title">
          <span><i :class="f.icon" /></span>
          <div><strong>{{ f.title }}</strong><small>{{ f.text }}</small></div>
        </li>
      </ul>
      <small class="brand__foot">© {{ new Date().getFullYear() }} Starrp</small>
    </aside>

    <main class="form-side">
      <button type="button" class="theme" :title="theme.resolved.value === 'dark' ? 'Tema claro' : 'Tema escuro'" @click="theme.toggle">
        <i :class="theme.resolved.value === 'dark' ? 'pi pi-sun' : 'pi pi-moon'" />
      </button>
      <form class="box" @submit.prevent="submit">
        <!-- No celular o painel azul some: o logo vem para cima do formulário (versão do tema). -->
        <img src="/brand/logo.png" alt="Starrp" class="box__logo box__logo--light" height="34" />
        <img src="/brand/logo-light.png" alt="" class="box__logo box__logo--dark" height="34" aria-hidden="true" />
        <h2>Entrar</h2>
        <p class="muted">Use o usuário e a senha fornecidos pelo administrador da sua loja.</p>
        <Message v-if="error" severity="error" :closable="false" icon="pi pi-exclamation-circle">{{ error }}</Message>
        <label class="field">
          <span>Usuário</span>
          <IconField><InputIcon class="pi pi-user" />
            <InputText v-model="username" autocomplete="username" autofocus fluid size="large" /></IconField>
        </label>
        <label class="field">
          <span>Senha</span>
          <Password v-model="password" :feedback="false" toggle-mask fluid size="large"
                    :input-props="{ autocomplete: 'current-password' }" />
        </label>
        <Button type="submit" label="Entrar" icon="pi pi-arrow-right" icon-pos="right" :loading="loading" size="large" fluid />
      </form>
    </main>
  </div>
</template>

<style scoped>
.login { min-height: 100%; display: grid; grid-template-columns: minmax(380px, 1fr) minmax(420px, 1.1fr); background: var(--surface-ground); }
.brand {
  position: relative; overflow: hidden; display: flex; flex-direction: column; gap: 2.5rem; padding: 3rem; color: #e6fffb;
  background: radial-gradient(120% 90% at 0% 0%, var(--brand-400) 0%, var(--brand-700) 45%, var(--brand-950) 100%);
}
.brand::after { content: ""; position: absolute; width: 420px; height: 420px; right: -140px; bottom: -160px; border-radius: 50%; background: rgba(255, 255, 255, 0.06); }
.brand__logo { position: relative; z-index: 1; height: 38px; width: auto; align-self: flex-start; }
.box__logo { display: none; height: 34px; width: auto; align-self: flex-start; object-fit: contain; margin-bottom: 0.5rem; }
.brand__copy { margin-top: auto; }
.brand h1 { color: #fff; font: 800 34px/1.15 var(--font-sans); letter-spacing: -0.02em; max-width: 440px; }
.brand p { margin-top: 12px; color: rgba(230, 255, 251, 0.82); font-size: 15px; }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
li { display: flex; gap: 12px; align-items: flex-start; padding: 12px; border-radius: 12px; background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.08); transition: background-color var(--dur-base) ease, transform var(--dur-base) var(--ease-out); }
li:hover { background: rgba(255, 255, 255, 0.11); transform: translateX(3px); }
li span { width: 34px; height: 34px; flex-shrink: 0; border-radius: 9px; display: grid; place-items: center; background: rgba(255, 255, 255, 0.14); color: #fff; }
li strong { display: block; color: #fff; font-size: 14px; }
li small { color: rgba(230, 255, 251, 0.75); font-size: 12.5px; }
.brand__foot { color: rgba(230, 255, 251, 0.55); }
.form-side { position: relative; display: grid; place-items: center; padding: 2rem; }
.theme { position: absolute; top: 20px; right: 20px; width: 40px; height: 40px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface-card); color: var(--text-muted); cursor: pointer; }
.theme:hover { color: var(--text-strong); border-color: var(--brand-border); }
.box { width: min(400px, 100%); display: flex; flex-direction: column; gap: 1.1rem; animation: srp-fade-up var(--dur-slow) var(--ease-out); }
.box h2 { font: 800 28px/1.1 var(--font-sans); letter-spacing: -0.02em; }
.box > p { margin-top: -0.6rem; }
.field { display: flex; flex-direction: column; gap: 0.4rem; font-size: 13px; font-weight: 600; color: var(--text-strong); }
@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .brand { display: none; }
  .box__logo--light { display: block; }
  :root[data-theme="dark"] .box__logo--light { display: none; }
  :root[data-theme="dark"] .box__logo--dark { display: block; }
}
</style>
