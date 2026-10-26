/** Largura do contêiner (o SVG desenha em pixels de verdade: texto não distorce). */
import { onBeforeUnmount, onMounted, ref } from "vue";

export function useWidth(initial = 600) {
  const el = ref<HTMLElement>();
  const width = ref(initial);
  let observer: ResizeObserver | undefined;
  onMounted(() => {
    if (!el.value) return;
    width.value = el.value.clientWidth || initial;
    observer = new ResizeObserver(([entry]) => (width.value = Math.max(240, Math.floor(entry!.contentRect.width))));
    observer.observe(el.value);
  });
  onBeforeUnmount(() => observer?.disconnect());
  return { el, width };
}
