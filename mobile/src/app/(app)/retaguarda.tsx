/** Tela da retaguarda que não existe no celular (PDV, Configurações da conta, Integrações). */
import { Stack, useLocalSearchParams } from "expo-router";

import { Screen } from "@/components/Screen";
import { EmptyState } from "@/components/ui";
import { useSession } from "@/session/SessionContext";

export default function WebOnlyScreen() {
  const { title, path } = useLocalSearchParams<{ title?: string; path?: string }>();
  const { server } = useSession();
  const desktopPdv = path === "/pdv";
  return (
    <Screen>
      <Stack.Screen options={{ title: title ?? "Retaguarda" }} />
      <EmptyState
        icon="monitor"
        title={`${title ?? "Esta tela"} fica no computador`}
        message={desktopPdv
          ? "As vendas no balcão são feitas no PDV (aplicativo do computador), com impressora e NFC-e."
          : `Abra pela retaguarda no navegador: ${server}${path ?? ""}`}
      />
    </Screen>
  );
}
