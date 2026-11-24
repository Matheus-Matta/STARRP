/**
 * O formato único do livro de relatórios (`services/report_book.py`) no visual da retaguarda no celular
 * (`ReportPage.vue` ≤640px + components/report): KpiTile em 2 colunas, blocos com padding 14px, ranking com
 * posição e barra, colunas no tempo, mapa de calor e a tabela (rola para o lado).
 */
import Feather from "@expo/vector-icons/Feather";
import { type ReactNode, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import type { Kpi, ReportBlock, ReportRow } from "@/api/types";
import { formatCompact, formatValue, toNumber } from "@/lib/format";
import { series as SERIES, tokens, useThemeColors } from "@/lib/tokens";

const Empty = ({ children }: { children: ReactNode }) => <Text className="font-sans text-[13px] text-muted">{children}</Text>;
const More = ({ label, onPress }: { label: string; onPress: () => void }) => (
  <Pressable onPress={onPress} className="mt-2.5 self-start py-1 active:opacity-60">
    <Text className="font-sans-semibold text-[12.5px] text-brand-text">{label}</Text>
  </Pressable>
);

/** `.kpis` (≤640px: 2 colunas, 8px) com o KpiTile: faixa na cor da série, rótulo, valor 800 e variação. */
export function KpiGrid({ kpis }: { kpis: Kpi[] }) {
  useThemeColors();
  return (
    <View className="flex-row flex-wrap gap-2">
      {kpis.map((k, i) => {
        const accent = SERIES[i % SERIES.length]!;
        const delta = k.delta === null || k.delta === undefined ? null : toNumber(k.delta);
        const better = delta === null || delta === 0 ? undefined : (delta > 0) === (k.good !== "down");
        const deltaColor = better === undefined ? tokens.muted : better ? tokens.successText : tokens.dangerText;
        return (
          <View key={`${k.label}-${i}`}
                className="min-w-0 basis-[45%] grow gap-1.5 overflow-hidden rounded-lg border border-border bg-card px-4 pb-3.5 pt-4">
            <View className="absolute bottom-0 left-0 top-0 w-[3px]" style={{ backgroundColor: accent }} />
            <Text numberOfLines={2} className="font-sans-semibold text-[12.5px] leading-[15px] text-muted">{k.label}</Text>
            <Text numberOfLines={1} adjustsFontSizeToFit className="font-sans-extrabold text-[20px] tracking-[-0.4px] tabular-nums text-strong">
              {formatValue(k.value, k.format ?? "money")}
            </Text>
            {delta !== null && (
              <View className="flex-row flex-wrap items-center gap-1">
                <Feather name={delta > 0 ? "arrow-up" : delta < 0 ? "arrow-down" : "minus"} size={10} color={deltaColor} />
                <Text className="font-sans-bold text-[12px]" style={{ color: deltaColor }}>
                  {formatValue(Math.abs(delta), "percent")}
                </Text>
                <Text className="font-sans-medium text-[12px] text-subtle">vs. período anterior</Text>
              </View>
            )}
            {k.hint ? <Text className="font-sans text-[12px] text-subtle">{k.hint}</Text> : null}
          </View>
        );
      })}
    </View>
  );
}

/** `.block` (≤640px: padding 14px): título 14,5px e descrição 12,5px. */
export function Block({ block }: { block: ReportBlock }) {
  let body: ReactNode;
  switch (block.type) {
    case "ranking":
    case "share":
    case "waterfall":
      body = <Ranking rows={(block.rows ?? []) as ReportRow[]} format={block.format} limit={block.limit ?? 10}
                      share={block.type === "share"} />;
      break;
    case "line":
    case "bars":
      body = <Columns block={block} />;
      break;
    case "heatmap":
      body = <Heatmap block={block} />;
      break;
    case "table":
      body = <Table block={block} />;
      break;
    default:
      body = <Empty>Este gráfico é exibido na retaguarda.</Empty>;
  }
  return (
    <View className="min-w-0 rounded-lg border border-border bg-card p-3.5 shadow-xs">
      <View className="mb-3.5">
        <Text className="font-sans-bold text-[14.5px] leading-[18.9px] text-strong">{block.title}</Text>
        {block.description ? <Text className="mt-0.5 font-sans text-[12.5px] text-muted">{block.description}</Text> : null}
      </View>
      {body}
    </View>
  );
}

/** RankingChart: posição, rótulo e valor; barra de 8px sobre o fundo rebaixado. */
function Ranking({ rows, format, limit, share }: { rows: ReportRow[]; format?: string; limit: number; share: boolean }) {
  useThemeColors();
  const [all, setAll] = useState(false);
  if (!rows.length) return <Empty>Sem dados no período.</Empty>;
  const shown = all ? rows : rows.slice(0, limit);
  const max = Math.max(...rows.map((r) => Math.abs(toNumber(r.value))), 1);
  const total = rows.reduce((s, r) => s + toNumber(r.value), 0);
  return (
    <View>
      <View className="gap-2.5">
        {shown.map((r, i) => {
          const value = toNumber(r.value);
          const pct = share && total ? ` · ${formatValue((value / total) * 100, "percent")}` : "";
          return (
            <View key={`${r.label}-${i}`} className="flex-row items-start gap-2.5">
              <Text className="w-5 pt-px text-right font-sans-bold text-[11.5px] tabular-nums text-subtle">{i + 1}</Text>
              <View className="min-w-0 flex-1">
                <View className="flex-row justify-between gap-3">
                  <Text numberOfLines={1} className="flex-1 font-sans text-[13px] text-body">{r.label}</Text>
                  <Text className="font-sans text-[13px] tabular-nums text-strong">{formatValue(r.value, format)}{pct}</Text>
                </View>
                <View className="mt-[5px] h-2 rounded bg-sunken">
                  <View className="h-full rounded-r"
                        style={{ width: `${Math.max((Math.abs(value) / max) * 100, 1)}%`,
                                 backgroundColor: value < 0 ? tokens.danger : SERIES[share ? i % SERIES.length : 0] }} />
                </View>
                {r.sub ? <Text className="mt-[3px] font-sans text-[11.5px] text-muted">{r.sub}</Text> : null}
              </View>
            </View>
          );
        })}
      </View>
      {rows.length > limit && <More label={all ? "Mostrar menos" : `Mostrar todos (${rows.length})`} onPress={() => setAll(!all)} />}
    </View>
  );
}

/** BarsChart/LineChart em colunas: legenda 12,5px com quadrado da série, grade e rótulos 11px. */
function Columns({ block }: { block: ReportBlock }) {
  useThemeColors();
  const labels = block.x ?? [];
  const lines = (block.series ?? []).filter((s) => Array.isArray(s.values));
  if (!labels.length || !lines.length) return <Empty>Sem dados no período.</Empty>;
  const max = Math.max(...lines.flatMap((s) => s.values.map((v) => Math.abs(toNumber(v)))), 1);
  const width = lines.length > 1 ? 10 : 16;
  return (
    <View className="gap-2">
      <View className="mb-2 flex-row flex-wrap gap-3.5">
        {lines.map((s, i) => (
          <View key={s.name} className="flex-row items-center gap-1.5">
            <View className="size-2.5 rounded-[3px]" style={{ backgroundColor: SERIES[i % SERIES.length] }} />
            <Text className="font-sans text-[12.5px] text-body">
              {s.name}: {formatValue(s.values.reduce<number>((a, v) => a + toNumber(v), 0), block.format)}
            </Text>
          </View>
        ))}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View className="h-[150px] flex-row items-end gap-1.5 border-b border-chart-grid pt-4">
          {labels.map((label, x) => (
            <View key={`${label}-${x}`} className="items-center gap-1">
              <View className="h-[110px] flex-row items-end gap-px">
                {lines.map((s, i) => (
                  <View key={s.name} className="rounded-t-[3px]"
                        style={{ width, height: Math.max((Math.abs(toNumber(s.values[x])) / max) * 110, 1),
                                 backgroundColor: SERIES[i % SERIES.length] }} />
                ))}
              </View>
              <Text className="font-sans text-[11px] tabular-nums text-muted">{label}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
      <Text className="font-sans text-[11px] text-muted">Maior valor: {formatCompact(max, block.format)}</Text>
    </View>
  );
}

/** HeatmapChart: células de 26px, raio 4px, do `--seq-low` ao `--seq-high`. */
function Heatmap({ block }: { block: ReportBlock }) {
  useThemeColors();
  const rows = (block.rows ?? []) as unknown as string[];
  const cols = (block.cols ?? []) as string[];
  const values = (block.values ?? []) as (string | number)[][];
  const max = Math.max(...values.flat().map(toNumber), 1);
  if (!cols.length) return <Empty>Sem dados no período.</Empty>;
  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View className="gap-[3px]">
          <View className="ml-[37px] flex-row gap-[3px]">
            {cols.map((c) => (
              <Text key={c} className="w-[26px] text-center font-sans text-[10.5px] tabular-nums text-muted">{c}</Text>
            ))}
          </View>
          {rows.map((r, y) => (
            <View key={r} className="flex-row items-center gap-[3px]">
              <Text className="w-[34px] font-sans text-[11.5px] text-muted">{r}</Text>
              {cols.map((c, x) => {
                const v = toNumber(values[y]?.[x]);
                return <View key={c} className="h-[26px] w-[26px] rounded"
                             style={{ backgroundColor: v ? mix(tokens.seqLow, tokens.seqHigh, v / max) : tokens.sunken }} />;
              })}
            </View>
          ))}
        </View>
      </ScrollView>
      <View className="mt-2.5 flex-row items-center gap-2">
        <Text className="font-sans text-[11.5px] text-muted">Menos</Text>
        <View className="h-2 w-[120px] flex-row overflow-hidden rounded">
          {[0, 0.25, 0.5, 0.75, 1].map((p) => <View key={p} className="flex-1" style={{ backgroundColor: mix(tokens.seqLow, tokens.seqHigh, p) }} />)}
        </View>
        <Text className="font-sans text-[11.5px] text-muted">Mais</Text>
      </View>
    </View>
  );
}

/** Mistura duas cores hex (a escala sequencial do mapa de calor). */
function mix(a: string, b: string, t: number) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((x, i) => Math.round(x + (pb[i]! - x) * t)).join(", ")})`;
}

const TABLE_PAGE = 20;

/** ReportTable: cabeçalho 11,5px em caixa alta no fundo rebaixado, células 13px; rola para o lado. */
function Table({ block }: { block: ReportBlock }) {
  useThemeColors();
  const [count, setCount] = useState(TABLE_PAGE);
  const rows = (block.rows ?? []) as Record<string, unknown>[];
  const columns = block.columns ?? [];
  if (!rows.length) return <Empty>Sem linhas no período.</Empty>;
  const numeric = (format?: string) => ["money", "int", "number", "percent", "quantity", "decimal"].includes(format ?? "");
  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator className="mx-[-14px]">
        <View>
          <View className="flex-row border-b border-border-subtle bg-sunken">
            {columns.map((c, i) => (
              <Text key={c.key} numberOfLines={1}
                    className={`${i === 0 ? "w-[180px]" : "w-[120px]"} px-3 py-2 font-sans-semibold text-[11.5px] uppercase tracking-[0.46px] text-muted ${numeric(c.format) ? "text-right" : ""}`}>
                {c.label}
              </Text>
            ))}
          </View>
          {rows.slice(0, count).map((row, r) => (
            <View key={r} className="flex-row border-b border-border-subtle">
              {columns.map((c, i) => {
                const text = formatValue(row[c.key], c.format ?? "text");
                const negative = numeric(c.format) && toNumber(row[c.key]) < 0;
                return (
                  <Text key={c.key} numberOfLines={2}
                        className={`${i === 0 ? "w-[180px] font-sans-semibold text-strong" : "w-[120px] font-sans text-body"} px-3 py-[9px] text-[13px] ${numeric(c.format) ? "text-right tabular-nums" : ""}`}
                        style={negative ? { color: tokens.dangerText } : undefined}>
                    {text}
                  </Text>
                );
              })}
            </View>
          ))}
        </View>
      </ScrollView>
      {rows.length > count && (
        <View className="mt-2 border-t border-border-subtle">
          <More label={`Mostrar mais (${rows.length - count} restantes)`} onPress={() => setCount(count + TABLE_PAGE)} />
        </View>
      )}
    </View>
  );
}
