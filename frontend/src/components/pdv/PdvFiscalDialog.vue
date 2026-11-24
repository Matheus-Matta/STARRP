<script setup lang="ts">
/**
 * Nota fiscal deste caixa (PDV web): emite pelo Comunicador Fiscal em NUVEM (Docker), que só o
 * backend chama — com o token, a cifra e o certificado A1 + CSC dos dados fiscais da filial.
 * Aqui ficam só os ajustes de emissão; nenhum segredo passa pelo navegador.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import SelectButton from "primevue/selectbutton";
import ToggleSwitch from "primevue/toggleswitch";
import { reactive, ref, watch } from "vue";

import { useNotify } from "@/composables/useNotify";
import { fiscal, fiscalSettings, saveFiscalSettings } from "@/fiscal/pdvFiscal";

const props = defineProps<{ visible: boolean }>();
const emit = defineEmits<{ close: [] }>();
const notify = useNotify();

const draft = reactive({ ...fiscalSettings });
const busy = ref<string | null>(null);
const health = ref<{ ok: boolean; message: string } | null>(null);
const kit = ref(fiscal.kitInfo());
const models = [{ label: "NFC-e (65)", value: "65" }, { label: "NF-e (55)", value: "55" }];

watch(() => props.visible, (open) => {
  if (!open) return;
  Object.assign(draft, fiscalSettings);
  health.value = null;
  kit.value = fiscal.kitInfo();
});

function save() {
  saveFiscalSettings({ ...draft });
}

async function run(name: string, action: () => Promise<void>) {
  busy.value = name;
  try {
    save();
    await action();
  } finally {
    busy.value = null;
  }
}

const test = () => run("health", async () => {
  health.value = await fiscal.health();
});
const refreshKit = () => run("kit", async () => {
  kit.value = await fiscal.refreshKit();
  if (kit.value.error) notify.warn("Kit fiscal", kit.value.error);
  else notify.success("Kit fiscal atualizado");
});

function close() {
  save();
  emit("close");
}
</script>

<template>
  <Dialog :visible="visible" modal header="Nota fiscal deste caixa" :style="{ width: 'min(640px, calc(100vw - 24px))' }"
          @update:visible="close">
    <div class="fiscal">
      <label class="toggle">
        <ToggleSwitch v-model="draft.enabled" />
        <span><strong>Emitir NFC-e/NF-e por este caixa</strong>
          <small>Pelo Comunicador Fiscal na nuvem, chamado pelo servidor. A filial precisa do provedor ACBrLib, do certificado A1 e do CSC nos dados fiscais, e da emissão no terminal ligada.</small></span>
      </label>

      <section>
        <h3>Comunicador fiscal (nuvem)</h3>
        <p class="hint">
          O servidor guarda o acesso ao comunicador e o certificado da filial, e cifra cada nota de ponta a ponta.
          Este navegador não guarda token, chave nem certificado. Sem internet, este caixa não emite: para vender
          e emitir offline, use o PDV desktop.
        </p>
        <div class="actions">
          <Button size="small" severity="secondary" icon="pi pi-bolt" label="Testar comunicador e SEFAZ" :loading="busy === 'health'" @click="test" />
        </div>
        <p v-if="health" class="status" :class="health.ok ? 'ok' : 'bad'">
          <i :class="health.ok ? 'pi pi-check-circle' : 'pi pi-times-circle'" /> {{ health.message }}
        </p>
      </section>

      <section>
        <h3>Emissão</h3>
        <SelectButton v-model="draft.model" :options="models" option-label="label" option-value="value" :allow-empty="false" />
        <label class="toggle"><ToggleSwitch v-model="draft.autoEmit" />
          <span><strong>Emitir ao concluir a venda</strong><small>Desligado: emita pelo pedido (F2).</small></span></label>
        <label class="toggle"><ToggleSwitch v-model="draft.contingency" />
          <span><strong>Contingência offline (NFC-e)</strong><small>SEFAZ fora: o comunicador assina, imprime e a nota é transmitida depois.</small></span></label>
      </section>

      <section>
        <h3>Kit fiscal (do servidor)</h3>
        <dl v-if="kit.ready" class="kit">
          <dt>Emitente</dt><dd>{{ kit.issuer?.legal_name }} · {{ kit.issuer?.state }}</dd>
          <dt>Ambiente</dt><dd>{{ kit.environment === "1" ? "Produção" : "Homologação" }}</dd>
          <dt>Série deste caixa</dt>
          <dd>{{ Object.entries(kit.series ?? {}).map(([m, s]) => `${m === "65" ? "NFC-e" : "NF-e"} série ${s.series} (próx. ${s.next_number})`).join(" · ") }}</dd>
        </dl>
        <p v-else class="hint">{{ kit.error }}</p>
        <Button size="small" severity="secondary" icon="pi pi-download" label="Baixar kit agora" :loading="busy === 'kit'" @click="refreshKit" />
      </section>
    </div>
  </Dialog>
</template>

<style scoped>
.fiscal { display: flex; flex-direction: column; gap: 16px; }
section { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; border-top: 1px solid var(--border-subtle); }
h3 { margin: 0; font-size: 13px; font-weight: 700; color: var(--text-strong); text-transform: uppercase; letter-spacing: .03em; }
.toggle { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }
.toggle span { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
.toggle small, .hint { font-size: 12px; color: var(--text-muted); margin: 0; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.status { margin: 0; padding: 8px 12px; border-radius: 8px; font-size: 12.5px; }
.status.ok { background: var(--success-subtle); color: var(--success-text); }
.status.bad { background: var(--danger-subtle); color: var(--danger-text); }
.kit { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0; font-size: 13px; }
.kit dt { color: var(--text-muted); }
.kit dd { margin: 0; color: var(--text-strong); }
</style>
