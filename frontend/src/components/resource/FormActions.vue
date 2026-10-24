<script setup lang="ts">
/**
 * Botões extras do formulário (`ResourceDef.formActions`): confirmar documento,
 * cancelar, imprimir, fechar caixa... Cada um chama a API (`run`) ou abre um
 * diálogo próprio (`dialog`). Some quando `visible(values)` diz que não cabe.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { useConfirm } from "primevue/useconfirm";
import { computed, ref, shallowRef } from "vue";

import { useNotify } from "@/composables/useNotify";
import type { FormAction, FormActionContext } from "@/resources/types";
import { useSession } from "@/stores/session";

const props = defineProps<{ actions: FormAction[]; ctx: FormActionContext }>();
const notify = useNotify();
const confirm = useConfirm();
const running = ref<string | null>(null);
const open = shallowRef<FormAction | null>(null);

const session = useSession();
const shown = computed(() => props.actions.filter((a) => (!a.permission || session.can(a.permission))
  && (!a.visible || a.visible(props.ctx.values))));

async function execute(action: FormAction) {
  running.value = action.label;
  try {
    await action.run!(props.ctx);
    if (action.success) notify.success(action.success);
    await props.ctx.reload();
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
  open.value = null;
  await props.ctx.reload();
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
