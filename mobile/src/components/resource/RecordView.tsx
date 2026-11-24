/**
 * O registro para LER, como a retaguarda (`RecordView.vue`): selos ao lado do título, números de destaque,
 * seções com título e explicação ("rótulo: valor"), tabelas (itens, pagamentos) e o resumo lateral, que no
 * celular vem logo depois dos números. Sem `display`, as seções do formulário viram a página.
 */
import Feather from "@expo/vector-icons/Feather";
import { useRouter } from "expo-router";
import type { ReactNode } from "react";
import { Image, Pressable, ScrollView, Text, View } from "react-native";

import { mediaUrl } from "@/api/client";
import { Badge } from "@/components/ui";
import type { Tone } from "@/lib/theme";
import { tokens, useThemeColors } from "@/lib/tokens";
import { hrefFor, iconOf } from "@/shared/frontend";
import type { DisplayBadge, DisplayItem, DisplaySection, FieldDef, ResourceDef } from "@/shared/types";
import { cellText, compositeTable, fieldText, stripHtml, TABLE_TYPES, toneOf, type ViewField } from "@/shared/values";

import { ViewTable } from "./RowCard";

type Values = Record<string, unknown>;
type Line = { key: string; field: ViewField; values: Values; link?: string; hint?: string; strong?: boolean;
              tone?: string; wide: boolean };
type Block = { title: string; icon?: string; description?: string; lines: Line[]; table?: Line;
               grid?: DisplaySection["table"] };

const WIDE = ["textarea", "richtext", "tags", "multirelation", "barcodes", "images"];

export function RecordBadges({ resource, values }: { resource: ResourceDef; values: Values }) {
  const badges = (resource.display?.badges?.(values) ?? []).filter((b): b is DisplayBadge => !!b);
  if (!badges.length) return null;
  return (
    <View className="flex-row flex-wrap gap-1.5">
      {badges.map((b) => <Badge key={b.label} label={b.label} tone={(b.tone as Tone | "neutral") ?? "brand"} />)}
    </View>
  );
}

