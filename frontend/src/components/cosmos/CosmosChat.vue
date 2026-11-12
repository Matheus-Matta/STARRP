<script setup lang="ts">
/** A conversa aberta: falas, o texto da Cosmos chegando ao vivo, o que ela está fazendo e o campo de envio. */
import { computed, nextTick, ref, watch } from "vue";

import { useCosmos } from "@/stores/cosmos";
import { renderMarkdown } from "@/utils/markdown";

import CosmosAvatar from "./CosmosAvatar.vue";
import CosmosMessageItem from "./CosmosMessageItem.vue";

const cosmos = useCosmos();
const draft = ref("");
const scroller = ref<HTMLElement | null>(null);
const input = ref<HTMLTextAreaElement | null>(null);
const picker = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const ACCEPT = ".xlsx,.xlsm,.csv,.tsv,.txt,.md,.json";

const key = computed(() => cosmos.key);
const busy = computed(() => Boolean(cosmos.busy[key.value]));
const live = computed(() => cosmos.live[key.value] ?? "");
const doing = computed(() => cosmos.doing[key.value] ?? "");
const error = computed(() => cosmos.errors[key.value] ?? "");
const offline = computed(() => cosmos.connection !== "on");
const attached = computed(() => cosmos.files[key.value] ?? []);
const uploading = computed(() => cosmos.uploading > 0);
const canSend = computed(() => !busy.value && !offline.value && !uploading.value
  && (Boolean(draft.value.trim()) || attached.value.length > 0));
const lastBot = computed(() => [...cosmos.thread].reverse().find((m) => m.role === "assistant")?.id);

/** O campo cresce com o texto (até ~6 linhas) e volta a uma linha ao enviar. */
function grow() {
  const el = input.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
}

function send(text = draft.value) {
  if (busy.value || uploading.value || (!text.trim() && !attached.value.length)) return;
  if (cosmos.ask(text)) {
    draft.value = "";
    void nextTick(grow);
  }
}

/** Enter envia; Shift+Enter quebra a linha. */
function onKey(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send();
  }
}

function onPick(event: Event) {
  const el = event.target as HTMLInputElement;
  if (el.files?.length) void cosmos.attach(el.files);
  el.value = "";
}

/** Arrastar uma planilha para a conversa anexa (como o clipe). */
let depth = 0; // dragenter/dragleave disparam a cada elemento de dentro: conta para saber quando saiu de vez
function onDrag(step: number) {
  depth = Math.max(0, depth + step);
  dragging.value = depth > 0;
}

function onDrop(event: DragEvent) {
  depth = 0;
  dragging.value = false;
  if (event.dataTransfer?.files.length && !offline.value) void cosmos.attach(event.dataTransfer.files);
}

async function toBottom() {
  await nextTick();
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: "smooth" });
}
watch(() => [cosmos.thread.length, live.value.length, doing.value, busy.value], toBottom, { immediate: true });
</script>

