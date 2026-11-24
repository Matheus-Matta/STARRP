/**
 * Cabeçalho das telas = a barra superior da retaguarda no celular (`AppTopbar.vue`, ≤640px): 52px, fundo
 * `--surface-ground`, borda embaixo e só a página atual, em 14px semibold forte.
 */
import { fonts, tokens } from "@/lib/theme";

export function headerOptions() {
  return {
    headerStyle: { backgroundColor: tokens.ground },
    headerShadowVisible: true,
    headerTintColor: tokens.muted,
    headerTitleStyle: { fontFamily: fonts.semibold, fontSize: 14, color: tokens.strong },
    headerTitleAlign: "left" as const,
  };
}
