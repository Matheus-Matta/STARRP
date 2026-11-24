/** Estado global mínimo (sem biblioteca): um valor + quem escuta, lido com `useStore`. */
import { useSyncExternalStore } from "react";

export type Store<T> = { get: () => T; set: (next: T | ((prev: T) => T)) => void; subscribe: (fn: () => void) => () => void };

export function createStore<T>(initial: T): Store<T> {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next) => {
      value = typeof next === "function" ? (next as (prev: T) => T)(value) : next;
      listeners.forEach((fn) => fn());
    },
    subscribe: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

export const useStore = <T,>(store: Store<T>) => useSyncExternalStore(store.subscribe, store.get);
