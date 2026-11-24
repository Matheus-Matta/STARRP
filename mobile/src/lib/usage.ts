/**
 * Uso das telas no aparelho: quantas vezes cada tela do menu foi aberta e qual foi a última. Fica em cache no
 * próprio celular (por usuário) e ordena os atalhos da tela Início:
 *   1º–3º: os mais acessados · 4º: o último acessado (se não estiver entre os 3) · depois: a ordem normal do menu.
 */
import { useSyncExternalStore } from "react";

import { storage } from "@/lib/storage";

type Usage = { counts: Record<string, number>; last: string | null };
const KEY = "starrp.usage";
const MAX = 40;

let userKey = "";
let usage: Usage = { counts: {}, last: null };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export async function loadUsage(user: string) {
  userKey = `${KEY}.${user}`;
  try {
    const saved = await storage.get(userKey);
    usage = saved ? (JSON.parse(saved) as Usage) : { counts: {}, last: null };
  } catch {
    usage = { counts: {}, last: null };
  }
  emit();
}

/** Conta uma visita à tela `key` (o `to` do item do menu, ex.: "/cadastros/vendas"). */
export function recordVisit(key: string) {
  if (!userKey || usage.last === key) return;
  const counts = { ...usage.counts, [key]: (usage.counts[key] ?? 0) + 1 };
  // Guarda só as mais usadas (o armazenamento seguro do celular é pequeno).
  const kept = Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, MAX));
  usage = { counts: kept, last: key };
  emit();
  void storage.set(userKey, JSON.stringify(usage));
}

export function useUsage(): Usage {
  return useSyncExternalStore((l) => {
    listeners.add(l);
    return () => listeners.delete(l);
  }, () => usage);
}

/** Ordena: 3 mais acessados, o último acessado (se não estiver entre eles) e o resto na ordem original. */
export function rankByUsage<T>(items: T[], keyOf: (item: T) => string, data: Usage): T[] {
  const top = [...items].filter((i) => (data.counts[keyOf(i)] ?? 0) > 0)
    .sort((a, b) => (data.counts[keyOf(b)] ?? 0) - (data.counts[keyOf(a)] ?? 0)).slice(0, 3);
  const last = items.find((i) => keyOf(i) === data.last);
  const head = last && !top.includes(last) ? [...top, last] : top;
  return [...head, ...items.filter((i) => !head.includes(i))];
}
