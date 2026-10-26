<script setup lang="ts">
/**
 * Leitura de código de barras pela câmera (celular, tablet ou webcam). Fica aberta lendo em
 * sequência: cada código lido sai em `read` (o mesmo código repetido dentro de 1,2 s é a mesma
 * leitura e é ignorado). Usa o leitor nativo do navegador (BarcodeDetector) quando existe e o
 * ZXing nos outros (Safari/iOS, Firefox). A câmera só abre em HTTPS ou localhost.
 */
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{ visible: boolean; title?: string; hint?: string }>();
const emit = defineEmits<{ "update:visible": [boolean]; read: [string] }>();

const video = ref<HTMLVideoElement>();
const error = ref("");
const last = ref("");
const flash = ref(false);
let stream: MediaStream | null = null;
let stopZxing: (() => void) | null = null;
let timer = 0;
let lastAt = 0;

function found(code: string) {
  const now = Date.now();
  if (code === last.value && now - lastAt < 1200) return;
  last.value = code;
  lastAt = now;
  flash.value = true;
  window.setTimeout(() => (flash.value = false), 250);
  navigator.vibrate?.(60);
  emit("read", code);
}

async function start() {
  error.value = "";
  last.value = "";
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
  } catch (failure) {
    const name = (failure as DOMException).name;
    error.value = name === "NotAllowedError" ? "Permita o uso da câmera no navegador (ícone de cadeado na barra de endereço)."
      : name === "NotFoundError" ? "Nenhuma câmera encontrada neste aparelho."
        : "Não foi possível abrir a câmera (ela só funciona em HTTPS ou localhost).";
    return;
  }
  if (!video.value) return;
  video.value.srcObject = stream;
  await video.value.play().catch(() => undefined);
  const Detector = (window as unknown as { BarcodeDetector?: new () => { detect: (v: HTMLVideoElement) => Promise<{ rawValue: string }[]> } })
    .BarcodeDetector;
  if (Detector) {
    const detector = new Detector();
    const tick = async () => {
      if (!stream || !video.value) return;
      try {
        const codes = await detector.detect(video.value);
        if (codes[0]?.rawValue) found(codes[0].rawValue);
      } catch { /* quadro sem código */ }
      timer = window.setTimeout(tick, 180);
    };
    void tick();
    return;
  }
  const { BrowserMultiFormatReader } = await import("@zxing/browser");
  const controls = await new BrowserMultiFormatReader().decodeFromVideoElement(video.value, (result) => {
    if (result) found(result.getText());
  });
  stopZxing = () => controls.stop();
}

function stop() {
  window.clearTimeout(timer);
  stopZxing?.();
  stopZxing = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
}

watch(() => props.visible, (open) => (open ? void start() : stop()));
onBeforeUnmount(stop);
</script>

<template>
  <Dialog :visible="visible" modal :header="title ?? 'Ler pela câmera'" :style="{ width: 'min(520px, calc(100vw - 24px))' }"
          @update:visible="emit('update:visible', $event)">
    <div class="cam">
      <p v-if="error" class="cam__error"><i class="pi pi-video" /> {{ error }}</p>
      <div v-else class="cam__view" :class="{ flash }">
        <video ref="video" muted playsinline />
        <span class="cam__aim" />
      </div>
      <p class="cam__hint">{{ hint ?? "Aponte para o código de barras. Pode ler um item atrás do outro." }}</p>
      <p v-if="last" class="cam__last"><i class="pi pi-check-circle" /> Último lido: <b>{{ last }}</b></p>
    </div>
    <template #footer>
      <Button label="Fechar" severity="secondary" outlined @click="emit('update:visible', false)" />
    </template>
  </Dialog>
</template>

<style scoped>
.cam { display: flex; flex-direction: column; gap: 10px; }
.cam__view { position: relative; border-radius: 10px; overflow: hidden; background: #000; aspect-ratio: 4 / 3;
             outline: 3px solid transparent; transition: outline-color 0.15s; }
.cam__view.flash { outline-color: var(--success); }
.cam__view video { width: 100%; height: 100%; object-fit: cover; display: block; }
.cam__aim { position: absolute; left: 12%; right: 12%; top: 42%; height: 16%; border: 2px solid rgb(255 255 255 / 0.85);
            border-radius: 8px; box-shadow: 0 0 0 999px rgb(0 0 0 / 0.25); pointer-events: none; }
.cam__error { margin: 0; padding: 14px; border-radius: 10px; background: var(--danger-subtle); color: var(--danger-text);
              font-size: 13.5px; display: flex; gap: 8px; align-items: center; }
.cam__hint { margin: 0; font-size: 12.5px; color: var(--text-muted); }
.cam__last { margin: 0; font-size: 13px; color: var(--success-text); display: flex; gap: 6px; align-items: center; }
</style>
