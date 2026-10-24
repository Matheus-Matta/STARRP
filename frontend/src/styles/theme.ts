/**
 * Tema do PrimeVue alinhado aos tokens de `tokens.css` (mesma marca e mesmas
 * superfícies), nos dois modos. O modo escuro liga com a classe `.dark` no
 * <html>, que `useTheme` mantém junto do `data-theme` dos nossos tokens.
 */
import { definePreset } from "@primeuix/themes";
import Aura from "@primeuix/themes/aura";

/** A marca vem das variáveis de `tokens.css`: trocar `data-brand` no <html> repinta o PrimeVue também. */
const brand = Object.fromEntries(
  [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((step) => [step, `var(--brand-${step})`]),
);
const slate = {
  0: "#ffffff", 50: "#f8fafc", 100: "#f1f5f9", 200: "#e2e8f0", 300: "#cbd5e1", 400: "#94a3b8", 500: "#64748b",
  600: "#475569", 700: "#334155", 800: "#1e293b", 900: "#0f172a", 950: "#020617",
};
const zinc = {
  0: "#ffffff", 50: "#fafafa", 100: "#f4f4f5", 200: "#e4e4e7", 300: "#d4d4d8", 400: "#a1a1aa", 500: "#71717a",
  600: "#52525b", 700: "#3f3f46", 800: "#27272a", 900: "#18181b", 950: "#09090b",
};

export const StarrpPreset = definePreset(Aura, {
  semantic: {
    primary: brand,
    focusRing: { width: "3px", style: "solid", color: "color-mix(in srgb, {primary.500} 40%, transparent)", offset: "1px" },
    // Compacto (estilo PrimeBlocks): campos de ~36px, cabem mais por tela.
    formField: { borderRadius: "7px", paddingX: "0.7rem", paddingY: "0.45rem", transitionDuration: "0.12s",
                 sm: { fontSize: "0.8125rem", paddingX: "0.6rem", paddingY: "0.32rem" } },
    colorScheme: {
      light: {
        surface: slate,
        primary: { color: "{primary.600}", contrastColor: "#ffffff", hoverColor: "{primary.700}", activeColor: "{primary.800}" },
        highlight: { background: "{primary.50}", focusBackground: "{primary.100}", color: "{primary.700}", focusColor: "{primary.800}" },
        formField: { hoverBorderColor: "{primary.400}", borderColor: "{surface.300}",
                     disabledBackground: "{surface.50}", disabledColor: "{surface.600}" },
      },
      dark: {
        surface: zinc,
        primary: { color: "{primary.400}", contrastColor: "var(--brand-950)", hoverColor: "{primary.300}", activeColor: "{primary.200}" },
        highlight: { background: "color-mix(in srgb, {primary.400}, transparent 84%)", focusBackground: "color-mix(in srgb, {primary.400}, transparent 76%)", color: "{primary.200}", focusColor: "{primary.100}" },
        formField: { background: "{surface.950}", hoverBorderColor: "{primary.400}", borderColor: "{surface.700}",
                     disabledBackground: "{surface.900}", disabledColor: "{surface.400}" },
      },
    },
  },
  components: {
    datatable: {
      headerCell: { padding: "0.55rem 0.9rem" },
      bodyCell: { padding: "0.6rem 0.9rem" },
      row: { stripedBackground: "{surface.50}" },
      colorScheme: {
        dark: { row: { stripedBackground: "{surface.950}" } },
      },
    },
    button: { root: { borderRadius: "7px", paddingY: "0.45rem", paddingX: "0.85rem", sm: { fontSize: "0.8125rem", paddingY: "0.3rem", paddingX: "0.65rem" } } },
    card: { root: { borderRadius: "12px" } },
    dialog: { root: { borderRadius: "14px" } },
  },
});
