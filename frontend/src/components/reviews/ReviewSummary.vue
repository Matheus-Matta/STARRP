<script setup lang="ts">
/** Painel da avaliação no registro: estrelas grandes, comentário, fotos e quem moderou. */
import { computed } from "vue";

import type { FormActionContext } from "@/resources/types";
import { dateTime } from "@/utils/format";

import StarRating from "./StarRating.vue";

const props = defineProps<{ ctx: FormActionContext }>();
const v = computed(() => props.ctx.values as Record<string, unknown>);
const photos = computed(() => (v.value.photo_urls ?? []) as string[]);
</script>

<template>
  <section class="review">
    <div class="review__head">
      <StarRating :value="Number(v.rating)" size="lg" show-label />
      <div class="review__who">
        <strong>{{ v.public_name }}</strong>
        <small>{{ dateTime(v.created_at) }} · {{ v.kind === "delivery" ? `Entrega da venda ${v.sale_number ?? "—"}` : v.product_name }}</small>
        <span v-if="v.verified_purchase" class="pill pill--success"><i class="pi pi-verified" /> Compra verificada</span>
      </div>
    </div>
    <blockquote v-if="v.comment" class="review__comment">“{{ v.comment }}”</blockquote>
    <p v-else class="review__empty">Sem comentário, só a nota.</p>
    <div v-if="photos.length" class="review__photos">
      <a v-for="url in photos" :key="url" :href="url" target="_blank" rel="noopener"><img :src="url" alt="Foto enviada pelo cliente" /></a>
    </div>
    <p v-if="v.status === 'rejected'" class="review__mod review__mod--bad">
      <i class="pi pi-times-circle" /> Rejeitada por {{ v.moderated_by_name ?? "—" }} em {{ dateTime(v.moderated_at) }}: {{ v.rejection_reason }}
    </p>
    <p v-else-if="v.status === 'approved'" class="review__mod">
      <i class="pi pi-check-circle" /> Aprovada por {{ v.moderated_by_name ?? "—" }} em {{ dateTime(v.moderated_at) }}
    </p>
    <p v-else class="review__mod review__mod--wait"><i class="pi pi-clock" /> Aguardando moderação: aprove ou rejeite acima.</p>
  </section>
</template>

<style scoped>
.review { display: flex; flex-direction: column; gap: 12px; padding: 18px 20px; border: 1px solid var(--border); border-radius: 12px;
          background: var(--surface-card); }
.review__head { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
.review__who { display: flex; flex-direction: column; gap: 3px; }
.review__who strong { font-size: 15px; color: var(--text-strong); }
.review__who small { font-size: 12.5px; color: var(--text-muted); }
.review__who .pill { align-self: flex-start; }
.review__comment { margin: 0; padding: 10px 14px; border-left: 3px solid #f5a524; background: var(--surface-sunken);
                   border-radius: 0 8px 8px 0; font-size: 14.5px; line-height: 1.55; color: var(--text-body); white-space: pre-wrap; }
.review__empty { margin: 0; color: var(--text-muted); font-size: 13px; }
.review__photos { display: flex; gap: 8px; flex-wrap: wrap; }
.review__photos img { width: 96px; height: 96px; object-fit: cover; border-radius: 10px; border: 1px solid var(--border); }
.review__mod { margin: 0; display: flex; gap: 6px; align-items: center; font-size: 13px; color: var(--success-text); }
.review__mod--bad { color: var(--danger-text); }
.review__mod--wait { color: var(--warning-text); }
</style>
