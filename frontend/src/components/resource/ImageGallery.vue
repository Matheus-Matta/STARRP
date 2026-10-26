<script setup lang="ts">
/**
 * Galeria de fotos (do produto ou de uma variante), como no StarHub:
 * arraste arquivos (ou clique) para enviar, arraste as fotos para mudar a
 * ordem — a 1ª é a CAPA (lista, PDV, loja virtual). O texto alternativo
 * descreve a foto para o Google e para leitores de tela.
 *
 * Valor: [{ image: "<id>", url: "/media/...", alt: "" }]. O envio acontece na
 * hora (a foto já fica no acervo); o vínculo com o produto é gravado no Salvar.
 */
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import ProgressBar from "primevue/progressbar";
import { computed, ref } from "vue";

import { http } from "@/api/http";
import { useNotify } from "@/composables/useNotify";

export type GalleryItem = { image: string; url: string; alt?: string; width?: number; height?: number };

const model = defineModel<GalleryItem[] | null | undefined>();
const props = defineProps<{ disabled?: boolean; compact?: boolean }>();
const notify = useNotify();
const items = computed(() => model.value ?? []);
const uploading = ref(0);
const over = ref(false);
const dragging = ref<number | null>(null);
const editing = ref<number | null>(null);
const input = ref<HTMLInputElement>();

async function send(files: FileList | File[]) {
  const list = [...files].filter((f) => f.type.startsWith("image/"));
  if (!list.length) return notify.warn("Escolha arquivos de imagem (JPG, PNG, WEBP ou GIF).");
  uploading.value += list.length;
  for (const file of list) {
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await http.post<{ id: string; url: string; alt_text: string; width: number; height: number }>(
        "/catalog/images/", form);
      if (!items.value.some((i) => i.image === data.id)) {
        model.value = [...items.value, { image: data.id, url: data.url, alt: data.alt_text, width: data.width, height: data.height }];
      }
    } catch (error) {
      notify.error(error, `Não foi possível enviar ${file.name}`);
    } finally {
      uploading.value -= 1;
    }
  }
}

function onPick(event: Event) {
  const files = (event.target as HTMLInputElement).files;
  if (files) void send(files);
  (event.target as HTMLInputElement).value = "";
}
function onDrop(event: DragEvent) {
  over.value = false;
  if (dragging.value === null && event.dataTransfer?.files.length) void send(event.dataTransfer.files);
}

function move(from: number, to: number) {
  if (to < 0 || to >= items.value.length || from === to) return;
  const next = [...items.value];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item!);
  model.value = next;
}
function remove(index: number) {
  model.value = items.value.filter((_, i) => i !== index);
}
function setAlt(index: number, alt: string) {
  model.value = items.value.map((item, i) => (i === index ? { ...item, alt } : item));
}
/** Arrastar uma foto sobre a outra troca a posição (a da frente vira capa). */
function onItemDrop(index: number) {
  if (dragging.value !== null) move(dragging.value, index);
  dragging.value = null;
}
</script>

<template>
  <div class="gallery" :class="{ 'gallery--compact': compact, 'gallery--over': over }"
       @dragover.prevent="over = dragging === null" @dragleave="over = false" @drop.prevent="onDrop">
    <figure v-for="(item, index) in items" :key="item.image" class="photo" :class="{ dragging: dragging === index }"
            :draggable="!props.disabled" @dragstart="dragging = index" @dragend="dragging = null"
            @dragover.prevent @drop.stop.prevent="onItemDrop(index)">
      <img :src="item.url" :alt="item.alt || 'Foto do produto'" loading="lazy" />
      <span v-if="index === 0" class="photo__cover"><i class="pi pi-star-fill" /> Capa</span>
      <div v-if="!props.disabled" class="photo__tools">
        <Button icon="pi pi-angle-left" text rounded size="small" aria-label="Mover para a esquerda" :disabled="index === 0"
                @click="move(index, index - 1)" />
        <Button icon="pi pi-pencil" text rounded size="small" aria-label="Texto alternativo" @click="editing = editing === index ? null : index" />
        <Button icon="pi pi-trash" text rounded size="small" severity="danger" aria-label="Tirar foto" @click="remove(index)" />
        <Button icon="pi pi-angle-right" text rounded size="small" aria-label="Mover para a direita"
                :disabled="index === items.length - 1" @click="move(index, index + 1)" />
      </div>
      <figcaption v-if="editing === index" class="photo__alt">
        <InputText :model-value="item.alt ?? ''" size="small" fluid placeholder="Ex.: camiseta azul, frente" autofocus
                   @update:model-value="setAlt(index, String($event ?? ''))" @keydown.enter.prevent="editing = null" />
      </figcaption>
    </figure>

    <button v-if="!props.disabled" type="button" class="add" @click="input?.click()">
      <i class="pi pi-images" />
      <strong>{{ items.length ? "Adicionar fotos" : "Arraste as fotos aqui" }}</strong>
      <small>ou clique · JPG, PNG, WEBP · até 8 MB</small>
      <ProgressBar v-if="uploading" mode="indeterminate" class="add__progress" />
    </button>
    <input ref="input" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple hidden @change="onPick" />
    <p v-if="props.disabled && !items.length" class="muted empty">Sem fotos.</p>
  </div>
</template>

<style scoped>
.gallery {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(min(148px, 100%), 1fr)); gap: 12px;
  padding: 2px; border-radius: 10px; transition: background-color var(--dur-fast) ease;
}
.gallery--compact { grid-template-columns: repeat(auto-fill, minmax(min(112px, 100%), 1fr)); gap: 10px; }
.gallery--over { background: var(--brand-subtle); outline: 2px dashed var(--brand); outline-offset: 2px; }
.photo {
  position: relative; margin: 0; aspect-ratio: 1; border-radius: 10px; overflow: hidden; cursor: grab;
  border: 1px solid var(--border); background: var(--surface-sunken);
  transition: transform var(--dur-fast) ease, box-shadow var(--dur-fast) ease, opacity var(--dur-fast) ease;
}
.photo:hover { box-shadow: var(--shadow-md); }
.photo.dragging { opacity: 0.4; transform: scale(0.97); }
.photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
.photo__cover {
  position: absolute; top: 8px; left: 8px; padding: 2px 8px; border-radius: 999px; font: 700 11px/1.6 var(--font-sans);
  background: var(--brand); color: #fff; display: inline-flex; gap: 4px; align-items: center;
}
.photo__cover i { font-size: 9px; }
.photo__tools {
  position: absolute; inset: auto 0 0 0; display: flex; justify-content: space-between; padding: 4px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.55)); opacity: 0; transition: opacity var(--dur-fast) ease;
}
.photo:hover .photo__tools, .photo:focus-within .photo__tools { opacity: 1; }
.photo__tools :deep(.p-button) { color: #fff; }
.photo__tools :deep(.p-button-danger) { color: #fecaca; }
.photo__alt { position: absolute; inset: auto 6px 44px 6px; }
.add {
  position: relative; aspect-ratio: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  border: 1.5px dashed var(--border-strong); border-radius: 10px; background: transparent; cursor: pointer; color: var(--text-muted);
  font-family: var(--font-sans); text-align: center; padding: 10px; overflow: hidden;
}
.add:hover { border-color: var(--brand); color: var(--text-brand); background: var(--brand-subtle); }
.add i { font-size: 22px; }
.add strong { font-size: 13px; color: var(--text-strong); }
.add small { font-size: 11px; }
.add__progress { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; }
.empty { margin: 0; font-size: 13px; }
</style>
