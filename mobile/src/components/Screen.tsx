/** Página (`.page` no celular: padding 1rem e 1rem entre blocos) com "puxar para atualizar". */
import type { ReactNode } from "react";
import { RefreshControl, ScrollView, View } from "react-native";

import { tokens, useThemeColors } from "@/lib/tokens";

export function Screen({ children, onRefresh, refreshing = false, scroll = true }: {
  children: ReactNode; onRefresh?: () => void; refreshing?: boolean; scroll?: boolean;
}) {
  useThemeColors();
  if (!scroll) return <View className="page flex-1 bg-ground">{children}</View>;
  return (
    <ScrollView
      className="flex-1 bg-ground"
      contentContainerClassName="page pb-12"
      contentInsetAdjustmentBehavior="automatic"
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} colors={[tokens.brand]} tintColor={tokens.brand} />
          : undefined
      }
    >
      {children}
    </ScrollView>
  );
}
