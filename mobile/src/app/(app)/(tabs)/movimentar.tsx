import { useRouter } from "expo-router";

import { getDefaultStore } from "@/api/client";
import { DOC_KINDS, DOC_STATUS, listDocuments } from "@/api/stock";
import type { DocKind } from "@/api/types";
import { Guard } from "@/components/Guard";
import { Screen } from "@/components/Screen";
import { Button, ErrorBox, ListRow, Muted, PageHeader, SectionTitle } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useSession } from "@/session/SessionContext";
import { hrefFor } from "@/shared/frontend";

const OFFERED: DocKind[] = ["entry", "exit", "transfer", "inventory", "adjustment", "supplier_return"];

export default function MoveTab() {
  return (
    <Guard permission="stock.manage" module="stock" needsStore>
      <Move />
    </Guard>
  );
}

function Move() {
  const router = useRouter();
  const { storeId, storeName, me } = useSession();
  // Em "Todas as filiais" o lançamento vai para a filial principal do usuário.
  const target = storeId === "*" ? me?.stores.find((s) => s.id === getDefaultStore())?.name ?? storeName : storeName;
  const drafts = useApi(() => listDocuments({ status: "draft" }), [storeId]);

  return (
    <Screen onRefresh={drafts.refresh} refreshing={drafts.refreshing}>
      <PageHeader title="Movimentar estoque" icon="repeat"
                  subtitle={`Filial ${target}. O saldo só muda quando o lançamento é confirmado.`} />
      <SectionTitle>Novo lançamento</SectionTitle>
      {OFFERED.map((kind) => (
        <ListRow key={kind} icon={DOC_KINDS[kind].icon} title={DOC_KINDS[kind].label}
                 subtitle={DOC_KINDS[kind].description}
                 onPress={() => router.push({ pathname: "/documentos/novo", params: { kind } })} />
      ))}

      <SectionTitle right={<Button label="Ver todos" variant="ghost" compact onPress={() => router.push(hrefFor("/cadastros/entradas-e-saidas"))} />}>
        Rascunhos a confirmar
      </SectionTitle>
      {drafts.error && <ErrorBox message={drafts.error} onRetry={drafts.reload} />}
      {(drafts.data?.results ?? []).slice(0, 10).map((d) => (
        <ListRow key={d.id} title={`${DOC_KINDS[d.kind]?.short ?? d.kind} #${d.number}`}
                 subtitle={`${d.warehouse_name} · ${d.item_count} item(ns) · ${formatDate(d.effective_date)}`}
                 right={DOC_STATUS[d.status]?.label}
                 tone="warning"
                 onPress={() => router.push(hrefFor(`/cadastros/entradas-e-saidas/${d.id}`))} />
      ))}
      {drafts.data?.results.length === 0 && <Muted>Nenhum rascunho aberto.</Muted>}
    </Screen>
  );
}