<template>
  <div class="chat" @dragenter.prevent="onDrag(1)" @dragleave="onDrag(-1)" @dragover.prevent @drop.prevent="onDrop">
    <div v-if="dragging" class="chat__dropzone"><i class="pi pi-file-excel" /> Solte a planilha para anexar</div>
    <div ref="scroller" class="chat__scroll">
      <div v-if="!cosmos.thread.length && !busy" class="chat__empty">
        <CosmosAvatar :size="40" />
        <p>Como posso ajudar? Pergunte sobre vendas, estoque, clientes, peça um relatório ou um cadastro.</p>
      </div>
      <CosmosMessageItem v-for="m in cosmos.thread" :key="m.id" :message="m" :busy="busy" :last="m.id === lastBot"
                         @reply="send" @decide="(action, approve) => cosmos.decide(action, approve)"
                         @decide-all="(actions, approve) => cosmos.decide(actions, approve)" />
      <div v-if="busy" class="row">
        <CosmosAvatar :size="26" pulse />
        <div class="live">
          <!-- eslint-disable-next-line vue/no-v-html — renderMarkdown escapa todo o texto -->
          <div v-if="live" class="bubble md" v-html="renderMarkdown(live)" />
          <!-- Pensando: os pontos pulando e, ao lado, o que ela está fazendo ("Consultando os dados…"). -->
          <div v-else class="typing" role="status" :aria-label="doing || 'Cosmos está digitando'">
            <span class="typing__dots" aria-hidden="true"><span /><span /><span /></span>
            <transition name="fade" mode="out-in">
              <span v-if="doing" :key="doing" class="typing__text">{{ doing }}</span>
            </transition>
          </div>
          <small v-if="live && doing" class="doing">{{ doing }}</small>
        </div>
      </div>
    </div>

    <p v-if="error" class="chat__error">
      <i class="pi pi-exclamation-circle" /> <span class="grow">{{ error }}</span>
      <button v-if="cosmos.lastAsked[key] && !offline" type="button" class="retry" @click="cosmos.retryLast()">
        <i class="pi pi-refresh" /> Tentar de novo
      </button>
    </p>
    <form class="composer" @submit.prevent="send()">
      <ul v-if="attached.length || uploading" class="files">
        <li v-for="f in attached" :key="f.id" class="file">
          <i :class="f.kind === 'sheet' ? 'pi pi-file-excel' : 'pi pi-file'" />
          <span class="file__name" :title="f.name">{{ f.name }}</span>
          <small v-if="f.kind === 'sheet'">{{ f.rows }} {{ f.rows === 1 ? "linha" : "linhas" }}</small>
          <button type="button" class="file__del" :aria-label="`Tirar ${f.name}`" @click="cosmos.detach(f.id)">
            <i class="pi pi-times" />
          </button>
        </li>
        <li v-if="uploading" class="file file--busy"><i class="pi pi-spin pi-spinner" /> Lendo o arquivo…</li>
      </ul>
      <input ref="picker" type="file" :accept="ACCEPT" multiple hidden @change="onPick" />
      <button type="button" class="composer__attach" aria-label="Anexar planilha ou arquivo"
              title="Anexar planilha (.xlsx, .csv) ou texto" :disabled="offline || busy" @click="picker?.click()">
        <i class="pi pi-paperclip" />
      </button>
      <textarea ref="input" v-model="draft" rows="1" class="composer__input" :class="{ 'composer__input--off': offline }"
                :disabled="offline" aria-label="Mensagem para a Cosmos"
                :placeholder="offline ? 'Conectando à Cosmos…' : 'Enviar mensagem...'" @input="grow" @keydown="onKey" />
      <!-- Respondendo: o botão vira "Parar". -->
      <button v-if="busy && cosmos.activeId" type="button" class="composer__send composer__send--stop" aria-label="Parar"
              title="Parar a resposta" @click="cosmos.stop()">
        <i class="pi pi-stop" />
      </button>
      <button v-else type="submit" class="composer__send" aria-label="Enviar" :disabled="!canSend">
        <i class="pi pi-arrow-up" />
      </button>
    </form>
    <small class="hint">A Cosmos pode errar. Toda gravação pede a sua confirmação.</small>
  </div>
</template>

<style scoped>
.chat { position: relative; display: flex; flex-direction: column; min-height: 0; height: 100%; }
.chat__dropzone { position: absolute; inset: 8px; z-index: 2; display: grid; place-content: center; justify-items: center;
                  gap: 8px; border: 2px dashed var(--brand); border-radius: var(--radius-lg); pointer-events: none;
                  background: color-mix(in srgb, var(--surface-card) 88%, transparent); color: var(--text-strong);
                  font: 600 13px var(--font-sans); }
.chat__dropzone .pi { font-size: 26px; color: var(--text-brand); }
.chat__scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.chat__empty { margin: auto 0; display: grid; justify-items: center; gap: 10px; text-align: center; color: var(--text-muted);
               font-size: 13px; padding: 0 20px; }
.row { display: flex; gap: 8px; align-items: flex-start; }
.live { display: grid; gap: 4px; min-width: 0; flex: 1; justify-items: start; }
.bubble { padding: 9px 12px; border-radius: 14px; border-top-left-radius: 4px; font-size: 13.5px; line-height: 1.5;
          background: var(--surface-sunken); border: 1px solid var(--border-subtle); color: var(--text-body); max-width: 100%; }
.md :deep(p) { margin: 0 0 6px; }
.md :deep(p:last-child) { margin: 0; }
.md :deep(ul), .md :deep(ol) { margin: 2px 0 6px; padding-left: 18px; }
.typing { display: inline-flex; align-items: center; gap: 10px; min-height: 40px; max-width: 100%; padding: 10px 14px;
          border-radius: 14px; border-top-left-radius: 4px; background: var(--surface-sunken);
          border: 1px solid var(--border-subtle); }
