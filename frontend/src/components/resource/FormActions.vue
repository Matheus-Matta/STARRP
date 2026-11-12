<script lang="ts">
import { shallowRef as pendingRef } from "vue";

import type { FormAction as PendingAction } from "@/resources/types";

/** Diálogo `then` esperando o registro recarregar (sobrevive à troca formulário → leitura). */
const pendingThen = pendingRef<{ id: string; then: NonNullable<PendingAction["then"]> } | null>(null);
</script>

<script setup lang="ts">
/**
 * Botões extras do formulário (`ResourceDef.formActions`): confirmar documento,
 * cancelar, imprimir, fechar caixa... Cada um chama a API (`run`) ou abre um
 * diálogo próprio (`dialog`). Some quando `visible(values)` diz que não cabe.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { useConfirm } from "primevue/useconfirm";
import { computed, nextTick, onMounted, ref, shallowRef, watch } from "vue";

import { useNotify } from "@/composables/useNotify";
import type { FormAction, FormActionContext } from "@/resources/types";
import { useSession } from "@/stores/session";

const props = defineProps<{ actions: FormAction[]; ctx: FormActionContext }>();
const notify = useNotify();
const confirm = useConfirm();
const running = ref<string | null>(null);
const open = shallowRef<{ label: string; dialog?: FormAction["dialog"]; then?: FormAction["then"] } | null>(null);

const session = useSession();

async function openPending() {
  const pending = pendingThen.value;
  if (!pending || pending.id !== props.ctx.id) return;
  if (pending.then.visible && !pending.then.visible(props.ctx.values)) return;
  pendingThen.value = null;
  // `auto` resolve sozinho (ex.: a regra de logística manda imprimir direto): sem diálogo.
  if (pending.then.auto) {
    try {
      if (await pending.then.auto(props.ctx)) return;
    } catch (error) {
      notify.error(error, `Não foi possível: ${pending.then.label.toLowerCase()}`);
      return;
    }
  }
  open.value = pending.then;
}
onMounted(openPending);
watch(() => props.ctx.values, openPending);
const shown = computed(() => props.actions.filter((a) => (!a.permission || session.can(a.permission))
  && session.hasModule(a.module) && (!a.visible || a.visible(props.ctx.values))));

async function execute(action: FormAction) {
  running.value = action.label;
  try {
    await action.run!(props.ctx);
    if (action.success) notify.success(action.success);
    // O diálogo seguinte (ex.: imprimir etiquetas) fica pendente FORA do componente: depois de
    // confirmar, a página troca para a leitura e recria estes botões.
    if (action.then) pendingThen.value = { id: props.ctx.id, then: action.then };
    await props.ctx.reload();
    await nextTick();
    await openPending();
  } catch (error) {
    notify.error(error, `Não foi possível: ${action.label.toLowerCase()}`);
  } finally {
    running.value = null;
  }
}

function start(action: FormAction) {
  if (action.dialog) {
    open.value = action;
    return;
  }
  if (!action.confirm) return void execute(action);
  confirm.require({
    header: action.label, message: action.confirm, icon: "pi pi-exclamation-triangle",
    acceptProps: { label: action.label, severity: action.severity === "danger" ? "danger" : undefined },
    rejectProps: { label: "Voltar", severity: "secondary", outlined: true },
    accept: () => execute(action),
  });
}

async function onDone() {
  const then = open.value?.then;
  open.value = null;
  if (then) pendingThen.value = { id: props.ctx.id, then };
  await props.ctx.reload();
  await nextTick();
  await openPending();
}
</script>

<template>
  <div class="actions">
    <Button v-for="action in shown" :key="action.label" :label="action.label" :icon="action.icon" size="small"
            :severity="action.severity ?? 'secondary'" :outlined="!action.severity || action.severity === 'secondary'"
            :loading="running === action.label" :disabled="running !== null" @click="start(action)" />
    <Dialog :visible="open !== null" modal :header="open?.label" :style="{ width: 'min(760px, calc(100vw - 24px))' }"
            @update:visible="open = null">
      <component :is="open.dialog" v-if="open?.dialog" :ctx="ctx" @done="onDone" @close="open = null" />
    </Dialog>
  </div>
</template>

<style scoped>
.actions { display: flex; gap: 0.4rem; flex-wrap: wrap; justify-content: flex-end; }
</style>
