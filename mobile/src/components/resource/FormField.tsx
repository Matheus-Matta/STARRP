/**
 * UM campo do formulário a partir da descrição da retaguarda (`FieldDef`), no formato do celular
 * (`.field`: rótulo 12,5px forte, campo de 16px, erro/dica embaixo).
 * Guarda os valores do mesmo jeito que a retaguarda manda à API: dinheiro/quantidade como texto
 * decimal ("12.50"), data ISO ("2026-11-21"), documento/telefone/CEP só com dígitos.
 * Campos compostos (itens, parcelas, variantes, fotos...) aparecem para leitura: editam na retaguarda.
 */
import Feather from "@expo/vector-icons/Feather";
import { placeholderOf, unitOf } from "@front/utils/fieldHints";
import { formatOf } from "@front/utils/formats";
import { applyMask, lookupCep, MASKS } from "@front/utils/masks";
import { type ReactNode, useState } from "react";
import { Image, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";

import { mediaUrl } from "@/api/client";
import { Scanner } from "@/components/Scanner";
import { Chip, Field, FieldShell, Muted } from "@/components/ui";
import { formatQty } from "@/lib/format";
import { tokens, useThemeColors } from "@/lib/tokens";
import type { FieldDef } from "@/shared/types";
import { compositeTable, fieldText, stripHtml } from "@/shared/values";

import { OptionSelect, RelationSelect } from "./Pickers";
import { ViewTable } from "./RowCard";

type Values = Record<string, unknown>;

const DECIMALS: Record<string, number> = { money: 2, percent: 2, quantity: 3, measure: 1, number: 0 };
const NUMERIC = Object.keys(DECIMALS);
/** Compostos: aparecem para leitura. */
const READ_ONLY = ["variants", "volumes", "grid", "stock-items", "installments", "addresses", "zip-ranges", "metafields",
                   "promotion-rules"];

function maskOf(field: FieldDef, values: Values): string | undefined {
  if (field.mask) return field.mask;
  if (field.format) return formatOf(field)?.mask;
  if (field.type === "phone") return String(values[field.name] ?? "").replace(/\D/g, "").length >= 11 ? MASKS.mobile : MASKS.phone;
  if (field.type === "cep") return MASKS.cep;
  if (field.type === "document") return values.person_type === "F" ? MASKS.cpf : MASKS.cnpj;
  return undefined;
}

/** "1.234,5" / "1234.5" → 1234.5 */
function parseNumber(text: string): number | null {
  const clean = text.trim();
  if (!clean) return null;
  const normalized = clean.includes(",") ? clean.replace(/\./g, "").replace(",", ".") : clean;
  const n = Number(normalized);
  return Number.isNaN(n) ? null : n;
}

const pad = (n: number) => String(n).padStart(2, "0");
/** ISO → "21/11/2026" (ou "21/11/2026 14:30"). */
function toDisplayDate(value: unknown, withTime: boolean) {
  if (!value) return "";
  const text = String(value);
  const d = text.length === 10 ? new Date(`${text}T00:00:00`) : new Date(text);
  if (Number.isNaN(d.getTime())) return "";
  const day = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  return withTime ? `${day} ${pad(d.getHours())}:${pad(d.getMinutes())}` : day;
}
/** "21/11/2026" → "2026-11-21"; com hora → ISO completo. Incompleto → undefined (ainda digitando). */
function fromDisplayDate(text: string, withTime: boolean): string | null | undefined {
  const digits = text.replace(/\D/g, "");
  if (!digits) return null;
  if (digits.length < (withTime ? 12 : 8)) return undefined;
  const [d, m, y] = [Number(digits.slice(0, 2)), Number(digits.slice(2, 4)), Number(digits.slice(4, 8))];
  if (!withTime) return `${y}-${pad(m)}-${pad(d)}`;
  return new Date(y, m - 1, d, Number(digits.slice(8, 10)), Number(digits.slice(10, 12))).toISOString();
}

export function FormField({ field, values, value, onChange, error, onFill, disabled }: {
  field: FieldDef; values: Values; value: unknown; onChange: (v: unknown) => void; error?: string;
  onFill?: (patch: Record<string, string>) => void; disabled?: boolean;
}) {
  useThemeColors();
  const label = field.label;
  const required = !!field.required;
  const placeholder = field.placeholder ?? placeholderOf(field);
  const hint = field.hint;

  if (field.type === "seo-preview") return null;

  if (READ_ONLY.includes(field.type)) {
    const table = compositeTable(field, values);
    return (
      <FieldShell label={label}>
        <View className="overflow-hidden rounded-[10px] border border-border">
          {table ? <ViewTable columns={table.columns} rows={table.rows} empty="Nenhum item." /> : null}
        </View>
        <Note text="Para incluir ou alterar estes itens, use a retaguarda (computador)." />
      </FieldShell>
    );
  }

  if (field.type === "images") {
    const photos = (Array.isArray(value) ? value : []) as { url: string }[];
    return (
      <FieldShell label={label}>
        {photos.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerClassName="gap-2">
            {photos.map((p, i) => (
              <Image key={p.url ?? i} source={{ uri: mediaUrl(p.url) ?? undefined }}
                     className="size-[84px] rounded-md border border-border-subtle bg-sunken" />
            ))}
          </ScrollView>
        ) : <Muted>Sem fotos.</Muted>}
        <Note text="As fotos são enviadas pela retaguarda." />
      </FieldShell>
    );
  }

  if (field.type === "richtext") {
    return (
      <FieldShell label={label}>
        <View className="input input-disabled items-start">
          <Text className="font-sans text-[14px] text-body" numberOfLines={8}>{value ? stripHtml(String(value)) : "—"}</Text>
        </View>
        <Note text="O texto com formatação é editado pela retaguarda." />
      </FieldShell>
    );
  }

  if (field.type === "boolean") {
    return (
      // ToggleSwitch com o rótulo ao lado, como o sim/não da retaguarda.
      <Pressable disabled={disabled} onPress={() => onChange(!value)} className="min-h-10 flex-row items-center gap-3">
        <Switch value={Boolean(value)} onValueChange={(v) => onChange(v)} disabled={disabled}
                trackColor={{ true: tokens.brand, false: tokens.fieldBorder }} thumbColor="#ffffff" />
        <View className="min-w-0 flex-1">
          <Text className="field-label">{label}</Text>
          {hint ? <Text className="field-hint">{hint}</Text> : null}
        </View>
      </Pressable>
    );
  }

  if (field.type === "segmented" || field.type === "multiselect") {
    const multiple = field.type === "multiselect";
    const list = multiple ? ((value as unknown[]) ?? []) : [value];
    return (
      <FieldShell label={label} required={required} error={error} hint={hint}>
        <View className="flex-row flex-wrap gap-1.5">
          {(field.options ?? []).map((o) => {
            const active = list.some((v) => String(v) === String(o.value));
            return (
              <Chip key={String(o.value)} label={o.label} active={active}
                    onPress={() => (disabled ? undefined : multiple
                      ? onChange(active ? list.filter((v) => String(v) !== String(o.value)) : [...list, o.value])
                      : onChange(o.value))} />
            );
          })}
        </View>
      </FieldShell>
    );
  }

  if (field.type === "select") {
    return (
      <FieldShell label={label} required={required} error={error} hint={hint}>
        <OptionSelect title={field.label} options={field.options ?? []} value={value} onChange={onChange}
                      error={!!error} disabled={disabled} placeholder={placeholder} />
      </FieldShell>
    );
  }

  if ((field.type === "relation" || field.type === "multirelation") && field.relation) {
    return (
      <FieldShell label={label} required={required} error={error} hint={hint}>
        <RelationSelect title={field.label} relation={field.relation} value={value} onChange={onChange}
                        multiple={field.type === "multirelation"} error={!!error} disabled={disabled}
                        placeholder={placeholder} initialLabel={fieldText({ ...field, type: "relation" }, values)} />
      </FieldShell>
    );
  }

  if (field.type === "barcodes") {
    return <Barcodes label={label} required={required} value={value} onChange={onChange} error={error} disabled={disabled} />;
  }

  if (field.type === "tags") {
    return <TagsField label={label} required={required} value={value} onChange={onChange} error={error} hint={hint}
                      disabled={disabled} />;
  }

  if (field.type === "date" || field.type === "datetime") {
    return <DateField field={field} label={label} required={required} value={value} onChange={onChange} error={error}
                      hint={hint} disabled={disabled} />;
  }

  if (NUMERIC.includes(field.type)) {
    return <NumberField field={field} label={label} required={required} value={value} onChange={onChange} error={error}
                        hint={hint} placeholder={placeholder} disabled={disabled} />;
  }

  const mask = maskOf(field, values);
  if (mask) {
    return (
      <MaskedField field={field} label={label} required={required} mask={mask} value={value} onChange={onChange}
                   error={error} hint={hint} placeholder={placeholder} onFill={onFill} disabled={disabled} />
    );
  }

  return (
    <Field
      label={label}
      required={required}
      value={value === null || value === undefined ? "" : String(value)}
      onChangeText={(v) => onChange(v)}
      error={error}
      hint={hint ?? (field.counter && field.maxLength ? `${String(value ?? "").length}/${field.maxLength}` : undefined)}
      placeholder={placeholder}
      editable={!disabled}
      multiline={field.type === "textarea"}
      maxLength={field.maxLength}
      secureTextEntry={field.type === "password"}
      keyboardType={field.type === "email" ? "email-address" : "default"}
      autoCapitalize={field.type === "email" || field.type === "password" || field.type === "color" ? "none" : "sentences"}
      autoCorrect={field.type === "textarea"}
    />
  );
}

