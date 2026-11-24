/**
 * Cartão da linha = `frontend/src/components/list/MobileCards.vue`: foto e título (15px, 700) no topo com o "⋯",
 * etiquetas (situação, ativo...) logo abaixo e as demais colunas em grade de 2 (rótulo 11px em caixa alta,
 * valor 13,5px). Toque abre; segurar ou "⋯" abre o menu da linha.
 */
import Feather from "@expo/vector-icons/Feather";
import { Image, Pressable, Text, View } from "react-native";

import { mediaUrl } from "@/api/client";
import { Badge, Muted } from "@/components/ui";
import { tokens, useThemeColors } from "@/lib/tokens";
import type { ColumnDef } from "@/shared/types";
import { cellText, isEmpty, isNumericColumn, toneOf } from "@/shared/values";

type Row = Record<string, unknown>;

export function RowCard({ row, columns, titleKey, onPress, onMenu, maxFields = 6 }: {
  row: Row; columns: ColumnDef[]; titleKey?: string; onPress?: () => void; onMenu?: () => void; maxFields?: number;
}) {
  useThemeColors();
  const shown = columns.filter((c) => c.mobile !== false);
  const image = shown.find((c) => c.type === "image");
  const chips = shown.filter((c) => (c.type === "tag" || c.type === "boolean") && c.key !== titleKey);
  const fields = shown.filter((c) => c.key !== titleKey && c.type !== "image" && c.type !== "tag" && c.type !== "boolean")
    .slice(0, maxFields);
  const titleColumn = shown.find((c) => c.key === titleKey) ?? columns.find((c) => c.key === titleKey);
  const imageUrl = image ? mediaUrl(row[image.key]) : null;
  const shownChips = chips.filter((c) => !isEmpty(row[c.key]));

  return (
    <Pressable disabled={!onPress} onPress={onPress} onLongPress={onMenu} className="m-card active:bg-hover">
      <View className="min-w-0 flex-row items-center gap-2.5">
        {image ? (
          // `.thumb` da CellValue: 38px, raio 8px, fundo rebaixado.
          <View className="size-[38px] items-center justify-center overflow-hidden rounded-md border border-border-subtle bg-sunken">
            {imageUrl ? <Image source={{ uri: imageUrl }} className="size-full" />
              : <Feather name="image" size={14} color={tokens.subtle} />}
          </View>
        ) : null}
        <Text numberOfLines={1} className="m-card-title min-w-0 flex-1">
          {titleColumn ? cellText(titleColumn, row[titleColumn.key]) : String(row.id ?? "")}
        </Text>
        {onMenu && (
          <Pressable onPress={onMenu} hitSlop={6} accessibilityLabel="Ações" className="m-card-menu active:bg-active">
            <Feather name="more-vertical" size={16} color={tokens.muted} />
          </Pressable>
        )}
      </View>
      {shownChips.length > 0 && (
        <View className="mt-2 flex-row flex-wrap gap-1.5">
          {shownChips.map((c) => <Badge key={c.key} label={cellText(c, row[c.key])} tone={toneOf(c, row[c.key])} />)}
        </View>
      )}
      {fields.length > 0 && (
        <View className="mt-2.5 flex-row flex-wrap gap-x-3 gap-y-1.5">
          {fields.map((c) => {
            const empty = isEmpty(row[c.key]);
            return (
              <View key={c.key} className="min-w-0 basis-[45%] grow">
                <Text numberOfLines={1} className="m-card-dt">{c.label}</Text>
                <Text numberOfLines={1}
                      className={empty ? "m-card-dd text-subtle"
                        : isNumericColumn(c.type) ? "m-card-dd font-sans-semibold text-strong tabular-nums" : "m-card-dd"}>
                  {cellText(c, row[c.key])}
                </Text>
              </View>
            );
          })}
        </View>
      )}
    </Pressable>
  );
}

/** Tabela dentro do registro (itens, pagamentos...): os mesmos cartões, sobre o fundo rebaixado. */
export function ViewTable({ columns, rows, empty, onRowPress }: {
  columns: ColumnDef[]; rows: Row[]; empty?: string; onRowPress?: (row: Row) => void;
}) {
  const titleKey = (columns.find((c) => c.title) ?? columns.find((c) => c.key === "name") ?? columns[0])?.key;
  if (!rows.length) return <Muted className="px-4 py-3">{empty ?? "Nada por aqui."}</Muted>;
  return (
    <View className="m-cards">
      {rows.map((row, i) => (
        <RowCard key={String(row.id ?? i)} row={row} columns={columns} titleKey={titleKey} maxFields={8}
                 onPress={onRowPress ? () => onRowPress(row) : undefined} />
      ))}
    </View>
  );
}
