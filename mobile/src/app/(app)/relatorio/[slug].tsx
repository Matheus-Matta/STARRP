/**
 * Um relatório do livro (`ReportPage.vue`): cabeçalho com o grupo, título e resumo; "Para que serve"; e no topo
 * os botões "Filtros" (gaveta pela direita: período com atalhos e datas livres + os filtros do relatório em
 * seleção com busca — produto, categoria e marca buscam no servidor) e "Exportar" (PDF, Excel, CSV, imprimir).
 * Os filtros ativos aparecem em selos logo abaixo; tocar abre a gaveta.
 */
import Feather from "@expo/vector-icons/Feather";
import { findReport } from "@front/reports/catalog";
import { Stack, useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { api } from "@/api/client";
import type { ReportBook } from "@/api/types";
import {
  DateRangeField, ExportButton, ExportSheet, FilterButton, FilterDrawer, FilterField, PRESETS, type Range, rangeLabel,
} from "@/components/Filters";
import { Guard } from "@/components/Guard";
import { Block, KpiGrid } from "@/components/ReportBlocks";
import { Screen } from "@/components/Screen";
import { OptionSelect, RelationSelect } from "@/components/resource/Pickers";
import { ErrorBox, Loading } from "@/components/ui";
import { docMeta, reportExports } from "@/lib/exporters";
import { tokens, useThemeColors } from "@/lib/tokens";
import { useApi } from "@/lib/useApi";
import { useSession } from "@/session/SessionContext";
import { iconOf } from "@/shared/frontend";

/** Filtros do livro com muitos itens: busca no servidor em vez de mandar a lista inteira. */
const REMOTE: Record<string, { endpoint: string }> = {
  product: { endpoint: "/catalog/products/" },
  category: { endpoint: "/catalog/categories/" },
  brand: { endpoint: "/catalog/brands/" },
};
const DEFAULT_RANGE = () => PRESETS.find((p) => p.key === "30")!.range();

export default function ReportScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const entry = findReport(String(slug));
  return (
    <Guard permission={entry?.permission ?? "reports.view"} module={entry?.module}>
      <Report slug={slug} />
    </Guard>
  );
}