function Note({ text }: { text: string }) {
  useThemeColors();
  return (
    <View className="flex-row items-center gap-1.5">
      <Feather name="monitor" size={12} color={tokens.subtle} />
      <Text className="field-hint flex-1">{text}</Text>
    </View>
  );
}

/** Botão quadrado ao lado do campo (mesma altura). */
function InlineButton({ icon, label, onPress, outlined }: {
  icon: "plus" | "maximize"; label: string; onPress: () => void; outlined?: boolean;
}) {
  useThemeColors();
  return (
    <Pressable onPress={onPress} accessibilityLabel={label}
               className={outlined ? "w-11 items-center justify-center rounded-[7px] border border-brand-200 active:bg-brand-subtle"
                 : "w-11 items-center justify-center rounded-[7px] bg-brand active:bg-brand-hover"}>
      <Feather name={icon} size={18} color={outlined ? tokens.brand : tokens.onBrand} />
    </Pressable>
  );
}

type Simple = { label: string; required?: boolean; value: unknown; onChange: (v: unknown) => void; error?: string;
                hint?: string; disabled?: boolean; placeholder?: string };

function NumberField({ field, label, required, value, onChange, error, hint, placeholder, disabled }: Simple & { field: FieldDef }) {
  const decimals = DECIMALS[field.type] ?? 0;
  const show = (v: unknown) => (v === null || v === undefined || v === ""
    ? "" : decimals ? formatQty(Number(v)).replace(/\./g, "") : String(v));
  const [text, setText] = useState(() => show(value));
  const [last, setLast] = useState(value);
  if (value !== last && parseNumber(text) !== (value === null || value === undefined || value === "" ? null : Number(value))) {
    setLast(value);
    setText(show(value));
  }
  const unit = field.type === "percent" ? "%" : field.type === "money" ? undefined : unitOf(field);
  return (
    <Field
      label={unit ? `${label} (${unit})` : field.type === "money" ? `${label} (R$)` : label}
      required={required}
      value={text}
      onChangeText={(v) => {
        setText(v);
        const n = parseNumber(v);
        const next = n === null ? null : decimals ? n.toFixed(decimals) : Math.trunc(n);
        setLast(next);
        onChange(next);
      }}
      keyboardType={field.signed ? "numbers-and-punctuation" : "decimal-pad"}
      error={error}
      hint={hint}
      placeholder={placeholder}
      editable={!disabled}
      className="tabular-nums"
    />
  );
}

