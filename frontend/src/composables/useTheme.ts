/**
 * Tema claro / escuro / automático (segue o sistema operacional).
 *
 * Aplica no <html> as duas marcas que os estilos leem: `data-theme` (nossos
 * tokens) e a classe `.dark` (o PrimeVue). A escolha fica no navegador; no
 * automático, mudar o tema do sistema muda o app na hora.
 */
import { computed, ref, watch } from "vue";

export type ThemeMode = "light" | "dark" | "system";

/** Cores da marca (paletas de `tokens.css`). Azul é o padrão: o mais comum em ERP. */
export const BRANDS = [
  { value: "azul", label: "Azul", swatch: "#2563eb" },
  { value: "indigo", label: "Índigo", swatch: "#4f46e5" },
  { value: "violeta", label: "Violeta", swatch: "#7c3aed" },
  { value: "petroleo", label: "Verde-petróleo", swatch: "#0a7a72" },
] as const;
export type Brand = (typeof BRANDS)[number]["value"];

const KEY = "starrp.theme";
const BRAND_KEY = "starrp.brand";
// Sem `matchMedia` (navegador embutido antigo, testes), o automático vale claro.
const media = typeof window !== "undefined" && typeof window.matchMedia === "function"
  ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function stored(): ThemeMode {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function storedBrand(): Brand {
  try {
    const value = localStorage.getItem(BRAND_KEY);
    return BRANDS.some((b) => b.value === value) ? (value as Brand) : "azul";
  } catch {
    return "azul";
  }
}

const mode = ref<ThemeMode>(stored());
const brand = ref<Brand>(storedBrand());
const systemDark = ref(media?.matches ?? false);
media?.addEventListener("change", (event) => (systemDark.value = event.matches));

const resolved = computed<"light" | "dark">(() =>
  mode.value === "system" ? (systemDark.value ? "dark" : "light") : mode.value);

function apply(theme: "light" | "dark") {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.classList.toggle("dark", theme === "dark");
}

watch(resolved, apply, { immediate: typeof document !== "undefined" });
watch(brand, (value) => {
  document.documentElement.dataset.brand = value;
}, { immediate: typeof document !== "undefined" });

export function useTheme() {
  function setMode(next: ThemeMode) {
    mode.value = next;
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // navegador sem storage: vale só nesta aba
    }
  }

  /** Alterna claro ↔ escuro (o automático vira a escolha oposta à atual). */
  function toggle() {
    setMode(resolved.value === "dark" ? "light" : "dark");
  }

  function setBrand(next: Brand) {
    brand.value = next;
    try {
      localStorage.setItem(BRAND_KEY, next);
    } catch {
      // navegador sem storage: vale só nesta aba
    }
  }

  return { mode, resolved, setMode, toggle, brand, setBrand };
}