/* Os três pontos sobem e descem em onda (o "pensando" de chat). */
.typing__dots { display: inline-flex; align-items: center; gap: 4px; height: 14px; flex-shrink: 0; }
.typing__dots span { width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted);
                     animation: think 1.2s ease-in-out infinite; }
/* Exceção ao "movimento reduzido" global (base.css desliga toda animação): sem os pontos andando
   parece que a Cosmos travou. É pequeno, curto e só enquanto ela responde. */
@media (prefers-reduced-motion: reduce) {
  .typing__dots span { animation: think 1.2s ease-in-out infinite !important; }
  .typing__dots span:nth-child(2) { animation-delay: 0.16s !important; }
  .typing__dots span:nth-child(3) { animation-delay: 0.32s !important; }
}
.typing__dots span:nth-child(2) { animation-delay: 0.16s; }
.typing__dots span:nth-child(3) { animation-delay: 0.32s; }
@keyframes think {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.45; }
  30% { transform: translateY(-6px); opacity: 1; }
}
.typing__text { min-width: 0; font-size: 12.5px; color: var(--text-muted); white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }
.fade-enter-active, .fade-leave-active { transition: opacity var(--dur-fast) ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.doing { font-size: 11.5px; color: var(--text-muted); }
.chat__error { margin: 0 14px; padding: 6px 10px; border-radius: 8px; font-size: 12.5px; background: var(--danger-subtle);
               color: var(--danger-text); display: flex; gap: 6px; align-items: center; }
/* Campo de largura total com o botão de enviar DENTRO dele, à direita. */
.composer { position: relative; margin: 10px 12px 4px; }
.composer__input { display: block; width: 100%; min-height: 46px; max-height: 140px; padding: 11px 48px 11px 42px;
                   border-radius: 10px; border: 2px solid var(--brand); background: var(--surface-sunken);
                   color: var(--text-strong); font: 14px/1.45 var(--font-sans); outline: 0; resize: none; overflow-y: auto;
                   transition: border-color var(--dur-fast), box-shadow var(--dur-fast); }
.composer__input:focus { box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 22%, transparent); }
.composer__input::placeholder { color: var(--text-subtle); }
.composer__input--off { border-color: var(--border-strong); }
.files { list-style: none; margin: 0 0 6px; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.file { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 4px 6px 4px 9px; border-radius: 8px;
        border: 1px solid var(--border); background: var(--surface-sunken); font-size: 12px; color: var(--text-body); }
.file > .pi { color: var(--text-brand); }
.file__name { min-width: 0; max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.file small { color: var(--text-muted); }
.file__del { border: 0; background: none; color: var(--text-subtle); cursor: pointer; padding: 2px; display: grid; }
.file__del:hover { color: var(--text-strong); }
.file--busy { color: var(--text-muted); padding-right: 9px; }
.composer__attach { position: absolute; bottom: 7px; left: 6px; width: 32px; height: 32px; display: grid; place-items: center;
                    border: 0; border-radius: 8px; background: transparent; color: var(--text-muted); cursor: pointer; }
.composer__attach:hover:not(:disabled) { background: var(--surface-active); color: var(--text-strong); }
.composer__attach:disabled { color: var(--text-subtle); cursor: default; }
.composer__send { position: absolute; bottom: 7px; right: 8px; width: 32px; height: 32px;
                  display: grid; place-items: center; border: 0; border-radius: 8px; background: transparent;
                  color: var(--text-strong); cursor: pointer; transition: background var(--dur-fast); }
.composer__send:hover:not(:disabled) { background: var(--surface-active); }
.composer__send:disabled { color: var(--text-subtle); cursor: default; }
.composer__send .pi { font-size: 14px; }
.composer__send--stop { color: var(--danger-text); }
.grow { flex: 1; }
.retry { border: 0; background: none; color: inherit; font: 600 12px var(--font-sans); cursor: pointer;
         display: inline-flex; gap: 4px; align-items: center; text-decoration: underline; }
.hint { padding: 0 14px 8px; font-size: 10.5px; color: var(--text-subtle); text-align: center; }
</style>
