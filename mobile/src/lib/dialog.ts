/**
 * Avisos e confirmações que funcionam no celular (Alert nativo) e no navegador
 * (no react-native-web o `Alert.alert` não mostra nada; lá usamos `window.alert/confirm`).
 */
import { Alert, Platform } from "react-native";

const web = Platform.OS === "web";

export function notify(title: string, message?: string) {
  if (web) {
    globalThis.alert?.([title, message].filter(Boolean).join("\n\n"));
    return;
  }
  Alert.alert(title, message);
}

/** Pergunta e chama `onConfirm` se a pessoa aceitar. */
export function confirmAction(title: string, message: string, confirmLabel: string, onConfirm: () => void,
                              destructive = false) {
  if (web) {
    if (globalThis.confirm?.(`${title}\n\n${message}`)) onConfirm();
    return;
  }
  Alert.alert(title, message, [
    { text: "Voltar", style: "cancel" },
    { text: confirmLabel, style: destructive ? "destructive" : "default", onPress: onConfirm },
  ]);
}
