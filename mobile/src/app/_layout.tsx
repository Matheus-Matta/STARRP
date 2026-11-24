// 1º: liga o diagnóstico (erros e etapas da abertura no terminal do Metro) antes de tudo.
import { boot } from "@/lib/boot";
import "../global.css";

import {
  PlusJakartaSans_400Regular, PlusJakartaSans_500Medium, PlusJakartaSans_600SemiBold, PlusJakartaSans_700Bold,
  PlusJakartaSans_800ExtraBold, useFonts,
} from "@expo-google-fonts/plus-jakarta-sans";
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { Button, EmptyState, Loading } from "@/components/ui";
import { loadAppearance } from "@/lib/appearance";
import { tokens, useThemeColors } from "@/lib/tokens";
import { SessionProvider, useSession } from "@/session/SessionContext";

function RootNavigator() {
  useThemeColors();
  const { status, resume, signOut, server } = useSession();
  useEffect(() => boot(`sessão: ${status}${status === "unreachable" ? ` (${server})` : ""}`), [status, server]);

  if (status === "loading") {
    return (
      <View className="flex-1 bg-ground">
        <Loading label="Carregando..." />
      </View>
    );
  }
  if (status === "unreachable") {
    return (
      <View className="flex-1 bg-ground">
        <EmptyState
          icon="wifi-off"
          title="Sem conexão com o servidor"
          message={`Não foi possível falar com ${server}. Confira o Wi-Fi/dados e se o servidor está no ar.`}
          action={
            <View className="gap-2 self-stretch">
              <Button label="Tentar de novo" icon="refresh-cw" onPress={() => void resume()} />
              <Button label="Entrar com outro servidor" variant="text" onPress={() => void signOut()} />
            </View>
          }
        />
      </View>
    );
  }

  const signedIn = status === "signedIn";
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: tokens.ground } }}>
      <Stack.Protected guard={signedIn}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
      <Stack.Protected guard={!signedIn}>
        <Stack.Screen name="login" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  // A fonte da retaguarda; se falhar (sem rede no web, por exemplo), segue com a do sistema.
  const [fontsLoaded, fontError] = useFonts({
    PlusJakartaSans_400Regular, PlusJakartaSans_500Medium, PlusJakartaSans_600SemiBold, PlusJakartaSans_700Bold,
    PlusJakartaSans_800ExtraBold,
  });
  // Aparência escolhida no menu (claro, escuro ou a do celular), aplicada antes da primeira tela.
  const [themed, setThemed] = useState(false);
  useEffect(() => {
    boot("abrindo o app");
    void loadAppearance()
      .then((value) => boot(`tema: ${value}`))
      .catch((error: unknown) => boot(`tema falhou: ${String(error)}`))
      .finally(() => setThemed(true));
  }, []);
  useEffect(() => {
    if (fontsLoaded || fontError) boot(fontError ? `fontes falharam: ${String(fontError)}` : "fontes carregadas");
  }, [fontsLoaded, fontError]);
  const { dark } = useThemeColors();
  if ((!fontsLoaded && !fontError) || !themed) return <View className="flex-1 bg-ground" />;
  return (
    <SafeAreaProvider>
      <SessionProvider>
        <StatusBar style={dark ? "light" : "dark"} />
        <ThemeProvider value={{
          ...(dark ? DarkTheme : DefaultTheme), dark,
          colors: { ...(dark ? DarkTheme : DefaultTheme).colors, primary: tokens.brand, background: tokens.ground,
                    card: tokens.ground, text: tokens.strong, border: tokens.border, notification: tokens.danger },
        }}>
          <RootNavigator />
        </ThemeProvider>
      </SessionProvider>
    </SafeAreaProvider>
  );
}

/**
 * Erro que derruba a abertura: em vez de tela branca ou o app fechar, mostra o que aconteceu (e vai para o
 * terminal do Metro), com "Tentar de novo".
 */
export function ErrorBoundary({ error, retry }: { error: Error; retry: () => Promise<void> }) {
  useEffect(() => boot(`ERRO: ${error.message}\n${error.stack ?? ""}`), [error]);
  return (
    <View style={{ flex: 1, backgroundColor: "#f1f5f9", padding: 24, justifyContent: "center", gap: 12 }}>
      <Text style={{ fontSize: 18, fontWeight: "700", color: "#0f172a" }}>O app encontrou um erro</Text>
      <Text style={{ fontSize: 13, color: "#334155" }} selectable>{error.message}</Text>
      <Text style={{ fontSize: 11, color: "#64748b" }} numberOfLines={12} selectable>{error.stack}</Text>
      <Text onPress={() => void retry()} style={{ fontSize: 15, fontWeight: "700", color: "#2563eb", paddingVertical: 8 }}>
        Tentar de novo
      </Text>
    </View>
  );
}
