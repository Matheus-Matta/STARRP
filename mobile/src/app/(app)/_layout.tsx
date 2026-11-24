import { buildNavigation } from "@front/components/layout/navigation";
import { Stack, usePathname } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

import { isActive, MenuButton, MenuDrawerProvider } from "@/components/MenuDrawer";
import { PrintHost } from "@/components/PrintHost";
import { headerOptions } from "@/lib/navigation";
import { tokens, useThemeColors } from "@/lib/tokens";
import { loadUsage, recordVisit } from "@/lib/usage";
import { useAccess } from "@/shared/frontend";

export default function AppLayout() {
  useThemeColors();
  return (
    <MenuDrawerProvider>
    <UsageTracker />
    <PrintHost />
    <Stack
      screenOptions={{
        ...headerOptions(),
        contentStyle: { backgroundColor: tokens.ground },
        headerBackButtonDisplayMode: "minimal",
        // A barra de cima de toda tela tem o ☰ (menu lateral); nas internas, o voltar fica à esquerda.
        headerRight: () => <View className="mr-1"><MenuButton /></View>,
      }}
    >
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="produto/[id]" options={{ title: "Produto" }} />
      <Stack.Screen name="documentos/novo" options={{ title: "Novo lançamento" }} />
      <Stack.Screen name="alertas" options={{ title: "Abaixo do mínimo" }} />
      <Stack.Screen name="relatorio/[slug]" options={{ title: "Relatório" }} />
      <Stack.Screen name="filial" options={{ title: "Filial", presentation: "modal" }} />
      <Stack.Screen name="financeiro" options={{ title: "Painel financeiro" }} />
      <Stack.Screen name="retaguarda" options={{ title: "Retaguarda" }} />
      <Stack.Screen name="cadastros/[resource]/index" options={{ title: "Cadastro" }} />
      <Stack.Screen name="cadastros/[resource]/novo" options={{ title: "Novo" }} />
      <Stack.Screen name="cadastros/[resource]/[id]/index" options={{ title: "Registro" }} />
      <Stack.Screen name="cadastros/[resource]/[id]/editar" options={{ title: "Editar" }} />
      <Stack.Screen name="cadastros/[resource]/[id]/[view]" options={{ title: "Consulta" }} />
    </Stack>
    </MenuDrawerProvider>
  );
}

/**
 * Conta as telas do menu que o usuário abre (de qualquer lugar: atalho, menu, barra do topo, link) para a tela
 * Início ordenar os atalhos pelo uso. Fica em cache no aparelho, por usuário.
 */
function UsageTracker() {
  const pathname = usePathname();
  const { me, can, hasModule } = useAccess();
  useEffect(() => {
    if (me) void loadUsage(String(me.id));
  }, [me]);
  useEffect(() => {
    if (!me || pathname === "/") return;
    const items = buildNavigation(can, hasModule).flatMap((g) => g.items).filter((i) => i.to !== "/");
    // O item mais específico que bate com a tela aberta (ex.: /cadastros/vendas/123 → Vendas).
    const hit = items.filter((i) => isActive(i.to, pathname)).sort((a, b) => b.to.length - a.to.length)[0];
    if (hit) recordVisit(hit.to);
  }, [pathname, me, can, hasModule]);
  return null;
}