export function RecordView({ resource, values }: { resource: ResourceDef; values: Values }) {
  useThemeColors();
  const display = resource.display ?? {};
  const stats = (display.stats ?? []).filter((s) => !s.visible || s.visible(values));
  const byName = new Map(resource.fields.map((f) => [f.name, f]));

  const fromField = (field: FieldDef): Line => ({ key: field.name, field, values,
                                                  wide: Boolean(field.full) || WIDE.includes(field.type) });
  const fromItem = (item: DisplayItem, index: number): Line => {
    const name = item.key ?? `__item${index}`;
    const v = item.value ? { ...values, [name]: item.value(values) } : values;
    const options = item.map ? Object.entries(item.map).map(([value, label]) => ({ value, label })) : undefined;
    return {
      key: name, values: v, strong: item.strong, tone: item.tone?.(values), wide: item.span === "full",
      link: item.link?.(values) || undefined, hint: item.hint?.(values) ?? undefined,
      field: { name, label: item.label, type: item.type ?? "text", relation: item.relation, options, map: item.map,
               tones: item.tones },
    };
  };
  const build = (section: DisplaySection): Block => {
    const fieldLines = (section.fields ?? []).map((n) => byName.get(n)).filter((f): f is FieldDef => !!f)
      .filter((f) => !f.visible || f.visible(values)).map(fromField);
    const itemLines = (section.items ?? []).filter((i) => !i.visible || i.visible(values)).map(fromItem);
    const description = typeof section.description === "function" ? section.description(values) : section.description;
    return { title: section.title, icon: section.icon, description, lines: [...fieldLines, ...itemLines], grid: section.table };
  };

  let main: Block[];
  if (display.sections) {
    main = display.sections.filter((s) => !s.visible || s.visible(values)).map(build);
  } else {
    const hidden = new Set(display.hide ?? []);
    const groups = new Map<string, FieldDef[]>();
    for (const field of resource.fields) {
      if (hidden.has(field.name) || (field.type === "password" && !(`has_${field.name}` in values))) continue;
      if (field.visible && !field.visible(values)) continue;
      if (field.createOnly || field.type === "seo-preview") continue;
      const name = field.section ?? "Dados";
      groups.set(name, [...(groups.get(name) ?? []), field]);
    }
    main = [...groups.entries()].map(([name, fields]) => {
      const info = resource.sections?.[name];
      const only = fields.length === 1 && TABLE_TYPES.includes(fields[0]!.type);
      return { title: name, icon: info?.icon, description: info?.description,
               lines: only ? [] : fields.map(fromField), table: only ? fromField(fields[0]!) : undefined };
    });
  }
  const aside = (display.aside ?? []).filter((s) => !s.visible || s.visible(values)).map(build).filter((b) => b.lines.length);
  const isTable = (b: Block) => Boolean(b.grid || b.table);
  // Celular (`.rv-body` numa coluna): números → seções → resumo da lateral → tabelas.
  const blocks: [Block, "grid" | "list"][] = [
    ...main.filter((b) => !isTable(b)).map((b) => [b, "grid"] as [Block, "grid"]),
    ...aside.map((b) => [b, "list"] as [Block, "list"]),
    ...main.filter(isTable).map((b) => [b, "grid"] as [Block, "grid"]),
  ];

  return (
    <View className="gap-3.5">
      {stats.length > 0 && (
        // `.rv-stats`: grade auto-fit de mínimo 170px → 2 por linha no celular.
        <View className="flex-row flex-wrap gap-3">
          {stats.map((s) => {
            const value = s.value(values);
            const tone = s.tone?.(values);
            const icon = s.icon ? iconOf(s.icon) : undefined;
            return (
              <View key={s.label} className="rv-stat min-w-[140px] basis-[40%] grow">
                <View className="flex-row items-center gap-1.5">
                  {icon && <Feather name={icon} size={12} color={tokens.subtle} />}
                  <Text numberOfLines={1} className="rv-stat-label shrink">{s.label}</Text>
                </View>
                <Text numberOfLines={1} adjustsFontSizeToFit
                      className={s.type === "date" || s.type === "datetime" ? "rv-stat-value text-[17px] tabular-nums" : "rv-stat-value tabular-nums"}
                      style={tone ? { color: toneText(tone) } : undefined}>
                  {cellText({ key: s.label, label: s.label, type: s.type }, value)}
                </Text>
                {s.hint?.(values) ? <Text className="font-sans text-[12px] text-muted">{s.hint(values)}</Text> : null}
              </View>
            );
          })}
        </View>
      )}
      {blocks.map(([block, kind]) => <BlockCard key={block.title} block={block} values={values} kind={kind} />)}
    </View>
  );
}

const toneText = (tone: string) => ({
  success: tokens.successText, danger: tokens.dangerText, warning: tokens.warningText, info: tokens.infoText,
  brand: tokens.brandText, neutral: tokens.subtle,
}[tone] ?? tokens.strong);

/** `.rv-sec`: título (14px, ícone da marca) e explicação em cima, `.rv-card` embaixo. */
function Section({ block, children, flush }: { block: Block; children: ReactNode; flush?: boolean }) {
  useThemeColors();
  const icon = block.icon ? iconOf(block.icon) : undefined;
  return (
    <View className="gap-[8.8px]">
      <View className="flex-row flex-wrap items-baseline gap-x-3 px-0.5">
        <View className="flex-row items-center gap-[7px]">
          {icon && <Feather name={icon} size={13} color={tokens.brand} />}
          <Text className="fsec-title">{block.title}</Text>
        </View>
        {block.description ? <Text className="fsec-desc">{block.description}</Text> : null}
      </View>
      <View className={flush ? "rv-card" : "rv-card py-2"}>{children}</View>
    </View>
  );
}

