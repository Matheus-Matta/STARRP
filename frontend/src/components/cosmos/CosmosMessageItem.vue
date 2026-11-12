<script setup lang="ts">
/** Uma fala na conversa: do usuário (à direita), da Cosmos (texto + blocos) ou um aviso do sistema. */
import Button from "primevue/button";
import { computed } from "vue";
import { useRouter } from "vue-router";

import type { CosmosAction, CosmosButton, CosmosMessage } from "@/api/cosmos";
import { renderMarkdown } from "@/utils/markdown";

import CosmosActionCard from "./CosmosActionCard.vue";
import CosmosAvatar from "./CosmosAvatar.vue";
import CosmosReportCard from "./CosmosReportCard.vue";

const props = defineProps<{ message: CosmosMessage; busy?: boolean; last?: boolean }>();
const emit = defineEmits<{ reply: [text: string]; decide: [action: CosmosAction, approve: boolean];
                          decideAll: [actions: CosmosAction[], approve: boolean] }>();
const router = useRouter();

const html = computed(() => renderMarkdown(props.message.content));
/** Várias propostas pendentes na mesma resposta: dá para decidir todas de uma vez. */
const pending = computed(() => props.message.blocks.flatMap((b) => (b.type === "action" && b.action.status === "pending"
  ? [b.action] : [])));
/** Avisos ao modelo ("O usuário CONFIRMOU...") viram uma linha discreta para a pessoa. */
const eventText = computed(() => {
  const text = props.message.content;
  if (text.includes("CANCELOU")) return "Proposta cancelada";
  if (text.includes("CONFIRMOU")) return text.includes("FALHOU") ? "Proposta confirmada — falhou ao gravar" : "Proposta confirmada";
  return "Aviso do sistema";
});

function onButton(button: CosmosButton) {
  if (button.kind === "link") void router.push(button.value);
  else emit("reply", button.value);
}

function onClick(event: MouseEvent) {
  const link = (event.target as HTMLElement).closest("a[data-internal='1']");
  if (link) {
    event.preventDefault();
    void router.push(link.getAttribute("href") ?? "/");
  }
}
</script>

<template>
  <div v-if="message.role === 'event'" class="event"><span>{{ eventText }}</span></div>
  <div v-else-if="message.role === 'user'" class="row row--user">
    <div class="user">
      <template v-for="(block, i) in message.blocks" :key="i">
        <ul v-if="block.type === 'attachments'" class="sent-files">
          <li v-for="f in block.items" :key="f.id">
            <i :class="f.kind === 'sheet' ? 'pi pi-file-excel' : 'pi pi-file'" />
            <span>{{ f.name }}</span>
            <small v-if="f.kind === 'sheet'">{{ f.rows }} {{ f.rows === 1 ? "linha" : "linhas" }}</small>
          </li>
        </ul>
      </template>
      <div class="bubble bubble--user">{{ message.content }}</div>
    </div>
  </div>
  <div v-else class="row row--bot">
    <CosmosAvatar :size="26" />
    <div class="stack">
      <!-- eslint-disable-next-line vue/no-v-html — HTML gerado por renderMarkdown, que escapa tudo antes -->
      <div v-if="message.content" class="bubble bubble--bot md" @click="onClick" v-html="html" />
      <template v-for="(block, i) in message.blocks" :key="i">
        <CosmosReportCard v-if="block.type === 'report'" :report="block.report" />
        <CosmosActionCard v-else-if="block.type === 'action'" :action="block.action" :busy="busy"
                          @decide="(approve) => emit('decide', block.action, approve)" />
        <div v-if="block.type === 'action' && pending.length > 1 && block.action.id === pending[pending.length - 1]!.id"
             class="bulk">
          <span>{{ pending.length }} propostas aguardando</span>
          <Button label="Cancelar todas" size="small" text severity="secondary" :disabled="busy"
                  @click="emit('decideAll', pending, false)" />
          <Button :label="`Confirmar todas (${pending.length})`" icon="pi pi-check" size="small" :loading="busy"
                  @click="emit('decideAll', pending, true)" />
        </div>
        <!-- Atalhos só na última resposta (os antigos já não valem) e no máximo 5. -->
        <div v-else-if="block.type === 'buttons' && last" class="chips">
          <Button v-for="b in block.buttons.slice(0, 5)" :key="b.label" :label="b.label" size="small" rounded outlined
                  :icon="b.kind === 'link' ? 'pi pi-arrow-up-right' : undefined" icon-pos="right"
                  :disabled="busy" @click="onButton(b)" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.row { display: flex; gap: 8px; align-items: flex-start; }
.row--user { justify-content: flex-end; }
.stack { min-width: 0; flex: 1; display: grid; gap: 8px; justify-items: start; }
.stack > * { max-width: 100%; }
.stack > :deep(article) { width: 100%; }
.bubble { padding: 9px 12px; border-radius: 14px; font-size: 13.5px; line-height: 1.5; overflow-wrap: anywhere; }
.user { max-width: 85%; min-width: 0; display: grid; gap: 4px; justify-items: end; }
.sent-files { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; justify-items: end; max-width: 100%; }
.sent-files li { display: inline-flex; gap: 6px; align-items: center; padding: 6px 10px; border-radius: 10px; font-size: 12px;
                 border: 1px solid var(--border); background: var(--surface-sunken); color: var(--text-body); max-width: 100%; }
.sent-files span { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sent-files small { color: var(--text-muted); }
.sent-files .pi { color: var(--text-brand); }
.bubble--user { white-space: pre-wrap; background: var(--brand); color: var(--on-brand);
                border-bottom-right-radius: 4px; }
.bubble--bot { background: var(--surface-sunken); color: var(--text-body); border: 1px solid var(--border-subtle);
               border-top-left-radius: 4px; }
.event { display: flex; justify-content: center; }
.event span { font-size: 11.5px; color: var(--text-muted); padding: 2px 10px; border-radius: var(--radius-pill);
              background: var(--surface-sunken); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.bulk { width: 100%; display: flex; align-items: center; gap: 4px; padding: 6px 10px; border-radius: var(--radius-md);
        background: var(--surface-sunken); border: 1px dashed var(--border-strong); font-size: 12.5px; color: var(--text-muted); }
.bulk span { flex: 1; }
.md :deep(p) { margin: 0 0 6px; }
.md :deep(p:last-child) { margin-bottom: 0; }
.md :deep(ul), .md :deep(ol) { margin: 2px 0 6px; padding-left: 18px; }
.md :deep(h3), .md :deep(h4), .md :deep(h5), .md :deep(h6) { margin: 6px 0 4px; font-size: 13.5px; color: var(--text-strong); }
.md :deep(strong) { color: var(--text-strong); }
.md :deep(code) { font: 12px var(--font-mono); padding: 1px 4px; border-radius: 4px; background: var(--surface-active); }
.md :deep(pre) { margin: 6px 0; padding: 8px; border-radius: 8px; background: var(--surface-active); overflow-x: auto; }
.md :deep(a) { color: var(--text-brand); font-weight: 600; }
.md :deep(.md-table) { overflow-x: auto; margin: 6px 0; }
.md :deep(table) { border-collapse: collapse; font-size: 12.5px; width: 100%; }
.md :deep(th), .md :deep(td) { padding: 4px 8px; border-bottom: 1px solid var(--border-subtle); text-align: left; white-space: nowrap; }
.md :deep(th) { color: var(--text-muted); font-weight: 700; }
</style>
