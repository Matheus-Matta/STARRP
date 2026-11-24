/**
 * Lista paginada = a lista da retaguarda no celular: a página (`.page`, gap 10px) com cabeçalho e, no
 * `.table-card`, a barra de ferramentas e os cartões sobre o fundo `--surface-sunken`. Puxar para atualizar,
 * rolagem infinita (no lugar do paginador), vazio e erro.
 */
import type { ReactElement, ReactNode } from "react";
import { ActivityIndicator, FlatList, RefreshControl, Text, View } from "react-native";

import { EmptyState, ErrorBox, Loading } from "@/components/ui";
import { tokens } from "@/lib/tokens";
import type { usePaged } from "@/lib/usePaged";

export function PagedList<T extends { id: string }>({ state, renderItem, header, toolbar, emptyTitle, emptyMessage }: {
  state: ReturnType<typeof usePaged<T>>;
  renderItem: (item: T) => ReactElement;
  /** Acima do cartão da lista (título, avisos). */
  header?: ReactNode;
  /** Barra de ferramentas do cartão (busca, filtros, chips). */
  toolbar?: ReactNode;
  emptyTitle: string;
  emptyMessage?: string;
}) {
  return (
    <FlatList
      className="flex-1 bg-ground"
      contentContainerClassName="grow px-4 pb-[104px] pt-4"
      data={state.loading ? [] : state.items}
      keyExtractor={(item) => item.id}
      renderItem={({ item }) => <View className="border-x border-border bg-sunken px-2 pb-2">{renderItem(item)}</View>}
      keyboardShouldPersistTaps="handled"
      ListHeaderComponent={
        <View>
          {header ? <View className="mb-2.5 gap-2.5">{header}</View> : null}
          {state.error ? <View className="mb-2.5"><ErrorBox message={state.error} onRetry={state.reload} /></View> : null}
          <View className="overflow-hidden rounded-t-xl border border-border bg-card">
            {toolbar ? <View className="toolbar">{toolbar}</View> : null}
            <View className="h-2 bg-sunken" />
          </View>
        </View>
      }
      ListEmptyComponent={
        <View className="flex-1 border-x border-border bg-sunken">
          {state.loading ? <Loading /> : state.error ? null : <EmptyState title={emptyTitle} message={emptyMessage} />}
        </View>
      }
      ListFooterComponent={
        <View className="mb-2 rounded-b-xl border border-t-0 border-border bg-sunken pb-1 shadow-xs">
          {state.loadingMore ? <ActivityIndicator color={tokens.brand} className="m-4" /> : null}
          {!state.loading && state.items.length > 0 ? (
            <View className="min-h-12 items-center justify-center border-t border-border-subtle bg-card">
              <Text className="font-sans text-[12.5px] text-muted">
                {state.items.length.toLocaleString("pt-BR")} de {state.count.toLocaleString("pt-BR")}
              </Text>
            </View>
          ) : null}
        </View>
      }
      onEndReachedThreshold={0.4}
      onEndReached={() => void state.loadMore()}
      refreshControl={
        <RefreshControl refreshing={state.refreshing} onRefresh={state.refresh} colors={[tokens.brand]} tintColor={tokens.brand} />
      }
    />
  );
}