function BlockCard({ block, values, kind }: { block: Block; values: Values; kind: "grid" | "list" }) {
  const router = useRouter();
  if (block.grid) {
    const columns = typeof block.grid.columns === "function" ? block.grid.columns(values) : block.grid.columns;
    const rows = block.grid.rows(values);
    return <Section block={block} flush><ViewTable columns={columns} rows={rows} empty={block.grid.empty} /></Section>;
  }
  if (block.table) {
    const table = compositeTable(block.table.field, values);
    return (
      <Section block={block} flush>
        {table ? <ViewTable columns={table.columns} rows={table.rows} empty="Nenhum item." /> : null}
      </Section>
    );
  }
  if (!block.lines.length) return null;
  const go = (line: Line) => (line.link ? () => router.push(hrefFor(line.link!)) : undefined);
  if (kind === "list") {
    return (
      <Section block={block} flush>
        <View className="py-1">
          {block.lines.map((line, i) => <ListLine key={line.key} line={line} first={i === 0} onLink={go(line)} />)}
        </View>
      </Section>
    );
  }
  return (
    <Section block={block}>
      {block.lines.map((line) => <GridItem key={line.key} line={line} onLink={go(line)} />)}
    </Section>
  );
}

/** Valor do item: selo para situação/sim-não, link com seta, número alinhado. */
function ItemValue({ line, onLink, right }: { line: Line; onLink?: () => void; right?: boolean }) {
  useThemeColors();
  const { field, values } = line;
  const raw = values[field.name];
  // Fotos (`ImageGallery` da retaguarda): a capa primeiro, rolando para o lado.
  if (field.type === "images") {
    const photos = (Array.isArray(raw) ? raw : []) as { url?: string; alt?: string }[];
    if (!photos.length) return <Text className="rv-dd text-subtle">Sem fotos.</Text>;
    return (
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerClassName="gap-2 pt-1">
        {photos.map((p, i) => (
          <Image key={`${p.url}-${i}`} source={{ uri: mediaUrl(p.url) ?? undefined }} accessibilityLabel={p.alt}
                 className="size-[96px] rounded-lg border border-border-subtle bg-sunken" resizeMode="cover" />
        ))}
      </ScrollView>
    );
  }
  const isTag = field.type === "tag" || (field.type === "boolean" && field.name.startsWith("is_"));
  const text = field.type === "richtext" ? stripHtml(String(raw ?? "")) || "—" : fieldText(field, values);
  if (isTag && raw !== null && raw !== undefined && raw !== "") return <Badge label={text} tone={toneOf(field, raw)} />;
  const color = onLink ? tokens.brandText : line.tone ? toneText(line.tone) : undefined;
  return (
    <View className={right ? "shrink flex-row items-center justify-end gap-[5px]" : "flex-row items-center gap-[5px]"}>
      <Text className={[
        right ? "text-right font-sans-semibold text-[13.5px] text-strong" : "rv-dd",
        line.strong && (right ? "font-sans-bold text-[15.5px]" : "rv-dd-strong"),
        onLink && "font-sans-semibold", "tabular-nums", text === "—" && "text-subtle",
      ].filter(Boolean).join(" ")} style={color ? { color } : undefined}>{text}</Text>
      {onLink && <Feather name="arrow-right" size={10} color={tokens.brandText} />}
    </View>
  );
}

/** `.rv-item`: rótulo 12px em cima, valor 14px embaixo (uma coluna até 560px). */
function GridItem({ line, onLink }: { line: Line; onLink?: () => void }) {
  return (
    <Pressable disabled={!onLink} onPress={onLink} className="rv-item active:opacity-60">
      <Text className="rv-dt">{line.field.label}</Text>
      <ItemValue line={line} onLink={onLink} />
      {line.hint ? <Text className="mt-0.5 font-sans text-[12px] text-muted">{line.hint}</Text> : null}
    </Pressable>
  );
}

/** `.rv-list__row` (resumo da lateral): rótulo à esquerda, valor à direita; o destaque com fundo rebaixado. */
function ListLine({ line, first, onLink }: { line: Line; first: boolean; onLink?: () => void }) {
  return (
    <Pressable disabled={!onLink} onPress={onLink}
               className={["flex-row justify-between gap-3 px-4 py-2 active:opacity-60", !first && "border-t border-border-subtle",
                           line.strong && "bg-sunken"].filter(Boolean).join(" ")}>
      <Text className="font-sans text-[13.5px] text-muted">{line.field.label}</Text>
      <ItemValue line={line} onLink={onLink} right />
    </Pressable>
  );
}
