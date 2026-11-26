/**
 * Novo lançamento de estoque (ou edição de um rascunho com `?id=`).
 * Itens entram pela câmera (leitura contínua: o mesmo código soma +1) ou pela busca.
 * Salva como rascunho; "Salvar e confirmar" já movimenta o saldo.
 */
import * as Haptics from "expo-haptics";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  createDocument, DOC_KINDS, type DocumentDraft, EXIT_REASONS, getDocument, getVariant, listWarehouses, lookupCode,
  postDocument, updateDocument,
} from "@/api/stock";
import type { DocKind, Variant, Warehouse } from "@/api/types";
import { Guard } from "@/components/Guard";
import { ProductPicker } from "@/components/ProductPicker";
import { Scanner } from "@/components/Scanner";
import { Button, Card, Chip, ErrorBox, Field, FormSection, Icon, Loading, Muted } from "@/components/ui";
import { notify, confirmAction } from "@/lib/dialog";
import { formatQty, isoDate, parseDecimalInput, toNumber } from "@/lib/format";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";
import { useSession } from "@/session/SessionContext";
import { hrefFor } from "@/shared/frontend";

type Line = {
  key: string;
  variant: string;
  name: string;
  sku: string;
  quantity: string; // texto digitado
  unitCost: string;
  lotNumber: string;
  expiresAt: string; // DD/MM/AAAA
  /** O que a linha já tinha e esta tela não edita (endereço, fabricação, notas, id): volta igual ao salvar. */
  kept?: Record<string, unknown>;
};

const KEPT = ["id", "bin", "destination_bin", "lot", "manufactured_at", "notes", "divergence_reason", "divergence_notes"];
const keptOf = (item: Record<string, unknown>) =>
  Object.fromEntries(KEPT.filter((k) => item[k] !== undefined).map((k) => [k, item[k]]));

const KIND_ORDER: DocKind[] = ["entry", "exit", "transfer", "inventory", "adjustment", "supplier_return"];

function brToIso(text: string): string | null {
  const m = text.trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
}

function isoToBr(iso?: string | null) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

function maskDate(text: string) {
  const digits = text.replace(/\D/g, "").slice(0, 8);
  return [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean).join("/");
}

let keySeq = 0;
const newKey = () => `l${++keySeq}`;

export default function NewDocumentScreen() {
  return (
    <Guard permission="stock.manage" module="stock" needsStore>
      <DocumentForm />
    </Guard>
  );
}

