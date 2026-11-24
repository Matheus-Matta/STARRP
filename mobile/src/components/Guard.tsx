/** Bloqueia a tela para quem não tem a permissão/módulo (o backend também nega; aqui a mensagem é clara). */
import Feather from "@expo/vector-icons/Feather";
import { useFocusEffect } from "expo-router";
import { type ReactNode, useCallback, useState } from "react";
import { Text, View } from "react-native";

import { getDefaultStore, setScopedStore } from "@/api/client";

import { EmptyState } from "@/components/ui";
import { tokens, useThemeColors } from "@/lib/tokens";
import { useSession } from "@/session/SessionContext";

export function Guard({ permission, module, children, needsStore }: {
  permission: string; module?: string; children: ReactNode; needsStore?: boolean;
}) {
  const { allowed, hasModule, storeId } = useSession();
  if (module && !hasModule(module)) {
    return (
      <View className="flex-1 bg-ground">
        <EmptyState icon="lock" title="Módulo não contratado"
                    message="Esta função depende de um módulo que não está ativo na sua conta." />
      </View>
    );
  }
  if (!allowed(permission, module)) {
    return (
      <View className="flex-1 bg-ground">
        <EmptyState icon="lock" title="Sem permissão"
                    message="O seu cargo não dá acesso a esta função. Fale com o administrador da conta." />
      </View>
    );
  }
  if (needsStore && (!storeId || storeId === "*")) {
    return <DefaultStoreScope>{children}</DefaultStoreScope>;
  }
  return <>{children}</>;
}

/**
 * Em "Todas as filiais", criar/editar não pergunta a filial: usa a filial PRINCIPAL do usuário
 * (`default_store_id`). A tela inteira (leituras e gravações) vai para ela enquanto estiver aberta.
 */
export function DefaultStoreScope({ children }: { children: ReactNode }) {
  useThemeColors();
  const { me } = useSession();
  const store = getDefaultStore();
  const [ready, setReady] = useState(false);
  // Só enquanto a tela está à vista: abas ficam montadas, e a filial não pode vazar para as outras telas.
  useFocusEffect(useCallback(() => {
    setScopedStore(store);
    setReady(true);
    return () => setScopedStore(null);
  }, [store]));
  if (!store) return <StoreRequired />;
  if (!ready) return null;
  const name = me?.stores.find((s) => s.id === store)?.name ?? "filial principal";
  return (
    <View className="flex-1">
      <View className="flex-row items-center gap-2 border-b border-border-subtle bg-info-subtle px-4 py-2">
        <Feather name="home" size={13} color={tokens.infoText} />
        <Text className="flex-1 font-sans text-[12.5px] text-info-text">
          Lançando em <Text className="font-sans-semibold">{name}</Text>, a sua filial principal.
        </Text>
      </View>
      {children}
    </View>
  );
}

export function StoreRequired() {
  return (
    <View className="flex-1 bg-ground">
      <EmptyState icon="home" title="Escolha uma filial"
                  message="O seu usuário não tem filial principal. Escolha uma filial no menu (topo da lista) para lançar." />
    </View>
  );
}
