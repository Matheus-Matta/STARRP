/**
 * Painel financeiro (o mesmo da retaguarda, em tela de celular): saldo das contas, o que vence (a receber
 * e a pagar) e o fluxo de caixa dos últimos 30 dias. Usa a mesma API (`frontend/src/api/operations`).
 */
import { financeApi } from "@front/api/operations";
import { money } from "@front/utils/format";
import { useRouter } from "expo-router";
import { View } from "react-native";

import { Guard } from "@/components/Guard";
import { Screen } from "@/components/Screen";
import { ErrorBox, KeyValue, ListRow, Loading, PageHeader, SectionCard, SectionTitle, Stat } from "@/components/ui";
import { daysAgo, isoDate } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { hrefFor } from "@/shared/frontend";
import { useSession } from "@/session/SessionContext";

const BUCKETS = [
  { key: "overdue", label: "Vencido" },
  { key: "next_7_days", label: "Próximos 7 dias" },
  { key: "next_30_days", label: "Próximos 30 dias" },
  { key: "later", label: "Depois" },
] as const;

export default function FinanceScreen() {
  return (
    <Guard permission="finance.view" module="finance">
      <FinancePanel />
    </Guard>
  );
}

function FinancePanel() {
  const router = useRouter();
  const { storeId } = useSession();
  const balances = useApi(() => financeApi.balances(), [storeId]);
  const aging = useApi(() => financeApi.aging(), [storeId]);
  const flow = useApi(() => financeApi.cashFlow({ date_from: daysAgo(29), date_to: isoDate() }), [storeId]);
  const refresh = () => {
    balances.refresh();
    aging.refresh();
    flow.refresh();
  };

  if (balances.loading && !balances.data) return <Loading />;

  return (
    <Screen onRefresh={refresh} refreshing={balances.refreshing}>
      <PageHeader title="Painel financeiro" icon="dollar-sign" subtitle="Saldos, vencimentos e o resultado dos últimos 30 dias." />
      {balances.error && <ErrorBox message={balances.error} onRetry={balances.reload} />}
      {flow.data && (
        <View className="flex-row flex-wrap gap-2.5">
          <View className="basis-[45%] grow">
            <Stat label="Saldo nas contas" value={money(balances.data?.total)} icon="briefcase" />
          </View>
          <View className="basis-[45%] grow">
            <Stat label="Resultado 30 dias" icon="trending-up"
                  value={money(Number(flow.data.inflow) - Number(flow.data.outflow))}
                  tone={Number(flow.data.inflow) >= Number(flow.data.outflow) ? "success" : "danger"} />
          </View>
          <View className="basis-[45%] grow">
            <Stat label="Entradas 30 dias" value={money(flow.data.inflow)} icon="arrow-down-left" tone="success" />
          </View>
          <View className="basis-[45%] grow">
            <Stat label="Saídas 30 dias" value={money(flow.data.outflow)} icon="arrow-up-right" tone="danger" />
          </View>
        </View>
      )}

      {aging.data && (["receivable", "payable"] as const).map((kind) => (
        <SectionCard key={kind} title={kind === "receivable" ? "A receber" : "A pagar"}
                     icon={kind === "receivable" ? "arrow-down-left" : "arrow-up-right"}
                     bodyClassName="gap-0 py-1.5">
          {BUCKETS.map((b) => <KeyValue key={b.key} label={b.label} value={money(aging.data![kind][b.key])} />)}
        </SectionCard>
      ))}

      {balances.data && (
        <SectionCard title="Contas" icon="credit-card" description="Saldo de cada conta financeira."
                     bodyClassName="gap-0 py-1.5">
          {balances.data.accounts.map((a) => <KeyValue key={a.id} label={a.name} value={money(a.balance)} />)}
        </SectionCard>
      )}

      <SectionTitle>Atalhos</SectionTitle>
      <View className="gap-2">
        <ListRow icon="arrow-down-left" title="Contas a receber" onPress={() => router.push(hrefFor("/cadastros/contas-a-receber"))} />
        <ListRow icon="arrow-up-right" title="Contas a pagar" onPress={() => router.push(hrefFor("/cadastros/contas-a-pagar"))} />
        <ListRow icon="calendar" title="Vencimentos" onPress={() => router.push(hrefFor("/cadastros/vencimentos"))} />
        <ListRow icon="list" title="Lançamentos" onPress={() => router.push(hrefFor("/cadastros/lancamentos"))} />
      </View>
    </Screen>
  );
}