function Report({ slug }: { slug: string }) {
  useThemeColors();
  const entry = findReport(slug);
  const { me, storeId, storeName } = useSession();
  const [about, setAbout] = useState(false);
  const [range, setRange] = useState<Range>(DEFAULT_RANGE);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [drawer, setDrawer] = useState(false);
  const [exporting, setExporting] = useState(false);
  // Rascunho da gaveta: só vale ao "Aplicar".
  const [draftRange, setDraftRange] = useState<Range>(range);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const params = { date_from: range.from ?? undefined, date_to: range.to ?? undefined, ...filters };
  const report = useApi(() => api.get<ReportBook>(`/reports/book/${slug}/`, params),
                        [slug, range.from, range.to, JSON.stringify(filters), storeId]);
  const data = report.data;
  const title = data?.title ?? entry?.title ?? "Relatório";
  const period = rangeLabel(range);
  const activeCount = Object.keys(filters).length + (rangeLabel(range) === rangeLabel(DEFAULT_RANGE()) ? 0 : 1);

  function openDrawer() {
    setDraftRange(range);
    setDraft(filters);
    setDrawer(true);
  }
  const labelOf = (name: string, value: string) =>
    data?.filters?.find((f) => f.name === name)?.options.find((o) => String(o.value) === value)?.label ?? labels[name] ?? "selecionado";

  return (
    <Screen onRefresh={report.refresh} refreshing={report.refreshing}>
      <Stack.Screen options={{ title }} />
      {/* `.report__head`: ícone 44px, grupo em caixa alta, título 22px (800) e o resumo. */}
      <View className="flex-row items-start gap-3.5">
        <View className="size-11 items-center justify-center rounded-xl bg-brand-subtle">
          <Feather name={iconOf(entry?.icon, "bar-chart-2")} size={18} color={tokens.brandText} />
        </View>
        <View className="min-w-0 flex-1">
          {entry?.group ? (
            <Text className="font-sans-bold text-[11.5px] uppercase tracking-[0.69px] text-subtle">{entry.group}</Text>
          ) : null}
          <Text className="mt-0.5 font-sans-extrabold text-[22px] leading-[26.4px] tracking-[-0.44px] text-strong">{title}</Text>
          <Text className="mt-1 font-sans text-[13.5px] text-muted">{data?.subtitle || entry?.description}</Text>
        </View>
      </View>

      {/* Ações da página: filtros (gaveta) e exportar/compartilhar. */}
      <View className="flex-row flex-wrap items-center gap-2">
        <FilterButton count={activeCount} onPress={openDrawer} />
        <ExportButton onPress={() => setExporting(true)} />
      </View>
      <Pressable onPress={openDrawer} className="flex-row flex-wrap items-center gap-1.5">
        <View className="chip pr-2.5">
          <Feather name="calendar" size={11} color={tokens.muted} />
          <Text className="chip-text">{period || "Qualquer data"}</Text>
        </View>
        <View className="chip pr-2.5">
          <Feather name="home" size={11} color={tokens.muted} />
          <Text className="chip-text">{storeName}</Text>
        </View>
        {Object.entries(filters).map(([name, value]) => (
          <View key={name} className="chip pr-2.5">
            <Feather name="filter" size={11} color={tokens.muted} />
            <Text className="chip-text">{data?.filters?.find((f) => f.name === name)?.label ?? name}: {labelOf(name, value)}</Text>
          </View>
        ))}
      </Pressable>

      {/* `.about`: para que serve, como ler e o que decidir. */}
      {entry?.about && (
        <View className="rounded-[10px] border border-brand-border bg-brand-subtle px-3.5 py-3">
          <View className="flex-row gap-2">
            <View className="mt-[3px]"><Feather name="info" size={13} color={tokens.brandText} /></View>
            <Text className="flex-1 font-sans text-[13.5px] leading-[20px] text-body">{entry.about.purpose}</Text>
          </View>
          <Pressable onPress={() => setAbout(!about)} className="ml-[22px] mt-1.5 flex-row items-center gap-1.5 self-start">
            <Text className="font-sans-semibold text-[12.5px] text-brand-text">{about ? "Menos" : "Como ler e o que decidir"}</Text>
            <Feather name={about ? "chevron-up" : "chevron-down"} size={10} color={tokens.brandText} />
          </Pressable>
          {about && (
            <View className="mt-2.5 gap-4">
              {([["Como ler", "eye", entry.about.read], ["O que decidir", "compass", entry.about.decide]] as const).map(
                ([label, icon, lines]) => lines.length > 0 && (
                  <View key={label}>
                    <View className="mb-1 flex-row items-center gap-1.5">
                      <Feather name={icon} size={12} color={tokens.strong} />
                      <Text className="font-sans-bold text-[12.5px] text-strong">{label}</Text>
                    </View>
                    {lines.map((line) => (
                      <Text key={line} className="pl-2 font-sans text-[13px] leading-[20px] text-body">•  {line}</Text>
                    ))}
                  </View>
                ),
              )}
            </View>
          )}
        </View>
      )}

      {report.loading && !data && <Loading label="Calculando..." />}
      {report.error && <ErrorBox message={report.error} onRetry={report.reload} />}
      {data && (
        <View className={report.refreshing ? "gap-3 opacity-60" : "gap-3"}>
          {data.kpis.length > 0 && <KpiGrid kpis={data.kpis} />}
          {data.blocks.map((b, i) => <Block key={`${b.title}-${i}`} block={b} />)}
        </View>
      )}

      <FilterDrawer visible={drawer} onClose={() => setDrawer(false)}
                    onClear={() => {
                      setDraftRange(DEFAULT_RANGE());
                      setDraft({});
                    }}
                    onApply={() => {
                      setRange(draftRange);
                      setFilters(draft);
                      setDrawer(false);
                    }}>
        <FilterField label="Período">
          <DateRangeField value={draftRange} onChange={setDraftRange} />
        </FilterField>
        {(data?.filters ?? []).filter((f) => f.options.length > 0 || REMOTE[f.name]).map((f) => (
          <FilterField key={f.name} label={f.label}>
            {REMOTE[f.name] ? (
              <RelationSelect title={f.label} relation={REMOTE[f.name]!} value={draft[f.name] ?? null} placeholder="Todos"
                              initialLabel={draft[f.name] ? labelOf(f.name, draft[f.name]!) : undefined}
                              onChange={(v) => setDraft(({ [f.name]: _, ...rest }) => (v ? { ...rest, [f.name]: String(v) } : rest))} />
            ) : (
              <OptionSelect title={f.label} placeholder="Todos" value={draft[f.name] ?? null}
                            options={f.options.map((o) => ({ value: String(o.value), label: o.label }))}
                            onChange={(v) => {
                              const option = f.options.find((o) => String(o.value) === String(v));
                              if (option) setLabels((l) => ({ ...l, [f.name]: option.label }));
                              setDraft(({ [f.name]: _, ...rest }) => (v ? { ...rest, [f.name]: String(v) } : rest));
                            }} />
            )}
          </FilterField>
        ))}
      </FilterDrawer>

      <ExportSheet visible={exporting} onClose={() => setExporting(false)}
                   options={reportExports(slug, params, data ?? null,
                                          docMeta(me, storeName, title, `${period || "Todo o período"} · ${storeName}`))} />
    </Screen>
  );
}
