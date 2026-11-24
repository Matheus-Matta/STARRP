/**
 * Seleção no celular: o campo mostra o escolhido e abre o diálogo de seleção (`SelectDialog`).
 *  - `OptionSelect`: opções fixas (uma ou várias), filtradas no aparelho;
 *  - `RelationSelect`: registro de outro cadastro, com busca no servidor (`search=`), como o
 *    RelationSelect da retaguarda (guarda o rótulo do escolhido e, no valor salvo, busca o nome).
 */
import Feather from "@expo/vector-icons/Feather";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Dimensions, FlatList, Pressable, Text, View } from "react-native";

import { api, type Page } from "@/api/client";
import { Button, Muted, SearchBar, Sheet } from "@/components/ui";
import { tokens, useThemeColors } from "@/lib/tokens";
import type { Option, Relation } from "@/shared/types";

type Row = Record<string, unknown>;

/** A "caixa" do campo de seleção (`p-select`: igual ao input, com a seta). */
export function SelectBox({ text, placeholder, onPress, error, disabled, onClear }: {
  text?: string; placeholder?: string; onPress: () => void; error?: boolean; disabled?: boolean; onClear?: () => void;
}) {
  useThemeColors();
  return (
    <Pressable disabled={disabled} onPress={onPress}
               className={["input gap-2", error && "input-invalid", disabled ? "input-disabled" : "active:border-brand-400"]
                 .filter(Boolean).join(" ")}>
      <Text numberOfLines={1} className={text ? "input-text flex-1" : "input-text flex-1 text-subtle"}>
        {text || placeholder || "Selecione"}
      </Text>
      {text && onClear && !disabled ? (
        <Pressable hitSlop={10} onPress={onClear} accessibilityLabel="Limpar">
          <Feather name="x" size={14} color={tokens.subtle} />
        </Pressable>
      ) : null}
      <Feather name="chevron-down" size={14} color={tokens.subtle} />
    </Pressable>
  );
}

/** Opção do diálogo (`p-select-option`): selecionada com o destaque azul-claro. */
function OptionRow({ label, hint, selected, onPress, multiple }: {
  label: string; hint?: string; selected: boolean; onPress: () => void; multiple?: boolean;
}) {
  useThemeColors();
  return (
    <Pressable onPress={onPress}
               className={selected ? "min-h-11 flex-row items-center gap-3 rounded-md bg-brand-subtle px-3"
                 : "min-h-11 flex-row items-center gap-3 rounded-md px-3 active:bg-hover"}>
      {multiple && (
        <View className={selected ? "size-5 items-center justify-center rounded border border-brand bg-brand"
          : "size-5 rounded border border-field-border bg-field-bg"}>
          {selected && <Feather name="check" size={13} color={tokens.onBrand} />}
        </View>
      )}
      <View className="flex-1 py-2">
        <Text className={selected ? "font-sans text-[15px] text-brand-text" : "font-sans text-[15px] text-body"}>{label}</Text>
        {hint ? <Text className="font-sans text-[12px] text-muted">{hint}</Text> : null}
      </View>
      {!multiple && selected ? <Feather name="check" size={16} color={tokens.brand} /> : null}
    </Pressable>
  );
}

/** Item de lista no diálogo de seleção. */
export type Choice = { value: unknown; label: string; hint?: string };
export type ChoiceSource = { options: Choice[] }
  | { load: (term: string, page: number) => Promise<{ items: Choice[]; more: boolean }> };

const norm = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("pt-BR");

/**
 * Diálogo de seleção (o `p-select` com filtro, em tela de celular): busca no topo e a lista rolando por baixo.
 * Opções fixas filtram no aparelho (lista virtualizada); registros de outro cadastro buscam no SERVIDOR
 * (`search=`), 30 por vez, e carregam mais ao rolar — nunca baixa a lista inteira (1.000 produtos não pesam).
 */
