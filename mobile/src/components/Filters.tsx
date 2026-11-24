/**
 * Peças de filtro e exportação, iguais em relatórios, listas e registros:
 *  - `FilterButton` + `FilterDrawer`: o botão "Filtros (n)" da página abre uma gaveta que entra pela DIREITA,
 *    com os filtros e "Limpar" / "Aplicar" no rodapé (nada pesa a página);
 *  - `DateRangeField`: período com atalhos (hoje, 7 dias, este mês...) e datas livres (de / até);
 *  - `ExportButton` + `ExportSheet`: PDF (no estilo da impressão da retaguarda), Excel e CSV, que abrem a folha de
 *    compartilhar do celular (WhatsApp, e-mail, Drive...), e Imprimir.
 */
import Feather from "@expo/vector-icons/Feather";
import { type ReactNode, useEffect, useState } from "react";
import { Animated, Easing, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AnimatedView } from "@/components/styled";
import { Button, Chip, Field, type IconName, Sheet } from "@/components/ui";
import { notify } from "@/lib/dialog";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";

/* ── Gaveta de filtros ─────────────────────────────────────────────────── */

export function FilterButton({ count, onPress }: { count: number; onPress: () => void }) {
  return (
    <Button label={count ? `Filtros (${count})` : "Filtros"} icon="sliders" compact
            variant={count ? "outlined" : "outlined-secondary"} onPress={onPress} />
  );
}

/** Gaveta que entra pela direita (como o menu lateral, do outro lado), com rodapé Limpar / Aplicar. */
export function FilterDrawer({ visible, onClose, onApply, onClear, title = "Filtros", children }: {
  visible: boolean; onClose: () => void; onApply: () => void; onClear: () => void; title?: string; children: ReactNode;
}) {
  useThemeColors();
  const insets = useSafeAreaInsets();
  const [progress] = useState(() => new Animated.Value(0));
  const [shown, setShown] = useState(false);
  const width = 340;

  useEffect(() => {
    if (visible) {
      setShown(true); // eslint-disable-line react-hooks/set-state-in-effect
      Animated.timing(progress, { toValue: 1, duration: 260, easing: Easing.bezier(0.22, 1, 0.36, 1), useNativeDriver: true })
        .start();
    } else {
      Animated.timing(progress, { toValue: 0, duration: 180, useNativeDriver: true }).start(() => setShown(false));
    }
  }, [visible, progress]);

  return (
    <Modal visible={shown} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <AnimatedView className="absolute bottom-0 left-0 right-0 top-0 bg-overlay" style={{ opacity: progress }}>
        <Pressable className="flex-1" onPress={onClose} accessibilityLabel="Fechar filtros" />
      </AnimatedView>
      <AnimatedView className="absolute bottom-0 right-0 top-0 max-w-[88%] border-l border-border bg-card shadow-lg"
                     style={{ width, paddingTop: insets.top, paddingBottom: insets.bottom,
                              transform: [{ translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [width, 0] }) }] }}>
        <View className="dialog-header">
          <Feather name="sliders" size={15} color={tokens.brand} />
          <Text className="dialog-title flex-1">{title}</Text>
          <Pressable onPress={onClose} hitSlop={10} accessibilityLabel="Fechar"
                     className="size-9 items-center justify-center rounded-full active:bg-hover">
            <Feather name="x" size={18} color={tokens.muted} />
          </Pressable>
        </View>
        <ScrollView className="flex-1" contentContainerClassName="gap-4 p-4" keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
        <View className="dialog-footer">
          <Button label="Limpar" icon="x-circle" variant="outlined-secondary" className="flex-1" onPress={onClear} />
          <Button label="Aplicar" icon="check" className="flex-1" onPress={onApply} />
        </View>
      </AnimatedView>
    </Modal>
  );
}

/** Rótulo + controle dentro da gaveta (`.field`). */
export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <View className="field">
      <Text className="field-label">{label}</Text>
      {children}
    </View>
  );
}

/* ── Período ───────────────────────────────────────────────────────────── */

export type Range = { from: string | null; to: string | null };

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const shift = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return iso(d);
};

/** Atalhos de período (os mesmos do seletor da retaguarda). */
export const PRESETS: { key: string; label: string; range: () => Range }[] = [
  { key: "today", label: "Hoje", range: () => ({ from: iso(new Date()), to: iso(new Date()) }) },
  { key: "yesterday", label: "Ontem", range: () => ({ from: shift(-1), to: shift(-1) }) },
  { key: "7", label: "7 dias", range: () => ({ from: shift(-6), to: iso(new Date()) }) },
  { key: "30", label: "30 dias", range: () => ({ from: shift(-29), to: iso(new Date()) }) },
  { key: "month", label: "Este mês", range: () => {
    const d = new Date();
    return { from: iso(new Date(d.getFullYear(), d.getMonth(), 1)), to: iso(d) };
  } },
  { key: "last-month", label: "Mês passado", range: () => {
    const d = new Date();
    return { from: iso(new Date(d.getFullYear(), d.getMonth() - 1, 1)), to: iso(new Date(d.getFullYear(), d.getMonth(), 0)) };
  } },
  { key: "90", label: "90 dias", range: () => ({ from: shift(-89), to: iso(new Date()) }) },
  { key: "year", label: "Este ano", range: () => ({ from: `${new Date().getFullYear()}-01-01`, to: iso(new Date()) }) },
  { key: "12m", label: "12 meses", range: () => ({ from: shift(-364), to: iso(new Date()) }) },
];

