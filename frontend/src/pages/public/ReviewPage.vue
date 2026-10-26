<script setup lang="ts">
/**
 * Página que o cliente abre pelo link da venda (sem login, pensada para o celular):
 * estrelas para a entrega (quando teve entrega) e para cada produto, comentário e até 3
 * fotos por produto. Item já avaliado aparece como "Avaliado". No fim, um obrigado.
 */
import { useQuery } from "@tanstack/vue-query";
import Button from "primevue/button";
import Textarea from "primevue/textarea";
import { computed, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import { toApiError } from "@/api/errors";
import { reviewsApi } from "@/api/reviews";
import StarRating from "@/components/reviews/StarRating.vue";
import { date } from "@/utils/format";

const route = useRoute();
const token = String(route.params.token);
const query = useQuery({ queryKey: ["public-review", token], queryFn: () => reviewsApi.publicView(token), retry: false });
const view = computed(() => query.data.value);

type Answer = { rating: number | null; comment: string; photos: File[]; previews: string[] };
const delivery = reactive<Answer>({ rating: null, comment: "", photos: [], previews: [] });
const answers = reactive<Record<string, Answer>>({});
const answer = (id: string) => (answers[id] ??= { rating: null, comment: "", photos: [], previews: [] });
const sending = ref(false);
const error = ref("");
const done = ref(false);

const pending = computed(() => (view.value?.products ?? []).filter((p) => !p.done));
const canSend = computed(() => Boolean(delivery.rating) || pending.value.some((p) => answer(p.id).rating));

function addPhotos(id: string, event: Event) {
  const input = event.target as HTMLInputElement;
  const a = answer(id);
  for (const file of Array.from(input.files ?? [])) {
    if (a.photos.length >= 3) break;
    if (!file.type.startsWith("image/")) continue;
    a.photos.push(file);
    a.previews.push(URL.createObjectURL(file));
  }
  input.value = "";
}
function removePhoto(id: string, index: number) {
  const a = answer(id);
  URL.revokeObjectURL(a.previews[index]!);
  a.photos.splice(index, 1);
  a.previews.splice(index, 1);
}

async function send() {
  error.value = "";
  const missing = pending.value.find((p) => answer(p.id).rating && !answer(p.id).comment.trim());
  if (missing) {
    error.value = `Conte em poucas palavras o que achou de "${missing.name}".`;
    return;
  }
  sending.value = true;
  try {
    await reviewsApi.submit(token, {
      delivery: delivery.rating ? { rating: delivery.rating, comment: delivery.comment } : null,
      products: pending.value.filter((p) => answer(p.id).rating)
        .map((p) => ({ product: p.id, rating: answer(p.id).rating, comment: answer(p.id).comment })),
    }, Object.fromEntries(pending.value.map((p) => [p.id, answer(p.id).photos])));
    done.value = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (failure) {
    error.value = toApiError(failure).message;
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <main class="rv">
    <div class="rv__card">
      <header class="rv__head">
        <img :src="view?.logo_url || '/logo.svg'" alt="" class="rv__logo" />
        <div>
          <h1>{{ view?.store ?? "Avaliação da compra" }}</h1>
          <p v-if="view">Compra nº {{ view.sale }} · {{ date(view.date) }}</p>
        </div>
      </header>

      <p v-if="query.isPending.value" class="rv__muted">Carregando…</p>
      <div v-else-if="query.isError.value" class="rv__state">
        <i class="pi pi-link" />
        <h2>Link indisponível</h2>
        <p>{{ toApiError(query.error.value).message }}</p>
      </div>
      <div v-else-if="done" class="rv__state rv__state--ok">
        <i class="pi pi-heart-fill" />
        <h2>Obrigado, {{ view?.customer }}!</h2>
        <p>Sua avaliação foi recebida e ajuda outras pessoas a escolher. Ela aparece depois de uma conferência rápida da loja.</p>
      </div>
      <div v-else-if="view && !pending.length && (!view.delivery.available || view.delivery.done)" class="rv__state rv__state--ok">
        <i class="pi pi-check-circle" />
        <h2>Tudo avaliado</h2>
        <p>Você já avaliou esta compra. Obrigado!</p>
      </div>
      <template v-else-if="view">
        <p class="rv__hello">Oi, <b>{{ view.customer }}</b>! Conta pra gente o que achou. Leva menos de 1 minuto.</p>

        <section v-if="view.delivery.available && !view.delivery.done" class="rv__item">
          <div class="rv__item-head"><span class="rv__icon"><i class="pi pi-truck" /></span><strong>Como foi a entrega?</strong></div>
          <StarRating v-model:value="delivery.rating" editable size="lg" show-label />
          <Textarea v-if="delivery.rating" v-model="delivery.comment" rows="2" auto-resize maxlength="1500"
                    placeholder="Chegou no prazo? O entregador foi atencioso? (opcional)" fluid />
        </section>

        <section v-for="p in view.products" :key="p.id" class="rv__item" :class="{ 'rv__item--done': p.done }">
          <div class="rv__item-head">
            <img v-if="p.image" :src="p.image" alt="" class="rv__thumb" />
            <span v-else class="rv__icon"><i class="pi pi-box" /></span>
            <strong>{{ p.name }}</strong>
          </div>
          <p v-if="p.done" class="rv__done"><i class="pi pi-check" /> Avaliado</p>
          <template v-else>
            <StarRating v-model:value="answer(p.id).rating" editable size="lg" show-label />
            <template v-if="answer(p.id).rating">
              <Textarea v-model="answer(p.id).comment" rows="3" auto-resize maxlength="1500"
                        placeholder="O que você achou? Qualidade, tamanho, se é como na foto…" fluid />
              <div class="rv__photos">
                <span v-for="(src, i) in answer(p.id).previews" :key="src" class="rv__photo">
                  <img :src="src" alt="Foto escolhida" />
                  <button type="button" aria-label="Tirar foto" @click="removePhoto(p.id, i)"><i class="pi pi-times" /></button>
                </span>
                <label v-if="answer(p.id).photos.length < 3" class="rv__add">
                  <input type="file" accept="image/*" multiple @change="addPhotos(p.id, $event)" />
                  <i class="pi pi-camera" /> Foto
                </label>
              </div>
            </template>
          </template>
        </section>

        <p v-if="error" class="rv__error"><i class="pi pi-exclamation-circle" /> {{ error }}</p>
        <Button label="Enviar avaliação" icon="pi pi-send" size="large" class="rv__send" :loading="sending"
                :disabled="!canSend" @click="send" />
      </template>
    </div>
    <p class="rv__foot">Avaliação segura · Starrp</p>
  </main>
</template>

<style scoped>
.rv { min-height: 100dvh; padding: 20px 14px 32px; background: var(--surface-ground); display: flex; flex-direction: column;
      align-items: center; gap: 12px; }
.rv__card { width: 100%; max-width: 520px; display: flex; flex-direction: column; gap: 14px; padding: 20px 18px;
            border-radius: 16px; background: var(--surface-card); border: 1px solid var(--border); box-shadow: var(--shadow-sm); }
.rv__head { display: flex; gap: 12px; align-items: center; }
.rv__logo { width: 52px; height: 52px; border-radius: 12px; object-fit: contain; background: #fff; border: 1px solid var(--border); }
.rv__head h1 { margin: 0; font: 800 18px/1.2 var(--font-sans); color: var(--text-strong); }
.rv__head p { margin: 2px 0 0; font-size: 13px; color: var(--text-muted); }
.rv__hello { margin: 0; font-size: 15px; line-height: 1.5; color: var(--text-body); }
.rv__item { display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: 12px; border: 1px solid var(--border);
            background: var(--surface-card); }
.rv__item--done { opacity: 0.7; }
.rv__item-head { display: flex; gap: 10px; align-items: center; }
.rv__item-head strong { font-size: 15px; color: var(--text-strong); line-height: 1.3; }
.rv__thumb { width: 48px; height: 48px; border-radius: 10px; object-fit: cover; border: 1px solid var(--border); flex: none; }
.rv__icon { width: 40px; height: 40px; border-radius: 10px; display: grid; place-items: center; background: var(--brand-subtle);
            color: var(--text-brand); flex: none; }
.rv__done { margin: 0; color: var(--success-text); font-weight: 700; font-size: 13px; display: flex; gap: 6px; align-items: center; }
.rv__photos { display: flex; gap: 8px; flex-wrap: wrap; }
.rv__photo { position: relative; }
.rv__photo img { width: 64px; height: 64px; object-fit: cover; border-radius: 10px; border: 1px solid var(--border); }
.rv__photo button { position: absolute; top: -6px; right: -6px; width: 22px; height: 22px; border-radius: 50%; border: 0;
                    background: var(--danger); color: #fff; display: grid; place-items: center; font-size: 10px; cursor: pointer; }
.rv__add { width: 64px; height: 64px; border-radius: 10px; border: 1.5px dashed var(--border); display: flex; flex-direction: column;
           align-items: center; justify-content: center; gap: 2px; font-size: 11px; color: var(--text-muted); cursor: pointer; }
.rv__add input { display: none; }
.rv__add i { font-size: 16px; }
.rv__send { width: 100%; justify-content: center; }
.rv__error { margin: 0; color: var(--danger-text); font-size: 13.5px; font-weight: 600; display: flex; gap: 6px; }
.rv__muted { color: var(--text-muted); }
.rv__state { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px; padding: 18px 6px; }
.rv__state i { font-size: 36px; color: var(--text-muted); }
.rv__state--ok i { color: #e11d48; }
.rv__state h2 { margin: 0; font: 800 20px var(--font-sans); color: var(--text-strong); }
.rv__state p { margin: 0; font-size: 14px; line-height: 1.5; color: var(--text-body); }
.rv__foot { margin: 0; font-size: 11.5px; color: var(--text-subtle); }
</style>
