/**
 * Cores em JS para o que não aceita className (ícones, spinner, cabeçalho da navegação, gráficos).
 * A fonte da verdade é `tokens.ts`, gerado de frontend/src/styles/tokens.css (`npm run front:styles`);
 * o visual em si fica nas classes Tailwind (`src/global.css`).
 */
import { series, tokens } from "@/lib/tokens";

export type Tone = "brand" | "success" | "warning" | "danger" | "info";

/** Texto, fundo, cor cheia e borda de cada tom (`.pill--*`, ícones, avisos). */
export function toneColors(tone: Tone) {
  switch (tone) {
    case "success": return { fg: tokens.successText, solid: tokens.success, bg: tokens.successSubtle, border: "#bbf7d0" };
    case "warning": return { fg: tokens.warningText, solid: tokens.warning, bg: tokens.warningSubtle, border: "#fde68a" };
    case "danger": return { fg: tokens.dangerText, solid: tokens.danger, bg: tokens.dangerSubtle, border: "#fecaca" };
    case "info": return { fg: tokens.infoText, solid: tokens.info, bg: tokens.infoSubtle, border: tokens.brandBorder };
    default: return { fg: tokens.brandText, solid: tokens.brand, bg: tokens.brandSubtle, border: tokens.brandBorder };
  }
}

export { series, tokens };

/** Famílias da Plus Jakarta Sans por peso (para estilos fora do Tailwind, ex.: cabeçalho da navegação). */
export const fonts = {
  regular: "PlusJakartaSans_400Regular",
  medium: "PlusJakartaSans_500Medium",
  semibold: "PlusJakartaSans_600SemiBold",
  bold: "PlusJakartaSans_700Bold",
  extrabold: "PlusJakartaSans_800ExtraBold",
} as const;
