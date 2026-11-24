/** Busca de produto em tela cheia (nome, SKU ou código) para incluir num lançamento. */
import { useState } from "react";
import { Modal, View } from "react-native";

import { searchVariants } from "@/api/stock";
import type { Variant } from "@/api/types";
import { PagedList } from "@/components/PagedList";
import { SafeAreaView } from "@/components/styled";
import { Button, ListRow, SearchBar } from "@/components/ui";
import { formatMoney, formatQty } from "@/lib/format";
import { usePaged } from "@/lib/usePaged";

export function ProductPicker({ visible, onClose, onPick }: {
  visible: boolean; onClose: () => void; onPick: (variant: Variant) => void;
}) {
  const [search, setSearch] = useState("");
  const state = usePaged((page) => searchVariants(search, page), [search, visible], visible);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView className="flex-1 bg-ground">
        <View className="flex-row items-center gap-2 px-4 pt-4">
          <View className="flex-1">
            <SearchBar value={search} onChangeText={setSearch} placeholder="Nome, SKU ou código" autoFocus />
          </View>
          <Button label="Fechar" variant="text" compact onPress={onClose} />
        </View>
        <PagedList
          state={state}
          emptyTitle={search ? "Nenhum produto encontrado" : "Digite para buscar"}
          renderItem={(v) => (
            <ListRow
              title={v.display_name}
              subtitle={[v.sku, v.category_name].filter(Boolean).join(" · ")}
              right={v.stock_quantity != null ? formatQty(v.stock_quantity) : undefined}
              rightSub={formatMoney(v.current_price ?? v.price)}
              onPress={() => {
                onPick(v);
                onClose();
              }}
            />
          )}
        />
      </SafeAreaView>
    </Modal>
  );
}
