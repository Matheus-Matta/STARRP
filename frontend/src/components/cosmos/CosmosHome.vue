<script setup lang="ts">
/** Início do widget: saudação, "Nova conversa", sugestões e as conversas anteriores. */
import Button from "primevue/button";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { useCosmos } from "@/stores/cosmos";
import { useSession } from "@/stores/session";
import { dateTime } from "@/utils/format";

import CosmosAvatar from "./CosmosAvatar.vue";
import { suggestionsFor } from "./suggestions";

const cosmos = useCosmos();
const session = useSession();
const route = useRoute();
const firstName = computed(() => (session.me?.name ?? "").split(" ")[0]);
// A busca vai ao servidor (acha conversas que ainda n\u00e3o foram carregadas), com uma pausa curta ao digitar.
const search = ref(cosmos.conversationSearch);
let typing = 0;
watch(search, (term) => {
  window.clearTimeout(typing);
  typing = window.setTimeout(() => void cosmos.loadConversations(term), 300);
});
onBeforeUnmount(() => window.clearTimeout(typing));

// Rolagem infinita: o marcador no fim da lista apareceu \u2192 pr\u00f3xima p\u00e1gina.
const box = ref<HTMLElement | null>(null);
const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
onMounted(() => {
  observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) void cosmos.loadMoreConversations();
  }, { root: box.value, rootMargin: "80px" });
  if (sentinel.value) observer.observe(sentinel.value);
});
onBeforeUnmount(() => observer?.disconnect());

/** Atalhos para quem está usando: a tela aberta, os alertas e o que a pessoa mais faz (ver suggestions.ts). */
const suggestions = computed(() => suggestionsFor(route.path, cosmos.status, (code) => session.can(code)));

function start(text?: string) {
  cosmos.newConversation();
  if (text) cosmos.ask(text);
}

function relative(value: string) {
  const diff = (Date.now() - new Date(value).getTime()) / 60_000;
  if (diff < 1) return "agora";
  if (diff < 60) return `há ${Math.round(diff)} min`;
  if (diff < 60 * 24) return `há ${Math.round(diff / 60)} h`;
  return dateTime(value);
}
</script>

<template>
  <div class="home">
    <section class="hello">
      <CosmosAvatar :size="44" />
      <div>
        <h3>Olá{{ firstName ? `, ${firstName}` : "" }}!</h3>
        <p>Sou a Cosmos. Tiro dúvidas, consulto dados, ajudo nos cadastros e monto relatórios com gráficos.</p>
      </div>
    </section>

    <div v-if="cosmos.status && !cosmos.status.enabled" class="off">
      <i class="pi pi-info-circle" /> A Cosmos ainda não foi ligada neste servidor (falta a chave da OpenAI).
    </div>

    <Button label="Nova conversa" icon="pi pi-pencil" class="new" @click="start()" />

    <div class="suggest">
      <button v-for="s in suggestions" :key="s.text" type="button" class="suggest__item" @click="start(s.text)">
        <i :class="s.icon" /> <span>{{ s.text }}</span>
      </button>
    </div>

    <p v-if="cosmos.status?.can_write" class="tip">
      <i class="pi pi-paperclip" /> Anexe uma planilha (.xlsx, .csv) na conversa: a Cosmos lê e propõe os cadastros em
      lote para você confirmar.
    </p>

    <h4 v-if="cosmos.conversations.length || search" class="label">Conversas anteriores</h4>
    <label v-if="cosmos.conversations.length > 5 || search" class="search">
      <i class="pi pi-search" />
      <input v-model="search" type="search" placeholder="Buscar conversa" aria-label="Buscar conversa" />
    </label>
    <p v-if="search && !cosmos.conversations.length && !cosmos.conversationsLoading" class="none">
      Nenhuma conversa com "{{ search }}".
    </p>
    <!-- Rolagem própria; ao chegar perto do fim carrega a próxima página (20 por vez). -->
    <div v-show="cosmos.conversations.length" ref="box" class="list-box">
      <ul class="list">
        <li v-for="c in cosmos.conversations" :key="c.id">
          <button type="button" class="conv" @click="cosmos.openConversation(c.id)">
            <i :class="c.digest_day ? 'pi pi-users' : 'pi pi-comments'" />
            <span class="conv__text">
              <strong>{{ c.title }}</strong>
              <small>{{ relative(c.last_message_at) }}</small>
            </span>
          </button>
          <Button icon="pi pi-trash" text rounded size="small" severity="secondary" aria-label="Apagar conversa"
                  class="conv__del" @click="cosmos.removeConversation(c.id)" />
        </li>
      </ul>
      <div ref="sentinel" class="more" aria-hidden="true">
        <i v-if="cosmos.conversationsLoading && cosmos.conversations.length" class="pi pi-spin pi-spinner" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.home { padding: 16px; display: grid; gap: 12px; align-content: start; }
.hello { display: flex; gap: 12px; align-items: center; }
.hello h3 { margin: 0; font: 800 17px var(--font-sans); color: var(--text-strong); }
.hello p { margin: 2px 0 0; font-size: 12.5px; color: var(--text-muted); line-height: 1.45; }
.off { font-size: 12.5px; padding: 8px 10px; border-radius: 8px; background: var(--warning-subtle); color: var(--warning-text); }
.new { width: 100%; height: 38px; min-height: 38px; flex-shrink: 0; justify-content: center; }
.suggest { display: grid; gap: 6px; }
.suggest__item { display: flex; gap: 10px; align-items: center; text-align: left; padding: 9px 12px; cursor: pointer;
                 border: 1px solid var(--border); border-radius: 10px; background: var(--surface-card);
                 color: var(--text-body); font: 500 12.5px var(--font-sans); transition: border-color var(--dur-fast); }
.suggest__item:hover { border-color: var(--brand); color: var(--text-strong); }
.suggest__item i { color: var(--text-brand); }
.tip { margin: 0; font-size: 12px; color: var(--text-muted); line-height: 1.45; }
.tip .pi { color: var(--text-brand); font-size: 11px; }
.label { margin: 6px 0 0; font: 700 11px var(--font-sans); letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-subtle); }
.search { display: flex; align-items: center; gap: 8px; padding: 0 10px; height: 34px; border-radius: 8px;
          border: 1px solid var(--border); background: var(--surface-sunken); color: var(--text-subtle); }
.search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text-strong);
                font: 13px var(--font-sans); }
.none { margin: 0; font-size: 12.5px; color: var(--text-muted); }
.list-box { max-height: 300px; overflow-y: auto; overscroll-behavior: contain; margin: 0 -4px; padding: 0 4px; }
.more { display: grid; place-items: center; min-height: 24px; color: var(--text-subtle); font-size: 13px; }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.list li { display: flex; align-items: center; border-radius: 8px; }
.list li:hover { background: var(--surface-hover); }
.conv { flex: 1; min-width: 0; display: flex; gap: 10px; align-items: center; padding: 8px; border: 0; background: none;
        cursor: pointer; text-align: left; color: var(--text-body); }
.conv > i { color: var(--text-subtle); }
.conv__text { min-width: 0; display: grid; }
.conv__text strong { font-size: 13px; font-weight: 600; color: var(--text-strong); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv__text small { font-size: 11.5px; color: var(--text-muted); }
.conv__del { opacity: 0; }
.list li:hover .conv__del, .conv__del:focus-visible { opacity: 1; }
@media (hover: none) { .conv__del { opacity: 1; } }
</style>