function MaskedField({ field, label, required, mask, value, onChange, error, hint, placeholder, onFill, disabled }: Simple & {
  field: FieldDef; mask: string; onFill?: (patch: Record<string, string>) => void;
}) {
  const [note, setNote] = useState("");
  const digitsMax = mask.replace(/[^9]/g, "").length;
  return (
    <Field
      label={label}
      required={required}
      value={applyMask(value, mask)}
      onChangeText={async (v) => {
        const digits = v.replace(/\D/g, "").slice(0, digitsMax);
        onChange(digits);
        if (field.type === "cep" && digits.length === 8 && onFill) {
          setNote("Buscando o endereço…");
          const found = await lookupCep(digits);
          setNote(found ? `Endereço preenchido pelo CEP (${found.source}).` : "CEP não encontrado: preencha o endereço.");
          if (found) onFill({ street: found.street, district: found.district, city: found.city, state: found.state,
                              city_ibge: found.city_ibge });
        }
      }}
      keyboardType="number-pad"
      error={error}
      hint={note || hint}
      placeholder={placeholder ?? mask.replace(/9/g, "0").replace("?", "")}
      editable={!disabled}
    />
  );
}

function DateField({ field, label, required, value, onChange, error, hint, disabled }: Simple & { field: FieldDef }) {
  const withTime = field.type === "datetime";
  const [text, setText] = useState(() => toDisplayDate(value, withTime));
  const [last, setLast] = useState(value);
  if (value !== last) {
    setLast(value);
    setText(toDisplayDate(value, withTime));
  }
  return (
    <Field
      label={label}
      required={required}
      value={text}
      onChangeText={(v) => {
        const masked = applyMask(v, withTime ? "99/99/9999 99:99" : "99/99/9999");
        setText(masked);
        const iso = fromDisplayDate(masked, withTime);
        if (iso !== undefined) {
          setLast(iso);
          onChange(iso);
        }
      }}
      keyboardType="number-pad"
      placeholder={withTime ? "dd/mm/aaaa hh:mm" : "dd/mm/aaaa"}
      error={error}
      hint={hint}
      editable={!disabled}
    />
  );
}

