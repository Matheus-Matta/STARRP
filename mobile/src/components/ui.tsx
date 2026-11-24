/**
 * Peças de interface do app = os componentes da retaguarda no celular, em Tailwind (classes de `src/global.css`,
 * que reproduzem base.css, primevue.css e o <style> de cada componente com os valores de `max-width: 640px`).
 * Ajustes de toque: alvos ≥ 40px, `active:` no lugar de `:hover`, campos com 16px.
 */
import Feather from "@expo/vector-icons/Feather";
import { type ComponentProps, type ReactNode, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, TextInput, type TextInputProps,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { tokens, useThemeColors } from "@/lib/tokens";
import { type Tone, toneColors } from "@/lib/theme";

export type IconName = ComponentProps<typeof Feather>["name"];
type ToneOrNeutral = Tone | "neutral";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

export function Icon({ name, size = 20, color }: { name: IconName; size?: number; color?: string }) {
  useThemeColors();
  return <Feather name={name} size={size} color={color ?? tokens.strong} />;
}

/** Texto com a fonte do app; o estilo vem por className (`font-sans-bold text-[15px] text-strong`). */
export function Txt({ children, className, numberOfLines }: {
  children: ReactNode; className?: string; numberOfLines?: number;
}) {
  return <Text numberOfLines={numberOfLines} className={cx("font-sans text-[13.5px] text-body", className)}>{children}</Text>;
}

/** Quadrado com ícone no tom (cabeçalho, seção, indicador). */
export function IconBox({ name, tone = "brand", size = 36, bordered }: {
  name: IconName; tone?: ToneOrNeutral; size?: number; bordered?: boolean;
}) {
  useThemeColors();
  const c = tone === "neutral" ? { fg: tokens.muted, bg: tokens.sunken, border: tokens.border } : toneColors(tone);
  return (
    <View className="items-center justify-center"
          style={{ width: size, height: size, borderRadius: size >= 36 ? 9 : Math.round(size * 0.28), backgroundColor: c.bg,
                   borderWidth: bordered ? 1 : 0, borderColor: c.border }}>
      <Feather name={name} size={Math.round(size * 0.42)} color={c.fg} />
    </View>
  );
}

/** `.card` (no app o padding é 14px, o de SectionCard no celular, para caber mais por tela). */
export function Card({ children, className, onPress }: { children: ReactNode; className?: string; onPress?: () => void }) {
  const base = cx("card gap-2 p-3.5", className);
  if (!onPress) return <View className={base}>{children}</View>;
  return <Pressable onPress={onPress} className={cx(base, "active:bg-hover active:border-brand-border")}>{children}</Pressable>;
}

/** PageHeader: ícone 36px em quadrado azul-claro, título 18px (celular) e descrição 12,5px. */
export function PageHeader({ title, subtitle, icon, right }: {
  title: string; subtitle?: string; icon?: IconName; right?: ReactNode;
}) {
  useThemeColors();
  return (
    <View className="flex-row items-center gap-3.5">
      {icon && (
        <View className="page-header-icon">
          <Feather name={icon} size={15} color={tokens.brand} />
        </View>
      )}
      <View className="min-w-0 flex-1">
        <Text className="h1">{title}</Text>
        {subtitle ? <Text className="h1-sub">{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

/** SectionCard: cabeçalho com ícone e divisória, corpo 14px. */
export function SectionCard({ title, description, icon, right, children, bodyClassName }: {
  title: string; description?: string; icon?: IconName; right?: ReactNode; children: ReactNode; bodyClassName?: string;
}) {
  useThemeColors();
  return (
    <View className="section">
      <View className="section-head">
        {icon && (
          <View className="section-icon">
            <Feather name={icon} size={15} color={tokens.brand} />
          </View>
        )}
        <View className="min-w-0 flex-1">
          <Text className="section-title">{title}</Text>
          {description ? <Text className="mt-0.5 font-sans text-[12.5px] text-muted">{description}</Text> : null}
        </View>
        {right}
      </View>
      <View className={cx("section-body gap-2", bodyClassName)}>{children}</View>
    </View>
  );
}

/** Seção do formulário/registro: título com ícone e explicação em cima, cartão embaixo (`.fsec`, `.rv-sec`). */
export function FormSection({ title, description, icon, children, cardClassName, first }: {
  title: string; description?: string; icon?: IconName; children: ReactNode; cardClassName?: string; first?: boolean;
}) {
  useThemeColors();
  return (
    <View className={cx("fsec", first && "pt-1")}>
      <View className="flex-row flex-wrap items-baseline gap-x-3 px-0.5">
        <View className="flex-row items-center gap-[7px]">
          {icon && <Feather name={icon} size={13} color={tokens.brand} />}
          <Text className="fsec-title">{title}</Text>
        </View>
        {description ? <Text className="fsec-desc">{description}</Text> : null}
      </View>
      <View className={cx("fsec-card", cardClassName)}>{children}</View>
    </View>
  );
}

export function Title({ children }: { children: ReactNode }) {
  return <Text className="h1">{children}</Text>;
}

/** Rótulo de grupo: caixa alta discreta (cabeçalho de grupo do menu e das tabelas). */
export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <View className="mt-2 min-h-6 flex-row items-center justify-between">
      <Text className="font-sans-bold text-[10.5px] uppercase tracking-[0.735px] text-muted">{children}</Text>
      {right}
    </View>
  );
}

export function Muted({ children, className, numberOfLines }: {
  children: ReactNode; className?: string; numberOfLines?: number;
}) {
  return <Text numberOfLines={numberOfLines} className={cx("font-sans text-[13px] text-muted", className)}>{children}</Text>;
}

export function Body({ children, className, numberOfLines }: {
  children: ReactNode; className?: string; numberOfLines?: number;
}) {
  return <Text numberOfLines={numberOfLines} className={cx("font-sans text-[13.5px] text-body", className)}>{children}</Text>;
}

type ButtonProps = {
  label: string;
  onPress: () => void;
  variant?: keyof typeof BUTTON;
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  className?: string;
  compact?: boolean;
};

/**
 * Botão do PrimeVue (Aura + StarrpPreset): primário azul, secundário cinza, perigo vermelho, texto e contorno.
 * `fg` é função: a cor do texto/ícone segue o tema ativo (claro ou escuro).
 */
const BUTTON = {
  primary: { box: "bg-brand border-brand active:bg-brand-hover active:border-brand-hover", fg: () => tokens.onBrand },
  secondary: { box: "bg-secondary-bg border-secondary-bg active:bg-secondary-bg-active active:border-secondary-bg-active",
               fg: () => tokens.secondaryFg },
  danger: { box: "bg-[#ef4444] border-[#ef4444] active:bg-[#dc2626] active:border-[#dc2626]", fg: () => "#ffffff" },
  ghost: { box: "bg-transparent border-transparent active:bg-brand-subtle", fg: () => tokens.brand },
  outlined: { box: "bg-transparent border-brand-border active:bg-brand-subtle", fg: () => tokens.brand },
  "outlined-secondary": { box: "bg-transparent border-outline-border active:bg-outline-active", fg: () => tokens.outlineFg },
  "outlined-danger": { box: "bg-transparent border-danger active:bg-danger-subtle", fg: () => tokens.danger },
  text: { box: "bg-transparent border-transparent active:bg-outline-active", fg: () => tokens.outlineFg },
  success: { box: "bg-[#22c55e] border-[#22c55e] active:bg-[#16a34a] active:border-[#16a34a]", fg: () => "#ffffff" },
  contrast: { box: "bg-contrast-bg border-contrast-bg active:bg-contrast-active active:border-contrast-active",
              fg: () => tokens.contrastFg },
} as const;

export function Button({ label, onPress, variant = "primary", icon, loading, disabled, className, compact }: ButtonProps) {
  useThemeColors();
  const p = { box: BUTTON[variant].box, fg: BUTTON[variant].fg() };
  const off = disabled || loading;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} disabled={off}
               className={cx("btn", compact && "btn-sm", p.box, off && "opacity-60", className)}>
      {loading ? <ActivityIndicator color={p.fg} /> : (
        <>
          {icon && <Feather name={icon} size={compact ? 14 : 16} color={p.fg} />}
          <Text numberOfLines={1} className={cx("btn-text", compact && "btn-sm-text")} style={{ color: p.fg }}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

/** Foco do campo: borda primary.400 e anel de 3px (primevue.css). */
function useFocusRing() {
  const [focused, setFocused] = useState(false);
  return { focused, onFocus: () => setFocused(true), onBlur: () => setFocused(false) };
}

/** `.field`: rótulo 12,5px forte, campo e erro/dica embaixo. */
export function FieldShell({ label, required, error, hint, children }: {
  label?: string; required?: boolean; error?: string; hint?: string; children: ReactNode;
}) {
  useThemeColors();
  return (
    <View className="field">
      {label ? (
        <Text className="field-label">
          {label}{required ? <Text className="text-danger"> *</Text> : null}
        </Text>
      ) : null}
      {children}
      {error ? (
        <View className="flex-row items-center gap-1">
          <Feather name="alert-circle" size={12} color={tokens.dangerText} />
          <Text className="field-error flex-1">{error}</Text>
        </View>
      ) : null}
      {!error && hint ? <Text className="field-hint">{hint}</Text> : null}
    </View>
  );
}

export function Field({ label, error, hint, required, onFocus, onBlur, editable, multiline, className, ...props }: TextInputProps & {
  label?: string; error?: string; hint?: string; required?: boolean;
}) {
  useThemeColors();
  const ring = useFocusRing();
  return (
    <FieldShell label={label} required={required} error={error} hint={hint}>
      <TextInput
        placeholderTextColor={tokens.subtle}
        selectionColor={tokens.brand}
        editable={editable}
        multiline={multiline}
        {...props}
        onFocus={(e) => { ring.onFocus(); onFocus?.(e); }}
        onBlur={(e) => { ring.onBlur(); onBlur?.(e); }}
        className={cx("input input-text", ring.focused && "input-focus", error && "input-invalid",
                      editable === false && "input-disabled", multiline && "min-h-[84px] align-top", className)}
      />
    </FieldShell>
  );
}

/** Busca da barra de ferramentas da lista (campo com lupa; leitor de código ao lado quando houver). */
export function SearchBar({ value, onChangeText, placeholder, onScan, autoFocus, onSubmit }: {
  value: string; onChangeText: (text: string) => void; placeholder?: string; onScan?: () => void;
  autoFocus?: boolean; onSubmit?: () => void;
}) {
  useThemeColors();
  const ring = useFocusRing();
  return (
    <View className={cx("input gap-2 py-0 pr-1", ring.focused && "input-focus")}>
      <Feather name="search" size={15} color={tokens.subtle} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder ?? "Buscar"}
        placeholderTextColor={tokens.subtle}
        selectionColor={tokens.brand}
        autoFocus={autoFocus}
        autoCorrect={false}
        autoCapitalize="none"
        returnKeyType="search"
        onSubmitEditing={onSubmit}
        onFocus={ring.onFocus}
        onBlur={ring.onBlur}
        className="input-text min-h-[38px] flex-1 py-1.5"
      />
      {value ? (
        <Pressable hitSlop={10} onPress={() => onChangeText("")} accessibilityLabel="Limpar" className="p-1">
          <Feather name="x" size={16} color={tokens.subtle} />
        </Pressable>
      ) : null}
      {onScan && (
        <Pressable hitSlop={8} onPress={onScan} accessibilityLabel="Ler código de barras"
                   className="size-8 items-center justify-center rounded-[7px] active:bg-brand-subtle">
          <Feather name="maximize" size={17} color={tokens.brand} />
        </Pressable>
      )}
    </View>
  );
}

/** Linha de lista em cartão (`.m-card` com ícone): atalhos, alertas, escolhas. */
export function ListRow({ title, subtitle, right, rightSub, icon, iconTone = "brand", onPress, tone }: {
  title: string; subtitle?: string; right?: string; rightSub?: string; icon?: IconName;
  iconTone?: ToneOrNeutral; onPress?: () => void; tone?: "danger" | "success" | "warning";
}) {
  useThemeColors();
  return (
    <Pressable disabled={!onPress} onPress={onPress}
               className="m-card min-h-[60px] flex-row items-center gap-3 py-3 active:bg-hover">
      {icon && <IconBox name={icon} tone={iconTone} />}
      <View className="min-w-0 flex-1 gap-0.5">
        <Text numberOfLines={2} className="m-card-title">{title}</Text>
        {subtitle ? <Muted numberOfLines={2}>{subtitle}</Muted> : null}
      </View>
      {(right || rightSub) && (
        <View className="max-w-[45%] items-end gap-0.5">
          {right ? (
            <Text numberOfLines={1} className="font-sans-bold text-[15px] tabular-nums"
                  style={{ color: tone ? toneColors(tone).fg : tokens.strong }}>{right}</Text>
          ) : null}
          {rightSub ? <Muted numberOfLines={1} className="text-[12px]">{rightSub}</Muted> : null}
        </View>
      )}
      {onPress && <Feather name="chevron-right" size={16} color={tokens.subtle} />}
    </Pressable>
  );
}

/** `.pill`: selo com ponto na cor do texto. */
export function Badge({ label, tone = "neutral" }: { label: string; tone?: ToneOrNeutral }) {
  useThemeColors();
  const c = tone === "neutral" ? { fg: tokens.muted, bg: tokens.hover } : toneColors(tone);
  return (
    <View className="pill" style={{ backgroundColor: c.bg }}>
      <View className="size-1.5 rounded-full" style={{ backgroundColor: c.fg }} />
      <Text className="pill-text" style={{ color: c.fg }}>{label}</Text>
    </View>
  );
}

/** Opção marcável (SelectButton/ToggleButton do PrimeVue em forma de chip). */
export function Chip({ label, active, onPress }: { label: string; active?: boolean; onPress: () => void }) {
  useThemeColors();
  return (
    <Pressable onPress={onPress}
               className={cx("min-h-9 flex-row items-center gap-1.5 rounded-[7px] border px-3",
                             active ? "border-brand-border bg-brand-subtle" : "border-field-border bg-field-bg active:bg-hover")}>
      {active && <Feather name="check" size={13} color={tokens.brandText} />}
      <Text className={cx("text-[13.5px]", active ? "font-sans-semibold text-brand-text" : "font-sans text-body")}>{label}</Text>
    </Pressable>
  );
}

export function Loading({ label }: { label?: string }) {
  useThemeColors();
  return (
    <View className="flex-1 items-center justify-center gap-2 p-6">
      <ActivityIndicator color={tokens.brand} size="large" />
      {label ? <Muted>{label}</Muted> : null}
    </View>
  );
}

/** EmptyState: ícone em quadrado tracejado, título 15px, texto 13px. */
export function EmptyState({ icon = "inbox", title, message, action }: {
  icon?: IconName; title: string; message?: string; action?: ReactNode;
}) {
  useThemeColors();
  return (
    <View className="flex-1 items-center justify-center gap-2 px-4 py-10">
      <View className="empty-icon">
        <Feather name={icon} size={22} color={tokens.subtle} />
      </View>
      <Text className="text-center font-sans-bold text-[15px] text-strong">{title}</Text>
      {message ? <Text className="max-w-[360px] text-center font-sans text-[13px] text-muted">{message}</Text> : null}
      {action}
    </View>
  );
}

/** Aviso de erro (Message "error" do PrimeVue). */
export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  useThemeColors();
  return (
    <View className="flex-row items-center gap-2 rounded-md border border-danger-subtle bg-danger-subtle px-3 py-2.5">
      <Feather name="alert-circle" size={16} color={tokens.dangerText} />
      <Text className="flex-1 font-sans-medium text-[13.5px] text-danger-text">{message}</Text>
      {onRetry && (
        <Pressable onPress={onRetry} hitSlop={8}>
          <Text className="font-sans-bold text-[13px] text-danger-text">Tentar de novo</Text>
        </Pressable>
      )}
    </View>
  );
}

/** Aviso informativo (`.system-note`, `.list-progress`). */
export function Note({ children, icon = "info", tone = "info" }: { children: ReactNode; icon?: IconName; tone?: Tone }) {
  useThemeColors();
  const c = toneColors(tone);
  return (
    <View className="flex-row items-center gap-2 rounded-md px-3 py-2" style={{ backgroundColor: c.bg }}>
      <Feather name={icon} size={14} color={c.fg} />
      <Text className="flex-1 font-sans text-[13px]" style={{ color: c.fg }}>{children}</Text>
    </View>
  );
}

/** StatCard: rótulo 12,5px, ícone 30px no tom e valor 800. */
export function Stat({ label, value, hint, tone, icon }: {
  label: string; value: string; hint?: string; tone?: "success" | "danger" | "warning" | "info"; icon?: IconName;
}) {
  useThemeColors();
  const c = toneColors(tone ?? "brand");
  return (
    <View className="stat min-w-[140px] flex-1">
      <View className="flex-row items-center justify-between gap-2">
        <Text numberOfLines={1} className="stat-label flex-1">{label}</Text>
        {icon && (
          <View className="stat-icon" style={{ backgroundColor: c.bg }}>
            <Feather name={icon} size={14} color={c.solid} />
          </View>
        )}
      </View>
      <Text numberOfLines={1} adjustsFontSizeToFit className="stat-value tabular-nums"
            style={tone ? { color: c.fg } : undefined}>{value}</Text>
      {hint ? <Text numberOfLines={2} className="stat-caption">{hint}</Text> : null}
    </View>
  );
}

export function Divider() {
  return <View className="my-0.5 h-px bg-border-subtle" />;
}

/** Linha "rótulo — valor" (`.rv-list__row`). */
export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return (
    <View className="flex-row items-center justify-between gap-3 py-1.5">
      <Text className="font-sans text-[13.5px] text-muted">{label}</Text>
      {typeof value === "string"
        ? <Text className="shrink text-right font-sans-semibold text-[13.5px] text-strong">{value}</Text>
        : value}
    </View>
  );
}

/** Diálogo do celular: sobe de baixo, com cabeçalho, conteúdo e rodapé como o p-dialog (≤640px). */
export function Sheet({ visible, onClose, title, children, footer, scroll = true }: {
  visible: boolean; onClose: () => void; title?: string; children: ReactNode; footer?: ReactNode; scroll?: boolean;
}) {
  useThemeColors();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <KeyboardAvoidingView className="flex-1" behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <Pressable className="absolute bottom-0 left-0 right-0 top-0 bg-overlay" onPress={onClose} accessibilityLabel="Fechar" />
        <View className="flex-1" pointerEvents="box-none" />
        <View className="dialog max-h-[88%] overflow-hidden shadow-lg" style={{ paddingBottom: footer ? 0 : insets.bottom }}>
          <View className="mb-0.5 mt-2 h-1 w-10 self-center rounded-full bg-border-strong" />
          {title ? (
            <View className="dialog-header">
              <Text numberOfLines={1} className="dialog-title flex-1">{title}</Text>
              <Pressable onPress={onClose} hitSlop={10} accessibilityLabel="Fechar"
                         className="size-9 items-center justify-center rounded-full active:bg-hover">
                <Feather name="x" size={18} color={tokens.muted} />
              </Pressable>
            </View>
          ) : null}
          {scroll ? (
            <ScrollView className="grow-0" contentContainerClassName="gap-3 p-4" keyboardShouldPersistTaps="handled">
              {children}
            </ScrollView>
          ) : <View className="shrink">{children}</View>}
          {footer ? (
            <View className="dialog-footer" style={{ paddingBottom: Math.max(insets.bottom, 16) }}>{footer}</View>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export type MenuItem = { label: string; icon?: IconName; danger?: boolean; onPress: () => void; hint?: string };

/** Menu "⋯" (p-menu): grupos separados por linha; item perigoso em vermelho (`.menu-danger`). */
export function MenuSheet({ visible, onClose, title, groups }: {
  visible: boolean; onClose: () => void; title?: string; groups: MenuItem[][];
}) {
  useThemeColors();
  const shown = groups.filter((g) => g.length);
  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
      {shown.map((group, gi) => (
        <View key={gi} className="gap-0.5">
          {gi > 0 && <Divider />}
          {group.map((item) => (
            <Pressable key={item.label} onPress={() => { onClose(); item.onPress(); }} className="menu-item active:bg-hover">
              {item.icon && <Feather name={item.icon} size={16} color={item.danger ? tokens.dangerText : tokens.muted} />}
              <View className="flex-1">
                <Text className={cx("menu-item-text", item.danger && "text-danger-text")}>{item.label}</Text>
                {item.hint ? <Text className="font-sans text-[12px] text-muted">{item.hint}</Text> : null}
              </View>
            </Pressable>
          ))}
        </View>
      ))}
    </Sheet>
  );
}

/** Botão flutuante "Novo" (o botão principal do cabeçalho da lista, no polegar). */
export function Fab({ label, icon = "plus", onPress }: { label: string; icon?: IconName; onPress: () => void }) {
  useThemeColors();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label}
               className="absolute bottom-4 right-4 h-12 flex-row items-center gap-2 rounded-full bg-brand px-5 shadow-brand active:bg-brand-hover">
      <Feather name={icon} size={18} color={tokens.onBrand} />
      <Text className="font-sans-semibold text-[15px] text-on-brand">{label}</Text>
    </Pressable>
  );
}
