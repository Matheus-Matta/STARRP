/**
 * Lista de QUALQUER cadastro da retaguarda (`frontend/src/resources`), como ela aparece no celular:
 * busca, "Filtros" (filtros declarados + ordenação), cartões, menu "⋯" da linha (abrir, consultas,
 * ações, excluir), ações do topo da lista e o botão "Novo". Filtros vindos de link viram selos com X.
 */
import { findResource } from "@front/resources";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import Feather from "@expo/vector-icons/Feather";
import { Pressable, Text, View } from "react-native";

import { Guard } from "@/components/Guard";
import { PagedList } from "@/components/PagedList";
import { OptionSelect, RelationSelect } from "@/components/resource/Pickers";
import { RowCard } from "@/components/resource/RowCard";
import { FormActions } from "@/components/resource/FormActions";
import { DateRangeField, ExportSheet, FilterButton, FilterDrawer, FilterField } from "@/components/Filters";
import { Button, Chip, EmptyState, type MenuItem, MenuSheet, Note, SearchBar } from "@/components/ui";
import { docMeta, listExports } from "@/lib/exporters";
import { openPrint, parsePrintHref } from "@/print/bus";
import { confirmAction, notify } from "@/lib/dialog";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";
import { usePaged } from "@/lib/usePaged";
import { hrefFor, iconOf, useAccess } from "@/shared/frontend";
import {
  accessOf, createHref, editHref, newLabel, resourceApi, type Row, rowHref,
} from "@/shared/resource";
import type { FilterDef, ResourceDef } from "@/shared/types";
import { titleKeyOf } from "@/shared/values";
import { useSession } from "@/session/SessionContext";

export default function ResourceListScreen() {
  const { resource: name } = useLocalSearchParams<{ resource: string }>();
  const resource = findResource(String(name));
  if (!resource) {
    return <EmptyState icon="slash" title="Tela não encontrada" message="Este cadastro não existe nesta versão do app." />;
  }
  return (
    <Guard permission={`${resource.permission}.view`} module={resource.module}>
      <Stack.Screen options={{ title: resource.title }} />
      <ResourceList resource={resource} />
    </Guard>
  );
}

/** Nome amigável dos filtros que chegam por link. */
const FILTER_NAMES: Record<string, string> = {
  variant: "produto", product: "produto", variant__product: "produto", financial_account: "conta", warehouse: "depósito",
  customer: "cliente", supplier: "fornecedor", title__kind: "tipo", status: "situação", due_date__gte: "vence a partir de",
  due_date__lte: "vence até", expires_at__lte: "vence até", category: "categoria", sale: "venda",
};

