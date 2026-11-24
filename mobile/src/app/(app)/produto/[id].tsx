import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { Image, Text, View } from "react-native";

import { mediaUrl } from "@/api/client";
import { getVariant, listBalances, listMovements } from "@/api/stock";
import { Screen } from "@/components/Screen";
import {
  Badge, IconBox, Button, Card, Divider, ErrorBox, KeyValue, ListRow, Loading, Muted, SectionTitle,
} from "@/components/ui";
import { formatDateTime, formatMoney, formatQty, toNumber } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { hrefFor } from "@/shared/frontend";
import { useSession } from "@/session/SessionContext";

export default function ProductScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { canUse, allowed, storeId } = useSession();
  const stock = canUse("stockView");
  const move = canUse("stockManage");

  const variant = useApi(() => getVariant(id), [id], allowed("catalog.view"));
  const balances = useApi(() => listBalances({ variant: id }), [id, storeId], stock);
  const moves = useApi(() => listMovements({ variant: id }), [id, storeId], stock);

  const refresh = () => {
    variant.refresh();
    balances.refresh();
    moves.refresh();
  };

  if (variant.loading && !variant.data) return <Loading />;
  const v = variant.data;
  const total = (balances.data?.results ?? []).reduce((sum, b) => sum + toNumber(b.quantity), 0);
  const name = v?.display_name ?? balances.data?.results[0]?.variant_name ?? "Produto";

  return (
    <Screen onRefresh={refresh} refreshing={variant.refreshing || balances.refreshing}>
      <Stack.Screen options={{ title: v?.sku || "Produto" }} />
      {variant.error && <ErrorBox message={variant.error} onRetry={variant.reload} />}

      <Card>
        <View className="flex-row gap-3">
          {v?.image ? (
            <Image source={{ uri: mediaUrl(v.image) ?? undefined }} className="size-[72px] rounded-lg border border-border-subtle bg-sunken" />
          ) : <IconBox name="package" size={56} bordered />}
          <View className="min-w-0 flex-1 gap-1">
            <Text className="h1">{name}</Text>
            {v?.category_name ? <Muted>{v.category_name}</Muted> : null}
            {v && !v.is_active ? <Badge label="Inativo" tone="danger" /> : null}
          </View>
        </View>
        {v && (
          <>
            <Divider />
            <KeyValue label="SKU" value={v.sku || "—"} />
            <KeyValue label="Código de barras" value={v.barcodes.map((b) => b.code).join(", ") || "—"} />
            <KeyValue label="Preço" value={formatMoney(v.price)} />
            {v.promotional_price ? <KeyValue label="Preço promocional" value={formatMoney(v.promotional_price)} /> : null}
            <KeyValue label="Unidade" value={v.sold_by_weight ? `${v.unit} (por peso)` : v.unit} />
          </>
        )}
      </Card>

      {stock && (
        <>
          <SectionTitle right={<Text className="font-sans-bold text-[14px] tabular-nums text-strong">{formatQty(total)} no total</Text>}>
            Saldo por depósito
          </SectionTitle>
          {balances.error && <ErrorBox message={balances.error} onRetry={balances.reload} />}
          {(balances.data?.results ?? []).map((b) => (
            <ListRow key={b.id} title={b.warehouse_name} right={formatQty(b.quantity)}
                     tone={toNumber(b.quantity) < 0 ? "danger" : undefined} />
          ))}
          {balances.data && balances.data.results.length === 0 && <Muted>Sem saldo nesta filial.</Muted>}
        </>
      )}

      {move && (
        <>
          <SectionTitle>Movimentar este produto</SectionTitle>
          <View className="flex-row flex-wrap gap-2">
            {([["entry", "Entrada", "arrow-down-circle"], ["exit", "Saída", "arrow-up-circle"],
               ["transfer", "Transferir", "shuffle"], ["inventory", "Contar", "clipboard"]] as const).map(
              ([kind, label, icon]) => (
                <Button key={kind} label={label} icon={icon} variant="outlined-secondary" compact className="grow"
                        onPress={() => router.push({ pathname: "/documentos/novo", params: { kind, variant: id } })} />
              ),
            )}
          </View>
        </>
      )}

      {stock && (
        <>
          <SectionTitle right={<Button label="Ver tudo" variant="ghost" compact
                                       onPress={() => router.push(hrefFor(`/cadastros/movimentacoes-de-estoque?variant=${id}`))} />}>
            Últimas movimentações
          </SectionTitle>
          {(moves.data?.results ?? []).slice(0, 8).map((m) => (
            <ListRow key={m.id} title={m.kind_label} subtitle={`${m.warehouse_name} · ${formatDateTime(m.created_at)}`}
                     right={`${toNumber(m.quantity) > 0 ? "+" : ""}${formatQty(m.quantity)}`}
                     rightSub={`saldo ${formatQty(m.balance_after)}`}
                     tone={toNumber(m.quantity) < 0 ? "danger" : "success"} />
          ))}
          {moves.data && moves.data.results.length === 0 && <Muted>Nenhuma movimentação.</Muted>}
        </>
      )}
    </Screen>
  );
}
