/**
 * Painel de impressão (a barra de cima da página `/imprimir/...` da retaguarda): carrega o documento, deixa escolher
 * o papel (Folha A4, A4 deitado, Bobina 80 mm — os que o documento aceita) e gera o PDF para compartilhar
 * (WhatsApp, e-mail...) ou abre a impressão do sistema. Atende `openPrint()` de qualquer tela.
 */
import Feather from "@expo/vector-icons/Feather";
import { useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, Text, View } from "react-native";

import { Chip, ErrorBox, Sheet } from "@/components/ui";
import { tokens, useThemeColors } from "@/lib/tokens";
import { errorMessage } from "@/lib/useApi";
import { loadPrint, onPrintRequest, type PrintRequest, printNow, renderPrint, sharePrint } from "@/print";
import type { LoadedDoc } from "@/print/docs";
import { FORMAT_LABELS, type PrintFormat } from "@/print/shell";
import { useSession } from "@/session/SessionContext";

export function PrintHost() {
  useThemeColors();
  const { me, storeId, storeName } = useSession();
  const [request, setRequest] = useState<PrintRequest | null>(null);
  const [doc, setDoc] = useState<LoadedDoc | null>(null);
  const [format, setFormat] = useState<PrintFormat>("a4");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"pdf" | "print" | null>(null);

  // Só no Expo web em desenvolvimento: gera o HTML de um documento para conferir a folha no navegador.
  useEffect(() => {
    if (!__DEV__ || Platform.OS !== "web") return;
    (globalThis as Record<string, unknown>).__starrpPrintHtml = async (docName: string, id: string, query: Record<string, string> = {},
                                                                       paper?: PrintFormat) => {
      const loaded = await loadPrint({ doc: docName, id, query }, storeName);
      return renderPrint(loaded, paper ?? loaded.format, me, storeId && storeId !== "*" ? storeId : null);
    };
  }, [me, storeId, storeName]);

  useEffect(() => onPrintRequest((next) => {
    setRequest(next);
    setDoc(null);
    setError(null);
  }), []);

  useEffect(() => {
    if (!request) return;
    let alive = true;
    loadPrint(request, storeName)
      .then((loaded) => {
        if (!alive) return;
        setDoc(loaded);
        setFormat(loaded.format);
      })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [request, storeName]);

  async function run(kind: "pdf" | "print") {
    if (!doc) return;
    setBusy(kind);
    setError(null);
    try {
      const active = storeId && storeId !== "*" ? storeId : null;
      if (kind === "pdf") await sharePrint(doc, format, me, active);
      else await printNow(doc, format, me, active);
      setRequest(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Sheet visible={!!request} onClose={() => setRequest(null)} title={doc?.title ?? "Imprimir"}>
      {error && <ErrorBox message={error} />}
      {!doc && !error && (
        <View className="items-center gap-2 py-6">
          <ActivityIndicator color={tokens.brand} />
          <Text className="font-sans text-[13px] text-muted">Carregando o documento…</Text>
        </View>
      )}
      {doc && (
        <>
          {doc.subtitle ? <Text className="font-sans text-[13px] text-muted">{doc.subtitle}</Text> : null}
          {doc.formats.length > 1 && (
            <View className="field">
              <Text className="field-label">Papel</Text>
              <View className="flex-row flex-wrap gap-1.5">
                {doc.formats.map((f) => <Chip key={f} label={FORMAT_LABELS[f]} active={format === f} onPress={() => setFormat(f)} />)}
              </View>
            </View>
          )}
          {([["pdf", "PDF", "Compartilhar no WhatsApp, e-mail, Drive…", "file-text"],
             ["print", "Imprimir", "Impressora ou \"Salvar como PDF\"", "printer"]] as const).map(([kind, label, hint, icon]) => (
            <Pressable key={kind} disabled={!!busy} onPress={() => void run(kind)} className="m-card flex-row items-center gap-3 active:bg-hover">
              <View className="size-10 items-center justify-center rounded-[10px] bg-brand-subtle">
                <Feather name={icon} size={17} color={tokens.brand} />
              </View>
              <View className="min-w-0 flex-1">
                <Text className="font-sans-bold text-[14px] text-strong">{busy === kind ? "Gerando…" : label}</Text>
                <Text className="font-sans text-[12px] text-muted">{hint}</Text>
              </View>
              <Feather name="chevron-right" size={16} color={tokens.subtle} />
            </Pressable>
          ))}
        </>
      )}
    </Sheet>
  );
}
