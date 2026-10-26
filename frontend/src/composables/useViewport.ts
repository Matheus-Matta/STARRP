/**
 * Tamanho de tela reativo. `isPhone` (até 640px) troca tabelas por cartões, filtros por
 * gaveta e paginação completa por "anterior / próxima". Um só listener para o app todo.
 */
import { ref } from "vue";

const query = typeof window !== "undefined" && typeof window.matchMedia === "function"
  ? window.matchMedia("(max-width: 640px)") : null;
const isPhone = ref(query?.matches ?? false);
query?.addEventListener("change", (event) => (isPhone.value = event.matches));

export function useViewport() {
  return { isPhone };
}