const toBr = (value: string | null) => (value ? value.split("-").reverse().join("/") : "");
function fromBr(text: string): string | null | undefined {
  const d = text.replace(/\D/g, "");
  if (!d) return null;
  if (d.length < 8) return undefined;
  return `${d.slice(4, 8)}-${d.slice(2, 4)}-${d.slice(0, 2)}`;
}
const maskBr = (text: string) => {
  const d = text.replace(/\D/g, "").slice(0, 8);
  return [d.slice(0, 2), d.slice(2, 4), d.slice(4, 8)].filter(Boolean).join("/");
};

/** Texto do período: o nome do atalho ou "01/11/2026 – 22/11/2026". */
export function rangeLabel(range: Range) {
  const preset = PRESETS.find((p) => {
    const r = p.range();
    return r.from === range.from && r.to === range.to;
  });
  if (preset) return preset.label;
  if (!range.from && !range.to) return "";
  return `${toBr(range.from) || "…"} – ${toBr(range.to) || "…"}`;
}

/** Campo de período: atalhos em chips e as datas livres (de / até), como o DateRangePicker da retaguarda. */
export function DateRangeField({ value, onChange, allowEmpty }: {
  value: Range; onChange: (range: Range) => void; allowEmpty?: boolean;
}) {
  useThemeColors();
  const [from, setFrom] = useState(toBr(value.from));
  const [to, setTo] = useState(toBr(value.to));
  const [last, setLast] = useState(value);
  if (value.from !== last.from || value.to !== last.to) {
    setLast(value);
    setFrom(toBr(value.from));
    setTo(toBr(value.to));
  }
  const active = PRESETS.find((p) => {
    const r = p.range();
    return r.from === value.from && r.to === value.to;
  })?.key;

  return (
    <View className="gap-2.5">
      <View className="flex-row flex-wrap gap-1.5">
        {allowEmpty && <Chip label="Qualquer data" active={!value.from && !value.to} onPress={() => onChange({ from: null, to: null })} />}
        {PRESETS.map((p) => <Chip key={p.key} label={p.label} active={active === p.key} onPress={() => onChange(p.range())} />)}
      </View>
      <View className="flex-row items-end gap-2">
        <View className="flex-1">
          <Field label="De" value={from} placeholder="dd/mm/aaaa" keyboardType="number-pad" onChangeText={(t) => {
            const m = maskBr(t);
            setFrom(m);
            const next = fromBr(m);
            if (next !== undefined) onChange({ ...value, from: next });
          }} />
        </View>
        <View className="flex-1">
          <Field label="Até" value={to} placeholder="dd/mm/aaaa" keyboardType="number-pad" onChangeText={(t) => {
            const m = maskBr(t);
            setTo(m);
            const next = fromBr(m);
            if (next !== undefined) onChange({ ...value, to: next });
          }} />
        </View>
      </View>
    </View>
  );
}

/* ── Exportar / compartilhar ───────────────────────────────────────────── */

export type ExportOption = { key: string; label: string; hint: string; icon: IconName; run: () => Promise<void> };

export function ExportButton({ onPress }: { onPress: () => void }) {
  return <Button label="Exportar" icon="share-2" compact variant="outlined-secondary" onPress={onPress} />;
}

/** "Exportar ou compartilhar": cada opção gera o arquivo e abre a folha de compartilhar do celular. */
export function ExportSheet({ visible, onClose, options, title = "Exportar ou compartilhar" }: {
  visible: boolean; onClose: () => void; options: ExportOption[]; title?: string;
}) {
  useThemeColors();
  const [running, setRunning] = useState<string | null>(null);
  async function run(option: ExportOption) {
    setRunning(option.key);
    try {
      await option.run();
      onClose();
    } catch (e) {
      notify(`Não foi possível: ${option.label.toLowerCase()}`, errorMessage(e));
    } finally {
      setRunning(null);
    }
  }
  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      {options.map((o) => (
        <Pressable key={o.key} disabled={!!running} onPress={() => void run(o)}
                   className="m-card flex-row items-center gap-3 active:bg-hover">
          <View className="size-10 items-center justify-center rounded-[10px] bg-brand-subtle">
            <Feather name={o.icon} size={17} color={tokens.brand} />
          </View>
          <View className="min-w-0 flex-1">
            <Text className="font-sans-bold text-[14px] text-strong">{running === o.key ? "Gerando…" : o.label}</Text>
            <Text className="font-sans text-[12px] text-muted">{o.hint}</Text>
          </View>
          <Feather name="chevron-right" size={16} color={tokens.subtle} />
        </Pressable>
      ))}
    </Sheet>
  );
}