function TagsField({ label, required, value, onChange, error, hint, disabled }: Simple) {
  useThemeColors();
  const tags = (Array.isArray(value) ? value : []) as string[];
  const [draft, setDraft] = useState("");
  function add() {
    const next = draft.split(",").map((s) => s.trim()).filter((s) => s && !tags.includes(s));
    if (next.length) onChange([...tags, ...next]);
    setDraft("");
  }
  return (
    <FieldShell label={label} required={required} error={error} hint={hint ?? "Digite e toque em + (ou separe por vírgula)."}>
      {tags.length > 0 && (
        <View className="flex-row flex-wrap gap-1.5">
          {tags.map((tag) => (
            // Chip do PrimeVue: fundo cinza, raio 16px, X para tirar.
            <Pressable key={tag} disabled={disabled} onPress={() => onChange(tags.filter((x) => x !== tag))}
                       className="flex-row items-center gap-1.5 rounded-2xl bg-secondary-bg px-3 py-1 active:bg-secondary-bg-active">
              <Text className="font-sans text-[13.5px] text-body">{tag}</Text>
              <Feather name="x" size={12} color={tokens.muted} />
            </Pressable>
          ))}
        </View>
      )}
      {!disabled && (
        <Row>
          <TextInput value={draft} onChangeText={setDraft} onSubmitEditing={add} placeholder="Nova tag"
                     placeholderTextColor={tokens.subtle} returnKeyType="done" className="input input-text flex-1" />
          <InlineButton icon="plus" label="Adicionar" onPress={add} />
        </Row>
      )}
    </FieldShell>
  );
}

const Row = ({ children }: { children: ReactNode }) => <View className="flex-row gap-2">{children}</View>;

type Barcode = { code: string; is_primary: boolean };

/** Códigos de barras do produto: lê pela câmera ou digita; a estrela marca o principal. */
function Barcodes({ label, required, value, onChange, error, disabled }: Simple) {
  useThemeColors();
  const list = (Array.isArray(value) ? value : []) as Barcode[];
  const [draft, setDraft] = useState("");
  const [scanning, setScanning] = useState(false);
  function add(raw: string) {
    const code = raw.trim();
    if (!code || list.some((b) => b.code === code)) return;
    onChange([...list, { code, is_primary: list.length === 0 }]);
    setDraft("");
  }
  function remove(code: string) {
    const rest = list.filter((b) => b.code !== code);
    if (rest.length && !rest.some((b) => b.is_primary)) rest[0] = { ...rest[0]!, is_primary: true };
    onChange(rest);
  }
  return (
    <FieldShell label={label} required={required} error={error}>
      {list.map((b) => (
        <View key={b.code} className="input gap-3">
          <Pressable disabled={disabled} hitSlop={6}
                     onPress={() => onChange(list.map((x) => ({ ...x, is_primary: x.code === b.code })))}>
            <Feather name={b.is_primary ? "star" : "circle"} size={16} color={b.is_primary ? tokens.accent : tokens.subtle} />
          </Pressable>
          <Text className="flex-1 font-sans-semibold text-[15px] tabular-nums text-strong">{b.code}</Text>
          {!disabled && (
            <Pressable hitSlop={8} onPress={() => remove(b.code)} accessibilityLabel="Remover código">
              <Feather name="trash-2" size={16} color={tokens.dangerText} />
            </Pressable>
          )}
        </View>
      ))}
      {!disabled && (
        <Row>
          <TextInput value={draft} onChangeText={setDraft} onSubmitEditing={() => add(draft)} placeholder="Código"
                     keyboardType="number-pad" placeholderTextColor={tokens.subtle} returnKeyType="done"
                     className="input input-text flex-1" />
          <InlineButton icon="maximize" label="Ler pela câmera" outlined onPress={() => setScanning(true)} />
          <InlineButton icon="plus" label="Adicionar" onPress={() => add(draft)} />
        </Row>
      )}
      <Text className="field-hint">A estrela marca o código principal.</Text>
      <Scanner visible={scanning} onClose={() => setScanning(false)} title="Leia o código de barras"
               onCode={(code) => {
                 add(code);
                 setScanning(false);
               }} />
    </FieldShell>
  );
}
