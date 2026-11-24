import { useRouter } from "expo-router";
import { useState } from "react";
import { ScrollView, View } from "react-native";

import { listBalances, listWarehouses } from "@/api/stock";
import { Guard } from "@/components/Guard";
import { PagedList } from "@/components/PagedList";
import { useProductScan } from "@/components/ProductScan";
import { OptionSelect } from "@/components/resource/Pickers";
import { RowCard } from "@/components/resource/RowCard";
import { Button, PageHeader, SearchBar } from "@/components/ui";
import { useApi } from "@/lib/useApi";
import { usePaged } from "@/lib/usePaged";
import { useSession } from "@/session/SessionContext";
import { hrefFor } from "@/shared/frontend";

/** As colunas do saldo na retaguarda (cadastro "saldos"), no cartão do celular. */
const BALANCE_COLUMNS = [
  { key: "variant_name", label: "Produto", title: true }, { key: "sku", label: "SKU" },
  { key: "warehouse_name", label: "Depósito" }, { key: "qty", label: "Saldo", type: "quantity" as const },
];

export default function StockTab() {
  return (
    <Guard permission="stock.view" module="stock">
      <StockBalances />
    </Guard>
  );
}

function StockBalances() {
  const router = useRouter();
  const { storeId, storeName } = useSession();
  const [search, setSearch] = useState("");
  const [warehouse, setWarehouse] = useState<string | undefined>();
  const scan = useProductScan();
  const warehouses = useApi(() => listWarehouses(), [storeId]);
  const state = usePaged((page) => listBalances({ search, warehouse, page }), [search, warehouse, storeId]);

  return (
    <View className="flex-1">
      {scan.scanner}
      <PagedList
        state={state}
        emptyTitle={search ? "Nada encontrado" : "Sem saldos"}
        emptyMessage={search ? "Tente outro nome, SKU ou leia o código." : "Nenhum produto com saldo nesta filial."}
        header={
          // `StockOverviewPage`: "Painel de estoque", filial e os atalhos (secundário com contorno).
          <>
            <PageHeader title="Painel de estoque" icon="archive" subtitle={storeName} />
            <ScrollView horizontal showsHorizontalScrollIndicator={false} className="mx-[-16px] grow-0" contentContainerClassName="gap-[6.4px] px-4">
              <Button label="Kardex" icon="list" variant="outlined-secondary" compact
                      onPress={() => router.push(hrefFor("/cadastros/movimentacoes-de-estoque"))} />
              <Button label="Abaixo do mínimo" icon="alert-triangle" variant="outlined-secondary" compact
                      onPress={() => router.push("/alertas")} />
            </ScrollView>
          </>
        }
        toolbar={
          <>
            <View className="min-w-0 flex-1">
              <SearchBar value={search} onChangeText={setSearch} placeholder="Produto ou SKU" onScan={scan.open} />
            </View>
            <View className="w-full">
              <OptionSelect title="Depósito" placeholder="Todos os depósitos" value={warehouse ?? null}
                            options={(warehouses.data ?? []).map((w) => ({ value: w.id, label: w.name }))}
                            onChange={(v) => setWarehouse(v ? String(v) : undefined)} />
            </View>
          </>
        }
        renderItem={(b) => (
          <RowCard row={{ ...b, qty: b.quantity }} titleKey="variant_name" columns={BALANCE_COLUMNS}
                   onPress={() => router.push({ pathname: "/produto/[id]", params: { id: b.variant } })} />
        )}
      />
    </View>
  );
}