function ResourceList({ resource }: { resource: ResourceDef }) {
  useThemeColors();
  const router = useRouter();
  const { me, can, hasModule } = useAccess();
  const { storeId } = useSession();
  const query = useLocalSearchParams<Record<string, string>>();
  const access = accessOf(resource, can, me);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, unknown>>(() => {
    const { resource: _r, ...rest } = query;
    return Object.fromEntries(Object.entries(rest).filter(([, v]) => typeof v === "string" && v));
  });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [exporting, setExporting] = useState(false);
  const { storeName } = useSession();
  function openDrawer() {
    setDraft(filters);
    setFiltersOpen(true);
  }
  const [menuRow, setMenuRow] = useState<Row | null>(null);

  const state = usePaged(
    (page) => resourceApi.list(resource.endpoint, {
      page, page_size: 20, search, ordering: resource.ordering, ...resource.params, ...filters,
    }),
    [resource.endpoint, search, filters, storeId],
  );

  // Trabalho em segundo plano numa linha (`poll`): relê sozinho até terminar.
  const polling = state.items.some((row) => resource.poll?.while(row));
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(() => void state.refresh(), 3000);
    return () => clearInterval(timer);
  }, [polling]); // eslint-disable-line react-hooks/exhaustive-deps

  const declared = useMemo(() => new Set((resource.filters ?? []).flatMap((f) =>
    f.type === "daterange" ? [`${f.name}__gte`, `${f.name}__lte`] : [f.name])), [resource.filters]);
  const has = (v: unknown) => v !== null && v !== undefined && v !== "";
  const activeCount = [...declared].filter((k) => has(filters[k])).length;
  const hidden = Object.entries(filters).filter(([k, v]) => !declared.has(k) && has(v));
  const titleKey = titleKeyOf(resource.columns);
  const listCtx = { id: "", values: {}, reload: async () => { await state.refresh(); } };

  function menuFor(row: Row): MenuItem[][] {
    const id = String(row.id);
    const open: MenuItem[] = [{ label: "Abrir", icon: "external-link", onPress: () => router.push(rowHref(resource, row)) }];
    if (access.canEdit(row)) open.push({ label: "Editar", icon: "edit-2", onPress: () => router.push(editHref(resource, id)) });
    const views = (resource.views ?? []).filter((v) => can(v.permission) && hasModule(v.module)).map((v) => ({
      label: v.label, icon: iconOf(v.icon, "list"),
      onPress: () => router.push({ pathname: "/cadastros/[resource]/[id]/[view]", params: { resource: resource.name, id, view: v.name } }),
    }));
    const extra = (resource.rowActions ?? []).filter((a) => can(a.permission) && (!a.visible || a.visible(row))).map((a) => ({
      label: a.label, icon: iconOf(a.icon, "play"), danger: a.danger, onPress: () => runRowAction(a, row),
    }));
    const remove: MenuItem[] = access.canDelete ? [{
      label: "Excluir", icon: "trash-2", danger: true,
      onPress: () => confirmAction("Confirmar exclusão", `Excluir este ${resource.singular}? A ação fica registrada na auditoria.`,
                                   "Excluir", () => void removeRow(id), true),
    }] : [];
    return [open, views, extra, remove];
  }

  function runRowAction(action: NonNullable<ResourceDef["rowActions"]>[number], row: Row) {
    if (action.to) {
      const to = action.to(row);
      const printing = parsePrintHref(to);
      if (printing) return openPrint(printing.doc, printing.id, printing.query);
      return router.push(hrefFor(to));
    }
    const go = async () => {
      try {
        await action.run?.(row);
        if (action.success) notify(action.success);
        void state.refresh();
      } catch (e) {
        notify(`Não foi possível: ${action.label.toLowerCase()}`, errorMessage(e));
      }
    };
    if (action.confirm) confirmAction(action.label, action.confirm, action.label, () => void go(), action.danger);
    else void go();
  }

  async function removeRow(id: string) {
    try {
      await resourceApi.remove(resource.endpoint, id);
      notify("Excluído");
      void state.refresh();
    } catch (e) {
      notify("Não foi possível excluir", errorMessage(e));
    }
  }

  const listActions = (resource.listActions ?? []);
  const filtering = activeCount > 0 || hidden.length > 0 || !!search;
  // Cabeçalho da lista (`.head`): título 18px, "N registros", ações da lista e "Novo".
  const header = (
    <>
      <View className="flex-row items-center gap-4">
        <View className="min-w-0 flex-1">
          <Text className="h1">{resource.title}</Text>
          <Text className="h1-sub min-h-[17.6px]">
            {state.loading ? "" : `${state.count.toLocaleString("pt-BR")} ${state.count === 1 ? "registro" : "registros"}`}
          </Text>
        </View>
        {access.canCreate && (
          <Button label={newLabel(resource)} icon="plus" compact onPress={() => router.push(createHref(resource))} />
        )}
      </View>
      {resource.systemNote && resource.systemData ? <Note icon="lock">{resource.systemNote}</Note> : null}
      {listActions.length > 0 && <FormActions actions={listActions} ctx={listCtx} />}
    </>
  );
  // Barra de ferramentas (`.toolbar` ≤640px): busca, "Filtros" (abre os filtros na própria barra), filtros de link e "Limpar".
  const toolbar = (
    <>
      {resource.searchable !== false && (
        <View className="min-w-0 flex-1">
          <SearchBar value={search} onChangeText={setSearch} placeholder="Buscar…" />
        </View>
      )}
      {(resource.filters ?? []).length > 0 && <FilterButton count={activeCount} onPress={openDrawer} />}
      <Pressable onPress={() => setExporting(true)} accessibilityLabel="Exportar ou compartilhar"
                 className="size-[34px] items-center justify-center rounded-[7px] border border-outline-border active:bg-outline-active">
        <Feather name="share-2" size={15} color={tokens.outlineFg} />
      </Pressable>
      {hidden.map(([key]) => (
        <View key={key} className="chip">
          <Feather name="filter" size={11} color={tokens.muted} />
          <Text className="chip-text">Filtrado: {FILTER_NAMES[key] ?? key.replace(/__/g, " ").replace(/_/g, " ")}</Text>
          <Pressable accessibilityLabel="Tirar filtro" onPress={() => setFilters((f) => ({ ...f, [key]: null }))}
                     className="size-[22px] items-center justify-center rounded-full active:bg-hover">
            <Feather name="x" size={12} color={tokens.muted} />
          </Pressable>
        </View>
      ))}
      {filtering && (
        <Button label="Limpar" icon="x-circle" variant="text" compact onPress={() => {
          setSearch("");
          setFilters(Object.fromEntries(Object.keys(filters).map((k) => [k, null])));
        }} />
      )}
    </>
  );

  return (
    <View className="flex-1">
      <PagedList
        state={state}
        header={header}
        toolbar={toolbar}
        emptyTitle={filtering ? "Nada encontrado com esses filtros" : `Nenhum ${resource.singular} ainda`}
        emptyMessage={filtering ? "Tente outra busca ou limpe os filtros." : "Os registros aparecem aqui assim que forem criados."}
        renderItem={(row) => (
          <RowCard row={row} columns={resource.columns} titleKey={titleKey}
                   onPress={() => router.push(rowHref(resource, row))} onMenu={() => setMenuRow(row)} />
        )}
      />
      <MenuSheet visible={!!menuRow} onClose={() => setMenuRow(null)} title={menuRow ? titleOf(menuRow) : undefined}
                 groups={menuRow ? menuFor(menuRow) : []} />
      {/* Filtros na gaveta da direita: só valem ao "Aplicar". */}
      <FilterDrawer visible={filtersOpen} onClose={() => setFiltersOpen(false)}
                    onClear={() => setDraft(Object.fromEntries(Object.keys(draft).map((k) => [k, null])))}
                    onApply={() => {
                      setFilters(draft);
                      setFiltersOpen(false);
                    }}>
        {(resource.filters ?? []).map((f) => (
          <FilterField key={f.name} label={f.label}>
            <FilterControl filter={f} values={draft} set={(k, v) => setDraft((cur) => ({ ...cur, [k]: v }))} />
          </FilterField>
        ))}
      </FilterDrawer>
      <ExportSheet visible={exporting} onClose={() => setExporting(false)}
                   options={listExports(resource, { search, ordering: resource.ordering, ...resource.params, ...filters } as never,
                                        activeCount ? "filtrada" : "",
                                        docMeta(me, storeName, resource.title,
                                                `${state.count.toLocaleString("pt-BR")} registro(s)${activeCount || search ? " · com filtros" : ""} · ${storeName}`))} />
    </View>
  );

  function titleOf(row: Row) {
    const col = resource.columns.find((c) => c.key === titleKey);
    return col ? String(row[col.key] ?? "") : resource.singular;
  }
}

