import { Tabs } from "expo-router";

import { TopTabBar } from "@/components/TopTabBar";
import { tokens } from "@/lib/theme";
import { canSeeReports } from "@/session/access";
import { useSession } from "@/session/SessionContext";
import { useThemeColors } from "@/lib/tokens";

/**
 * Telas principais com a barra de atalhos no TOPO (`TopTabBar`): Início, Vender, Estoque, Movimentar,
 * Relatórios e "Menu" (abre o menu lateral). Cada tela tem o próprio título (h1), sem cabeçalho extra.
 */
export default function TabsLayout() {
  useThemeColors();
  const { me, canUse, allowed } = useSession();
  const stock = canUse("stockView");
  const move = canUse("stockManage");
  const reports = canSeeReports(me);

  return (
    <Tabs
      tabBar={(props) => <TopTabBar {...props} />}
      screenOptions={{
        headerShown: false,
        tabBarPosition: "top",
        sceneStyle: { backgroundColor: tokens.ground },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Início" }} />
      <Tabs.Screen name="venda" options={{ title: "PDV móvel", href: allowed("sales.manage") ? undefined : null }} />
      <Tabs.Screen name="estoque" options={{ title: "Painel de estoque", href: stock ? undefined : null }} />
      <Tabs.Screen name="movimentar" options={{ title: "Movimentar estoque", href: move ? undefined : null }} />
      <Tabs.Screen name="relatorios" options={{ title: "Relatórios", href: reports ? undefined : null }} />
    </Tabs>
  );
}
