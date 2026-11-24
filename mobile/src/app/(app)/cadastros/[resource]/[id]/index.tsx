/**
 * Registro de QUALQUER cadastro: a página de leitura da retaguarda (selos, números, seções, tabelas),
 * as ações do registro (confirmar, cancelar, baixar...), "Editar" quando pode, as consultas (movimentos,
 * vendas, extrato...) e o histórico no fim. Trabalho em segundo plano (`poll`) relê sozinho.
 */
import { findResource } from "@front/resources";
import { Stack, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import Feather from "@expo/vector-icons/Feather";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ExportButton, ExportSheet } from "@/components/Filters";
import { Guard } from "@/components/Guard";
import { FormActions } from "@/components/resource/FormActions";
import { HistoryFeed } from "@/components/resource/HistoryFeed";
import { RecordBadges, RecordView } from "@/components/resource/RecordView";
import { Screen } from "@/components/Screen";
import { RecordTabs } from "@/components/resource/RecordTabs";
import { Badge, Button, EmptyState, ErrorBox, Loading, Note } from "@/components/ui";
import { confirmAction, notify } from "@/lib/dialog";
import { tokens, useThemeColors } from "@/lib/tokens";
import { docMeta, recordExports } from "@/lib/exporters";
import { errorMessage } from "@/lib/useApi";
import { useAccess } from "@/shared/frontend";
import { accessOf, editHref, resourceApi, type Row } from "@/shared/resource";
import { useSession } from "@/session/SessionContext";
import type { ResourceDef } from "@/shared/types";
import { recordTitle } from "@/shared/values";

export default function RecordScreen() {
  const { resource: name, id } = useLocalSearchParams<{ resource: string; id: string }>();
  const resource = findResource(String(name));
  if (!resource) return <EmptyState icon="slash" title="Tela não encontrada" />;
  return (
    <Guard permission={`${resource.permission}.view`} module={resource.module}>
      <Record resource={resource} id={String(id)} />
    </Guard>
  );
}

function Record({ resource, id }: { resource: ResourceDef; id: string }) {
  useThemeColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { me, can } = useAccess();
  const { storeName } = useSession();
  const [exporting, setExporting] = useState(false);
  const access = accessOf(resource, can, me);
  const [values, setValues] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [version, setVersion] = useState(0);

  const reload = useCallback(async () => {
    try {
      setValues(await resourceApi.get(resource.endpoint, id));
      setError(null);
      setVersion((v) => v + 1);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [resource.endpoint, id]);

  // Abre e volta da edição (ou de outra tela): relê.
  useFocusEffect(useCallback(() => {
    void reload();
  }, [reload]));

  const polling = Boolean(values && resource.poll?.while(values));
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(() => void reload(), 3000);
    return () => clearInterval(timer);
  }, [polling, reload]);

  if (!values && !error) return <Loading />;
  if (!values) return <Screen><ErrorBox message={error!} onRetry={() => void reload()} /></Screen>;

  const title = recordTitle(values, resource);
  const ctx = { id, values, reload };

  async function remove() {
    try {
      await resourceApi.remove(resource.endpoint, id);
      notify("Excluído");
      router.back();
    } catch (e) {
      notify("Não foi possível excluir", errorMessage(e));
    }
  }

  const canEdit = access.canEdit(values);
  const confirmRemove = () => confirmAction("Confirmar exclusão",
                                            `Excluir este ${resource.singular}? A ação fica registrada na auditoria.`,
                                            "Excluir", () => void remove(), true);

  return (
    <View className="flex-1 bg-ground">
      <Screen onRefresh={() => {
        setRefreshing(true);
        void reload().finally(() => setRefreshing(false));
      }} refreshing={refreshing}>
        <Stack.Screen options={{ title: resource.singular[0]!.toUpperCase() + resource.singular.slice(1) }} />
        {/* `.head`: título 18px com os selos ao lado, "grupo · cadastro" embaixo e as ações numa linha que rola. */}
        <View className="gap-2.5">
          <View>
            <View className="flex-row flex-wrap items-center gap-1.5">
              <Text className="h1">{title}</Text>
              {values.is_active === false && <Badge label="Inativo" />}
              <RecordBadges resource={resource} values={values} />
            </View>
            <Text className="h1-sub">{resource.group} · {resource.title}</Text>
          </View>
          <View className="flex-row items-center gap-2">
            <ExportButton onPress={() => setExporting(true)} />
          </View>
          <FormActions actions={resource.formActions ?? []} ctx={ctx} />
        </View>
        <RecordTabs resource={resource} id={id} active="dados" />
        {polling && resource.poll ? <Note icon="loader">{resource.poll.message}</Note> : null}
        {error ? <ErrorBox message={error} /> : null}

        <RecordView resource={resource} values={values} />
        <HistoryFeed resource={resource} id={id} version={version} />
        <ExportSheet visible={exporting} onClose={() => setExporting(false)}
                     options={recordExports(resource, values, docMeta(me, storeName, recordTitle(values, resource),
                                                                      `${resource.group} · ${resource.title}`))} />
        {(canEdit || access.canDelete) && <View className="h-16" />}
      </Screen>
      {(canEdit || access.canDelete) && (
        // `.actionbar` do registro: excluir (ícone vermelho) e editar.
        <View className="absolute left-4 right-4" style={{ bottom: 12 + insets.bottom }}>
          <View className="actionbar">
            <View className="flex-row items-center gap-2 pl-1.5">
              <Feather name="check-circle" size={12} color={tokens.success} />
              <Text className="font-sans-semibold text-[12.5px] text-muted">Tudo salvo</Text>
            </View>
            <View className="flex-1 flex-row justify-end gap-[6.4px]">
              {access.canDelete && (
                <Pressable onPress={confirmRemove} accessibilityLabel="Excluir"
                           className="size-[34px] items-center justify-center rounded-[7px] active:bg-danger-subtle">
                  <Feather name="trash-2" size={15} color="#ef4444" />
                </Pressable>
              )}
              {canEdit && (
                <Button label="Editar" icon="edit-2" compact onPress={() => router.push(editHref(resource, id))} />
              )}
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