function DocumentForm() {
  useThemeColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ kind?: DocKind; variant?: string; id?: string }>();
  const { storeId } = useSession();
  const editingId = params.id;

  const [kind, setKind] = useState<DocKind>(params.kind && DOC_KINDS[params.kind] ? params.kind : "entry");
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [warehouse, setWarehouse] = useState<string>("");
  const [destination, setDestination] = useState<string>("");
  const [exitReason, setExitReason] = useState("consumption");
  const [effectiveDate, setEffectiveDate] = useState(isoToBr(isoDate()));
  const [externalNumber, setExternalNumber] = useState("");
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<"draft" | "post" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [scanning, setScanning] = useState(false);
  const [picking, setPicking] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const linesRef = useRef(lines);
  linesRef.current = lines;

  const meta = DOC_KINDS[kind];
  const isEntry = kind === "entry";

  // Carrega depósitos (+ rascunho em edição, + produto pré-escolhido).
  useEffect(() => {
    (async () => {
      try {
        const list = (await listWarehouses()).filter((w) => !storeId || storeId === "*" || w.store === storeId);
        setWarehouses(list);
        if (editingId) {
          const doc = await getDocument(editingId);
          setKind(doc.kind);
          setWarehouse(doc.warehouse);
          setDestination(doc.destination ?? "");
          setExitReason(doc.exit_reason || "consumption");
          setEffectiveDate(isoToBr(doc.effective_date));
          setExternalNumber(doc.external_number);
          setReason(doc.reason);
          setLines(doc.items.map((i) => ({
            key: newKey(), variant: i.variant, name: i.variant_name ?? "", sku: i.sku ?? "",
            quantity: formatQty(i.quantity).replace(/\./g, ""), unitCost: i.unit_cost && toNumber(i.unit_cost)
              ? String(i.unit_cost).replace(".", ",") : "",
            lotNumber: i.lot_number ?? "", expiresAt: isoToBr(i.expires_at),
            kept: keptOf(i as unknown as Record<string, unknown>),
          })));
        } else {
          setWarehouse((list.find((w) => w.is_default) ?? list[0])?.id ?? "");
          if (params.variant) {
            const v = await getVariant(params.variant);
            addVariant(v, 1);
          }
        }
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addVariant(v: Variant, amount: number) {
    setLines((prev) => {
      const found = prev.find((l) => l.variant === v.id);
      if (found) {
        const next = toNumber(parseDecimalInput(found.quantity) ?? 0) + amount;
        return prev.map((l) => (l === found ? { ...l, quantity: formatQty(next).replace(/\./g, "") } : l));
      }
      return [{ key: newKey(), variant: v.id, name: v.display_name, sku: v.sku,
                quantity: formatQty(amount).replace(/\./g, ""), unitCost: "", lotNumber: "", expiresAt: "" }, ...prev];
    });
  }

  async function onScanned(code: string) {
    try {
      const v = await lookupCode(code);
      if (!v) {
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        notify("Produto não encontrado", `Nenhum produto com o código ${code}.`);
        return;
      }
      // Etiqueta de balança já traz o peso.
      addVariant(v, v.scale_quantity ? toNumber(v.scale_quantity) : 1);
    } catch (e) {
      notify("Erro na leitura", errorMessage(e));
    }
  }

  function updateLine(key: string, patch: Partial<Line>) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  function removeLine(key: string) {
    setLines((prev) => prev.filter((l) => l.key !== key));
  }

  const destinations = useMemo(() => warehouses.filter((w) => w.id !== warehouse), [warehouses, warehouse]);

  function buildDraft(): DocumentDraft | string {
    if (!warehouse) return "Escolha o depósito.";
    if (kind === "transfer" && !destination) return "Escolha o depósito de destino.";
    if (kind === "transfer" && destination === warehouse) return "Origem e destino precisam ser diferentes.";
    const date = brToIso(effectiveDate);
    if (!date) return "Data inválida. Use DD/MM/AAAA.";
    if (!lines.length) return "Inclua ao menos um produto.";
    const items: DocumentDraft["items"] = [];
    for (const l of lines) {
      const qty = parseDecimalInput(l.quantity);
      if (qty === null) return `Quantidade inválida em ${l.name}.`;
      if (kind !== "adjustment" && toNumber(qty) < 0) return `Quantidade negativa só em ajuste (${l.name}).`;
      if (kind !== "adjustment" && kind !== "inventory" && toNumber(qty) === 0) return `Quantidade zerada em ${l.name}.`;
      const item: DocumentDraft["items"][number] = { ...l.kept, variant: l.variant, quantity: qty };
      if (isEntry) {
        const cost = parseDecimalInput(l.unitCost);
        if (cost !== null) item.unit_cost = cost;
        if (l.lotNumber.trim()) item.lot_number = l.lotNumber.trim();
        if (l.expiresAt.trim()) {
          const exp = brToIso(l.expiresAt);
          if (!exp) return `Validade inválida em ${l.name}. Use DD/MM/AAAA.`;
          item.expires_at = exp;
        }
      }
      items.push(item);
    }
    return {
      kind, warehouse, effective_date: date, reason: reason.trim(), items,
      destination: kind === "transfer" ? destination : null,
      exit_reason: kind === "exit" ? exitReason : "",
      external_number: externalNumber.trim(),
    };
  }

  async function save(confirm: boolean) {
    const draft = buildDraft();
    if (typeof draft === "string") {
      setError(draft);
      return;
    }
    const run = async () => {
      setSaving(confirm ? "post" : "draft");
      setError(null);
      setFieldErrors({});
      let savedId = editingId;
      try {
        const doc = editingId ? await updateDocument(editingId, draft) : await createDocument(draft);
        savedId = doc.id;
        if (confirm) await postDocument(doc.id);
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        router.replace(hrefFor(`/cadastros/entradas-e-saidas/${doc.id}`));
      } catch (e) {
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
        // Salvou o rascunho mas a confirmação falhou: abre o rascunho com o erro.
        if (confirm && savedId && !editingId) {
          notify("Rascunho salvo, mas não confirmado", errorMessage(e));
          router.replace(hrefFor(`/cadastros/entradas-e-saidas/${savedId}`));
          return;
        }
        setError(errorMessage(e));
        if (e && typeof e === "object" && "fields" in e) setFieldErrors((e as { fields: Record<string, string> }).fields);
      } finally {
        setSaving(null);
      }
    };
    if (!confirm) return run();
    confirmAction("Confirmar lançamento?",
                  `${meta.short} com ${lines.length} produto(s). O saldo do estoque será movimentado agora.`,
                  "Confirmar", () => void run());
  }

  if (loading) return <Loading />;

  const qtyLabel = kind === "inventory" ? "Contado" : kind === "adjustment" ? "Diferença (±)" : "Quantidade";

  return (
    <KeyboardAvoidingView className="flex-1 bg-ground" behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <Stack.Screen options={{ title: editingId ? "Editar rascunho" : meta.short }} />
      <Scanner visible={scanning} continuous onClose={() => setScanning(false)} onCode={(c) => void onScanned(c)}
               title="Leia os produtos (cada leitura soma 1)" />
      <ProductPicker visible={picking} onClose={() => setPicking(false)} onPick={(v) => addVariant(v, 1)} />

      <ScrollView contentContainerClassName="page pb-28"
                  keyboardShouldPersistTaps="handled">
        {!editingId && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} className="mx-[-16px] grow-0" contentContainerClassName="gap-1.5 px-4">
            {KIND_ORDER.map((k) => <Chip key={k} label={DOC_KINDS[k].short} active={kind === k} onPress={() => setKind(k)} />)}
          </ScrollView>
        )}
        <View>
          <Text className="h1">{editingId ? "Editar rascunho" : meta.label}</Text>
          <Text className="h1-sub">{meta.description}</Text>
        </View>
        {error && <ErrorBox message={error} />}

        <FormSection title={kind === "transfer" ? "Depósito de origem" : "Depósito"} icon="home" first
                     description={warehouses.find((w) => w.id === warehouse)?.uses_bins
                       ? "Depósito com endereços (WMS): se o sistema pedir o endereço, conclua pelo computador." : undefined}>
          <View className="flex-row flex-wrap gap-1.5">
            {warehouses.map((w) => (
              <Chip key={w.id} label={w.name + (w.is_default ? " (padrão)" : "")} active={warehouse === w.id}
                    onPress={() => setWarehouse(w.id)} />
            ))}
          </View>
          {warehouses.length === 0 && <Muted>Nenhum depósito ativo nesta filial.</Muted>}
          {kind === "transfer" && (
            <View className="field">
              <Text className="field-label">Depósito de destino</Text>
              <View className="flex-row flex-wrap gap-1.5">
                {destinations.map((w) => (
                  <Chip key={w.id} label={w.name} active={destination === w.id} onPress={() => setDestination(w.id)} />
                ))}
              </View>
            </View>
          )}
          {kind === "exit" && (
            <View className="field">
              <Text className="field-label">Motivo da saída</Text>
              <View className="flex-row flex-wrap gap-1.5">
                {EXIT_REASONS.map((r) => (
                  <Chip key={r.value} label={r.label} active={exitReason === r.value} onPress={() => setExitReason(r.value)} />
                ))}
              </View>
            </View>
          )}
        </FormSection>

        <FormSection title="Dados" icon="file-text">
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Field label="Data" value={effectiveDate} keyboardType="number-pad" placeholder="dd/mm/aaaa"
                     onChangeText={(v) => setEffectiveDate(maskDate(v))} error={fieldErrors.effective_date} />
            </View>
            {(isEntry || kind === "supplier_return") && (
              <View className="flex-1">
                <Field label="Nº da nota" value={externalNumber} onChangeText={setExternalNumber}
                       error={fieldErrors.external_number} />
              </View>
            )}
          </View>
          <Field label="Observação" value={reason} onChangeText={setReason} multiline
                 placeholder={kind === "exit" ? "Ex.: avaria no transporte" : "Opcional"} />
        </FormSection>

        <FormSection title={`Produtos (${lines.length})`} icon="box"
                     description={kind === "inventory"
                       ? "Informe quanto foi CONTADO. Ao confirmar, o sistema compara com o saldo e lança a diferença." : undefined}>
          <View className="flex-row gap-2">
            <Button label="Ler códigos" icon="maximize" className="flex-1" onPress={() => setScanning(true)} />
            <Button label="Buscar" icon="search" variant="outlined-secondary" className="flex-1" onPress={() => setPicking(true)} />
          </View>
        </FormSection>
        {fieldErrors.items ? <ErrorBox message={fieldErrors.items} /> : null}

        {lines.map((l) => (
          <Card key={l.key}>
            <View className="flex-row items-start gap-2">
              <View className="flex-1">
                <Text className="m-card-title" numberOfLines={2}>{l.name}</Text>
                {l.sku ? <Muted>{l.sku}</Muted> : null}
              </View>
              <Pressable hitSlop={10} onPress={() => removeLine(l.key)} accessibilityLabel="Remover item">
                <Icon name="trash-2" size={16} color={tokens.dangerText} />
              </Pressable>
            </View>
            <View className="flex-row items-end gap-2">
              <Button label="−" variant="outlined-secondary" className="w-12"
                      onPress={() => updateLine(l.key, {
                        quantity: formatQty(toNumber(parseDecimalInput(l.quantity) ?? 0) - 1).replace(/\./g, "") })} />
              <View className="flex-1">
                <Field label={qtyLabel} value={l.quantity} keyboardType={kind === "adjustment" ? "numbers-and-punctuation" : "decimal-pad"}
                       onChangeText={(v) => updateLine(l.key, { quantity: v })} className="text-center tabular-nums" />
              </View>
              <Button label="+" variant="outlined-secondary" className="w-12"
                      onPress={() => updateLine(l.key, {
                        quantity: formatQty(toNumber(parseDecimalInput(l.quantity) ?? 0) + 1).replace(/\./g, "") })} />
            </View>
            {isEntry && (
              expanded === l.key ? (
                <View className="gap-2">
                  <Field label="Custo unitário (R$)" value={l.unitCost} keyboardType="decimal-pad"
                         onChangeText={(v) => updateLine(l.key, { unitCost: v })} />
                  <View className="flex-row gap-2">
                    <View className="flex-1">
                      <Field label="Lote" value={l.lotNumber} onChangeText={(v) => updateLine(l.key, { lotNumber: v })} />
                    </View>
                    <View className="flex-1">
                      <Field label="Validade" value={l.expiresAt} placeholder="DD/MM/AAAA" keyboardType="number-pad"
                             onChangeText={(v) => updateLine(l.key, { expiresAt: maskDate(v) })} />
                    </View>
                  </View>
                </View>
              ) : (
                <Button label={[l.unitCost && `custo ${l.unitCost}`, l.lotNumber && `lote ${l.lotNumber}`,
                  l.expiresAt && `val. ${l.expiresAt}`].filter(Boolean).join(" · ") || "Custo, lote e validade"}
                        variant="ghost" compact icon="edit-2" className="self-start" onPress={() => setExpanded(l.key)} />
              )
            )}
          </Card>
        ))}
      </ScrollView>

      {/* `.actionbar` fixa embaixo: rascunho e confirmar. */}
      <View className="absolute left-4 right-4" style={{ bottom: 12 + insets.bottom }}>
        <View className="actionbar">
          <View className="flex-row items-center gap-2 pl-1.5">
            <View className="size-[9px] rounded-full" style={{ backgroundColor: lines.length ? tokens.accent : tokens.success }} />
          </View>
          <View className="flex-1 flex-row justify-end gap-[6.4px]">
            <Button label="Rascunho" variant="outlined-secondary" compact loading={saving === "draft"}
                    disabled={saving !== null} onPress={() => void save(false)} />
            <Button label="Salvar e confirmar" icon="check" compact loading={saving === "post"}
                    disabled={saving !== null} onPress={() => void save(true)} />
          </View>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
