/**
 * Leitor de código de barras pela câmera (EAN, Code 128, QR...). Abre em tela cheia;
 * `continuous` mantém a câmera aberta para bipar vários itens seguidos (contagem, entrada).
 */
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { useRef, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Button, Icon } from "@/components/ui";
import { fonts } from "@/lib/theme";

const BARCODE_TYPES = ["ean13", "ean8", "upc_a", "upc_e", "code128", "code39", "code93", "itf14", "qr",
  "datamatrix"] as const;

export function Scanner({ visible, onClose, onCode, continuous = false, title = "Aponte para o código" }: {
  visible: boolean; onClose: () => void; onCode: (code: string) => void; continuous?: boolean; title?: string;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const [torch, setTorch] = useState(false);
  const [last, setLast] = useState<string | null>(null);
  // O leitor dispara várias vezes por segundo: ignora o mesmo código por 1,5 s.
  const lastRead = useRef<{ code: string; at: number }>({ code: "", at: 0 });

  function handle(code: string) {
    const now = Date.now();
    if (code === lastRead.current.code && now - lastRead.current.at < 1500) return;
    lastRead.current = { code, at: now };
    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    setLast(code);
    onCode(code);
    if (!continuous) onClose();
  }

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        {!permission ? null : !permission.granted ? (
          <SafeAreaView style={styles.permission}>
            <Icon name="camera-off" size={40} color="#fff" />
            <Text style={styles.white}>O app precisa da câmera para ler os códigos de barras.</Text>
            <Button label="Permitir câmera" onPress={() => void requestPermission()} />
            <Button label="Cancelar" variant="ghost" onPress={onClose} />
          </SafeAreaView>
        ) : (
          <>
            {visible && (
              <CameraView
                style={StyleSheet.absoluteFill}
                facing="back"
                enableTorch={torch}
                barcodeScannerSettings={{ barcodeTypes: [...BARCODE_TYPES] }}
                onBarcodeScanned={({ data }) => data && handle(data)}
              />
            )}
            <SafeAreaView style={styles.overlay} pointerEvents="box-none">
              <View style={styles.top}>
                <Pressable onPress={onClose} hitSlop={12} style={styles.round}>
                  <Icon name="x" color="#fff" />
                </Pressable>
                <Text style={[styles.white, { flex: 1, textAlign: "center" }]}>{title}</Text>
                <Pressable onPress={() => setTorch((v) => !v)} hitSlop={12} style={styles.round}>
                  <Icon name={torch ? "zap-off" : "zap"} color="#fff" />
                </Pressable>
              </View>
              <View style={styles.frame} />
              <View style={styles.bottom}>
                {continuous && last ? <Text style={styles.white}>Último lido: {last}</Text> : null}
                {continuous && <Button label="Concluir leitura" onPress={onClose} />}
              </View>
            </SafeAreaView>
          </>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000" },
  permission: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16, padding: 24 },
  overlay: { flex: 1, justifyContent: "space-between", padding: 16 },
  top: { flexDirection: "row", alignItems: "center", gap: 12 },
  round: { width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center",
           justifyContent: "center" },
  frame: { alignSelf: "center", width: "80%", aspectRatio: 1.6, borderWidth: 3, borderColor: "#60a5fa",
           borderRadius: 16 },
  bottom: { gap: 12, paddingBottom: 8 },
  white: { color: "#fff", fontSize: 15, fontFamily: fonts.semibold, textAlign: "center" },
});
