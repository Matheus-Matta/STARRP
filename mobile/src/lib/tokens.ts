/**
 * Cores em JS que acompanham o tema ATIVO (claro ou escuro), para o que não aceita className: ícones, spinner,
 * placeholder, cabeçalho da navegação, gráficos. Os valores vêm de `styles/palette.ts`, GERADO do tokens.css da
 * retaguarda (`npm run front:styles`).
 *
 * `tokens.brand` lê o tema na hora; o componente que usa cores em JS chama `useThemeColors()` para redesenhar
 * quando o tema muda (o Uniwind já redesenha o que é className).
 */
import { Uniwind, useUniwind } from "uniwind";

import { darkSeries, darkTokens, lightSeries, lightTokens } from "@/styles/palette";

type Tokens = typeof lightTokens;

const isDark = () => Uniwind.currentTheme === "dark";

export const tokens: Tokens = new Proxy(lightTokens, {
  get: (_target, key: string) => (isDark() ? darkTokens : lightTokens)[key as keyof Tokens],
});

/** Paleta categórica dos gráficos (`--series-1..8`) do tema ativo. */
export const series: readonly string[] = new Proxy(lightSeries, {
  get: (_target, key) => Reflect.get(isDark() ? darkSeries : lightSeries, key),
});

/** Assina a troca de tema: o componente redesenha e `tokens` já devolve as cores novas. */
export function useThemeColors() {
  const { theme } = useUniwind();
  return { tokens, dark: theme === "dark" };
}