function FilterControl({ filter, values, set }: {
  filter: FilterDef; values: Record<string, unknown>; set: (k: string, v: unknown) => void;
}) {
  switch (filter.type) {
    case "boolean": {
      const v = values[filter.name];
      return (
        <View className="flex-row flex-wrap items-center gap-1.5">
          <Chip label="Todos" active={v === null || v === undefined || v === ""} onPress={() => set(filter.name, null)} />
          <Chip label="Sim" active={String(v) === "true"} onPress={() => set(filter.name, "true")} />
          <Chip label="Não" active={String(v) === "false"} onPress={() => set(filter.name, "false")} />
        </View>
      );
    }
    case "relation":
      return filter.relation ? (
        <RelationSelect title={filter.label} relation={filter.relation} value={values[filter.name]} placeholder="Todos"
                        onChange={(v) => set(filter.name, v)} />
      ) : null;
    case "daterange":
      return (
        <DateRangeField allowEmpty
                        value={{ from: (values[`${filter.name}__gte`] as string) || null, to: (values[`${filter.name}__lte`] as string) || null }}
                        onChange={(r) => {
                          set(`${filter.name}__gte`, r.from);
                          set(`${filter.name}__lte`, r.to);
                        }} />
      );
    default:
      return (
        <OptionSelect title={filter.label} options={filter.options ?? []} value={values[filter.name]} placeholder="Todos"
                      onChange={(v) => set(filter.name, v)} />
      );
  }
}
