<script setup lang="ts">
/**
 * Tela bloqueada do caixa: cobre o PDV inteiro (venda e valores ficam escondidos).
 * Volta com a senha do próprio operador ou a senha de ações do caixa (o gerente
 * que veio liberar). Recarregar a página NÃO desbloqueia.
 */
import Button from "primevue/button";
import Password from "primevue/password";
import { nextTick, onMounted, ref } from "vue";

const props = defineProps<{ operator: string; unlock: (password: string) => Promise<void>; managerPassword: boolean }>();
const emit = defineEmits<{ logout: [] }>();
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  if (!password.value || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await props.unlock(password.value);
  } catch {
    error.value = "Senha incorreta.";
    password.value = "";
    await nextTick();
    document.getElementById("pdv-unlock")?.focus();
  } finally {
    busy.value = false;
  }
}
onMounted(() => document.getElementById("pdv-unlock")?.focus());
</script>

<template>
  <div class="lock" role="dialog" aria-modal="true" aria-label="Caixa bloqueado">
    <form class="lock__card" @submit.prevent="submit">
      <span class="lock__icon"><i class="pi pi-lock" /></span>
      <h2>Caixa bloqueado</h2>
      <p>Operador: <b>{{ operator }}</b>. Digite a sua senha{{ managerPassword ? " ou a senha de ações do caixa" : "" }} para voltar.</p>
      <Password v-model="password" input-id="pdv-unlock" :feedback="false" toggle-mask fluid size="large"
                placeholder="Senha" :invalid="!!error" />
      <small v-if="error" class="lock__error"><i class="pi pi-exclamation-circle" /> {{ error }}</small>
      <Button type="submit" label="Desbloquear" icon="pi pi-lock-open" size="large" :loading="busy" fluid />
      <Button label="Trocar de operador (sair)" severity="secondary" text size="small" @click="emit('logout')" />
    </form>
  </div>
</template>

<style scoped>
.lock {
  position: fixed; inset: 0; z-index: 1200; display: grid; place-items: center; padding: 16px;
  background: color-mix(in srgb, var(--surface-ground) 70%, transparent); backdrop-filter: blur(14px);
}
.lock__card {
  width: min(380px, 100%); display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 28px 24px;
  border-radius: 16px; border: 1px solid var(--border); background: var(--surface-card); box-shadow: var(--shadow-lg); text-align: center;
}
.lock__icon { width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; background: var(--brand-subtle); color: var(--brand); font-size: 22px; }
.lock__card h2 { margin: 0; font: 800 20px/1.2 var(--font-sans); color: var(--text-strong); }
.lock__card p { margin: 0; font-size: 13.5px; color: var(--text-muted); }
.lock__card :deep(.p-password), .lock__card :deep(.p-password-input) { width: 100%; }
.lock__error { color: var(--danger-text); align-self: flex-start; display: flex; gap: 6px; align-items: center; }
</style>
