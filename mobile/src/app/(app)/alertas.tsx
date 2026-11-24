import { useRouter } from "expo-router";

import { stockAlerts } from "@/api/stock";
import { Guard } from "@/components/Guard";
import { Screen } from "@/components/Screen";
import { EmptyState, ErrorBox, ListRow, Loading, Muted } from "@/components/ui";
import { formatQty } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useSession } from "@/session/SessionContext";

export default function AlertsScreen() {
  return (
    <Guard permission="stock.view" module="stock">
      <Alerts />
    </Guard>
  );
}

function Alerts() {
  const router = useRouter();
  const { storeId } = useSession();
  const alerts = useApi(() => stockAlerts(), [storeId]);

  return (
    <Screen onRefresh={alerts.refresh} refreshing={alerts.refreshing}>
      <Muted>Produtos com saldo (somando os depósitos) menor que o estoque mínimo cadastrado.</Muted>
      {alerts.loading && <Loading />}
      {alerts.error && <ErrorBox message={alerts.error} onRetry={alerts.reload} />}
      {alerts.data?.length === 0 && <EmptyState icon="check-circle" title="Tudo acima do mínimo" />}
      {(alerts.data ?? []).map((a) => (
        <ListRow
          key={a.id}
          title={[a.product_name, a.name].filter(Boolean).join(" ")}
          subtitle={`${a.sku} · mínimo ${formatQty(a.min_stock)}`}
          right={formatQty(a.stock)}
          tone="warning"
          onPress={() => router.push({ pathname: "/produto/[id]", params: { id: a.id } })}
        />
      ))}
    </Screen>
  );
}