export function SelectDialog({ visible, onClose, title, source, isSelected, onPick, multiple, onClear }: {
  visible: boolean; onClose: () => void; title: string; source: ChoiceSource; isSelected: (value: unknown) => boolean;
  onPick: (choice: Choice) => void; multiple?: boolean; onClear?: () => void;
}) {
  useThemeColors();
  const remote = "load" in source;
  const [term, setTerm] = useState("");
  const [rows, setRows] = useState<Choice[]>([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [wasOpen, setWasOpen] = useState(false);
  if (visible !== wasOpen) {
    setWasOpen(visible);
    if (visible) setTerm("");
  }

  const fetchPage = useCallback(async (next: number, search: string) => {
    if (!("load" in source)) return;
    setLoading(true);
    setFailed(null);
    try {
      const result = await source.load(search, next);
      setRows((prev) => (next === 1 ? result.items : [...prev, ...result.items]));
      setMore(result.more);
      setPage(next);
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "Não foi possível carregar.");
    } finally {
      setLoading(false);
    }
  }, [source]);

  useEffect(() => {
    if (!visible || !remote) return;
    const timer = setTimeout(() => void fetchPage(1, term), term ? 250 : 0);
    return () => clearTimeout(timer);
  }, [visible, term, remote, fetchPage]);

  const fixed = "options" in source ? source.options : [];
  const list = remote ? rows : fixed.filter((o) => !term || norm(o.label).includes(norm(term)));
  const showSearch = remote || fixed.length > 8;
  const height = Math.round(Dimensions.get("window").height * 0.62);

  return (
    <Sheet visible={visible} onClose={onClose} title={title} scroll={false}
           footer={multiple || onClear ? (
             <>
               {onClear && <Button label="Limpar" variant="outlined-secondary" className="flex-1" onPress={() => {
                 onClear();
                 onClose();
               }} />}
               {multiple && <Button label="Pronto" icon="check" className="flex-1" onPress={onClose} />}
             </>
           ) : undefined}>
      <View style={{ height }} className="gap-2 px-4 pt-3">
        {showSearch && <SearchBar value={term} onChangeText={setTerm} placeholder="Procurar…" autoFocus={remote} />}
        {failed && <Muted>{failed}</Muted>}
        <FlatList
          data={list}
          keyExtractor={(item, i) => `${String(item.value)}-${i}`}
          keyboardShouldPersistTaps="handled"
          initialNumToRender={30}
          windowSize={7}
          onEndReachedThreshold={0.5}
          onEndReached={() => {
            if (remote && more && !loading) void fetchPage(page + 1, term);
          }}
          ListEmptyComponent={loading ? undefined
            : <Muted className="py-4 text-center">{term ? `Nada encontrado para "${term}".` : "Nada encontrado."}</Muted>}
          ListFooterComponent={loading ? <ActivityIndicator color={tokens.brand} className="my-3" /> : <View className="h-3" />}
          renderItem={({ item }) => (
            <OptionRow label={item.label} hint={item.hint} selected={isSelected(item.value)} multiple={multiple}
                       onPress={() => {
                         onPick(item);
                         if (!multiple) onClose();
                       }} />
          )}
        />
      </View>
    </Sheet>
  );
}

export function OptionSelect({ title, options, value, onChange, multiple, error, disabled, placeholder }: {
  title: string; options: Option[]; value: unknown; onChange: (v: unknown) => void; multiple?: boolean; error?: boolean;
  disabled?: boolean; placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const chosen = multiple ? ((value as unknown[]) ?? []) : [value];
  const has = (v: unknown) => chosen.some((c) => String(c) === String(v));
  const text = options.filter((o) => has(o.value)).map((o) => o.label).join(", ");
  return (
    <>
      <SelectBox text={text} placeholder={placeholder} onPress={() => setOpen(true)} error={error} disabled={disabled}
                 onClear={!multiple ? () => onChange(null) : undefined} />
      <SelectDialog visible={open} onClose={() => setOpen(false)} title={title} multiple={multiple}
                    source={{ options: options.map((o) => ({ value: o.value, label: o.label })) }} isSelected={has}
                    onPick={(o) => onChange(!multiple ? o.value
                      : has(o.value) ? chosen.filter((c) => String(c) !== String(o.value)) : [...chosen, o.value])} />
    </>
  );
}

export function RelationSelect({ title, relation, value, onChange, multiple, error, disabled, placeholder, initialLabel }: {
  title: string; relation: Relation; value: unknown; onChange: (v: unknown) => void; multiple?: boolean; error?: boolean;
  disabled?: boolean; placeholder?: string; initialLabel?: string;
}) {
  useThemeColors();
  const labelKey = relation.labelKey ?? "name";
  const valueKey = relation.valueKey ?? "id";
  const [open, setOpen] = useState(false);
  const [known, setKnown] = useState<Record<string, string>>({});
  const remember = useCallback((entries: [string, string][]) => {
    setKnown((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
  }, []);
  const chosen = (multiple ? ((value as unknown[]) ?? []) : value === null || value === undefined || value === "" ? [] : [value])
    .map(String);

  // Rótulo do valor já salvo: o nome que o registro trouxe ou o detalhe do relacionado.
  const single = chosen.length === 1 && initialLabel && initialLabel !== chosen[0] ? initialLabel : undefined;
  useEffect(() => {
    const missing = chosen.filter((id) => !(id in known));
    if (!missing.length || valueKey !== "id" || single) return;
    let alive = true;
    void Promise.all(missing.map((id) => api.get<Row>(`${relation.endpoint}${id}/`)
      .then((row) => [id, String(row[labelKey] ?? id)] as [string, string])
      .catch(() => [id, id] as [string, string])))
      .then((entries) => alive && remember(entries));
    return () => {
      alive = false;
    };
  }, [chosen.join(","), relation.endpoint]); // eslint-disable-line react-hooks/exhaustive-deps

  const source = useMemo<ChoiceSource>(() => ({
    load: async (search: string, page: number) => {
      const data = await api.get<Page<Row>>(relation.endpoint, { ...relation.params, search, page, page_size: 30 });
      remember(data.results.map((r) => [String(r[valueKey]), String(r[labelKey] ?? r[valueKey])]));
      return { items: data.results.map((r) => ({ value: r[valueKey], label: String(r[labelKey] ?? r[valueKey]) })),
               more: Boolean(data.next) };
    },
  }), [relation.endpoint, relation.params, labelKey, valueKey, remember]);

  const text = chosen.map((id) => known[id] ?? single ?? "…").join(", ");
  function pick(choice: Choice) {
    const id = String(choice.value);
    if (!multiple) return onChange(choice.value);
    const list = (value as unknown[]) ?? [];
    onChange(chosen.includes(id) ? list.filter((v) => String(v) !== id) : [...list, choice.value]);
  }

  return (
    <>
      <SelectBox text={text} placeholder={placeholder} onPress={() => setOpen(true)} error={error} disabled={disabled}
                 onClear={!multiple ? () => onChange(null) : undefined} />
      <SelectDialog visible={open} onClose={() => setOpen(false)} title={title} multiple={multiple} source={source}
                    isSelected={(v) => chosen.includes(String(v))} onPick={pick} />
    </>
  );
}
