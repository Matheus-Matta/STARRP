/**
 * Aparência do app escolhida no menu: Claro, Escuro ou Sistema (segue o celular). Guardada no aparelho e
 * aplicada antes da primeira tela (`loadAppearance` no layout raiz).
 */
import { Uniwind } from "uniwind";

import { storage } from "@/lib/storage";

export type Appearance = "light" | "dark" | "system";
const KEY = "starrp.appearance";

export async function loadAppearance(): Promise<Appearance> {
  const saved = (await storage.get(KEY)) as Appearance | null;
  const value = saved === "dark" || saved === "system" ? saved : "light";
  Uniwind.setTheme(value);
  return value;
}

export async function setAppearance(value: Appearance) {
  Uniwind.setTheme(value);
  await storage.set(KEY, value);
}

export function currentAppearance(): Appearance {
  return Uniwind.hasAdaptiveThemes ? "system" : Uniwind.currentTheme === "dark" ? "dark" : "light";
}
