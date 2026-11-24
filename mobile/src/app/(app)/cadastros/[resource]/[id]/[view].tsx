/**
 * Consulta do registro (`ResourceDef.views`): lista de outro cadastro filtrada por este registro
 * (movimentos do produto, vendas do cliente...), como a página `/cadastros/<c>/<id>/<consulta>` da retaguarda.
 */
import { findResource } from "@front/resources";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Text, View } from "react-native";

import { Guard } from "@/components/Guard";
import { PagedList } from "@/components/PagedList";
import { RowCard } from "@/components/resource/RowCard";
import { RecordTabs } from "@/components/resource/RecordTabs";
import { Button, EmptyState, SearchBar } from "@/components/ui";
import { useApi } from "@/lib/useApi";
import { usePaged } from "@/lib/usePaged";
import { hrefFor } from "@/shared/frontend";
import { isWebOnly, resourceApi } from "@/shared/resource";
import type { DetailView, ResourceDef } from "@/shared/types";
import { recordTitle, titleKeyOf } from "@/shared/values";
import { useSession } from "@/session/SessionContext";

export default function RecordViewScreen() {
  const { resource: name, id, view } = useLocalSearchParams<{ resource: string; id: string; view: string }>();
  const resource = findResource(String(name));
  const detail = resource?.views?.find((v) => v.name === view);
  if (!resource || !detail) return <EmptyState icon="slash" title="Consulta não encontrada" />;
  if (!detail.list || isWebOnly(detail.component)) {
    return (
      <EmptyState icon="monitor" title={detail.label}
                  message="Esta consulta tem uma tela própria na retaguarda. Abra pelo computador." />
    );
  }
  return (
    <Guard permission={detail.permission ?? `${resource.permission}.view`} module={detail.module ?? resource.module}>
      <Stack.Screen options={{ title: detail.label }} />
      <ViewList resource={resource} id={String(id)} detail={detail} />
    </Guard>
  );
}

function ViewList({ resource, id, detail }: { resource: ResourceDef; id: string; detail: DetailView }) {
  const router = useRouter();
  const { storeId } = useSession();
  const list = detail.list!;
  const [search, setSearch] = useState("");
  // Os filtros dependem do registro (ex.: o produto da variante): busca o registro primeiro.
  const record = useApi(() => resourceApi.get(resource.endpoint, id), [resource.endpoint, id]);
  const params = record.data ? list.params(id, record.data) : null;
  const state = usePaged(
    (page) => resourceApi.list(list.endpoint, { page, page_size: 20, ordering: list.ordering, search, ...params }),
    [list.endpoint, search, JSON.stringify(params), storeId],
    Boolean(params),
  );
  const titleKey = titleKeyOf(list.columns);

  return (
    <View className="flex-1">
      <PagedList
        state={state}
        emptyTitle="Nada por aqui"
        header={(
          <>
            <View>
              <Text className="h1">{record.data ? recordTitle(record.data, resource) : resource.singular}</Text>
              <Text className="h1-sub">{detail.description ?? `${resource.title} · ${detail.label}`}</Text>
            </View>
            <RecordTabs resource={resource} id={id} active={detail.name} />
          </>
        )}
        toolbar={list.searchable || (list.openAll && record.data) ? (
          <>
            {list.searchable && <View className="min-w-0 flex-1"><SearchBar value={search} onChangeText={setSearch} placeholder="Buscar…" /></View>}
            {list.openAll && record.data && (
              <Button label={list.openAll.label} icon="external-link" variant="outlined-secondary" compact
                      onPress={() => router.push(hrefFor(list.openAll!.to(id, record.data!)))} />
            )}
          </>
        ) : undefined}
        renderItem={(row) => (
          <RowCard row={row} columns={list.columns} titleKey={titleKey}
                   onPress={list.rowLink ? () => router.push(hrefFor(list.rowLink!(row))) : undefined} />
        )}
      />
    </View>
  );
}
