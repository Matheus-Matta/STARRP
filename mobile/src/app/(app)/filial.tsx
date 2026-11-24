import { useRouter } from "expo-router";
import { useState } from "react";

import { Screen } from "@/components/Screen";
import { ListRow, Muted } from "@/components/ui";
import { notify } from "@/lib/dialog";
import { errorMessage } from "@/lib/useApi";
import { ALL_STORES, useSession } from "@/session/SessionContext";

export default function StoreScreen() {
  const router = useRouter();
  const { me, storeId, selectStore } = useSession();
  const [busy, setBusy] = useState(false);
  const stores = me?.stores ?? [];

  async function choose(id: string) {
    if (busy) return;
    setBusy(true);
    try {
      await selectStore(id);
      router.back();
    } catch (e) {
      notify("Não foi possível trocar", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Muted>Os números, saldos e lançamentos do app passam a ser desta filial.</Muted>
      {stores.length > 1 && (
        <ListRow title="Todas as filiais" subtitle="Visão consolidada (só consulta)" icon="layers"
                 right={storeId === ALL_STORES ? "✓" : undefined} onPress={() => void choose(ALL_STORES)} />
      )}
      {stores.map((s) => (
        <ListRow key={s.id} title={s.name} icon="map-pin" right={storeId === s.id ? "✓" : undefined}
                 subtitle={s.id === me?.default_store_id ? "Sua filial principal" : undefined}
                 onPress={() => void choose(s.id)} />
      ))}
      {stores.length === 0 && <Muted>Nenhuma filial liberada para o seu usuário.</Muted>}
    </Screen>
  );
}
