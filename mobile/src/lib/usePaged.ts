/** Lista paginada da API (`?page=`) para FlatList: carrega, recarrega e busca a próxima página. */
import { useCallback, useEffect, useRef, useState } from "react";

import type { Page } from "@/api/client";
import { errorMessage } from "@/lib/useApi";

export function usePaged<T>(loader: (page: number) => Promise<Page<T>>, deps: unknown[] = [], enabled = true) {
  const [items, setItems] = useState<T[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(enabled);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });
  const key = JSON.stringify(deps);

  const load = useCallback(
    async (mode: "load" | "refresh") => {
      if (!enabled) return;
      const mine = ++seq.current;
      if (mode === "refresh") setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await loaderRef.current(1);
        if (mine !== seq.current) return;
        setItems(data.results);
        setCount(data.count);
        setPage(1);
        setHasMore(Boolean(data.next));
      } catch (e) {
        if (mine === seq.current) setError(errorMessage(e));
      } finally {
        if (mine === seq.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [enabled],
  );

  useEffect(() => {
    // Busca digitada: espera a pessoa parar de digitar.
    const timer = setTimeout(() => void load("load"), 250);
    return () => clearTimeout(timer);
  }, [load, key]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loadingMore || loading) return;
    const mine = seq.current;
    setLoadingMore(true);
    try {
      const data = await loaderRef.current(page + 1);
      if (mine !== seq.current) return;
      setItems((prev) => [...prev, ...data.results]);
      setPage(page + 1);
      setHasMore(Boolean(data.next));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoadingMore(false);
    }
  }, [hasMore, loadingMore, loading, page]);

  return { items, count, loading, refreshing, loadingMore, error, hasMore, loadMore,
           refresh: () => load("refresh"), reload: () => load("load") };
}
