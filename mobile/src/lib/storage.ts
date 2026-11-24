/**
 * Guarda tokens e preferências: SecureStore no celular (criptografado pelo sistema);
 * no navegador (Expo web, para desenvolvimento) o SecureStore não existe e usa `localStorage`.
 */
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const web = Platform.OS === "web";
/** iPhone: só com o aparelho desbloqueado e só NESTE aparelho (não vai para backup do iCloud nem para outro iPhone). */
const SECURE = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };

export const storage = {
  async get(key: string): Promise<string | null> {
    if (!web) return SecureStore.getItemAsync(key, SECURE);
    try {
      return globalThis.localStorage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  },
  async set(key: string, value: string) {
    if (!web) return SecureStore.setItemAsync(key, value, SECURE);
    try {
      globalThis.localStorage?.setItem(key, value);
    } catch {
      /* armazenamento bloqueado: a sessão vale só enquanto a aba estiver aberta */
    }
  },
  async remove(key: string) {
    if (!web) return SecureStore.deleteItemAsync(key, SECURE);
    try {
      globalThis.localStorage?.removeItem(key);
    } catch {
      /* idem */
    }
  },
};
