/** Carrega dados da API com estado de carregando/erro e recarga (puxar para atualizar). */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/api/client";

export function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Não foi possível concluir a operação.";
}

/** `deps`: quando algum muda (filial, filtro...), recarrega. O `loader` mais recente é sempre o usado. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = [], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });
  const key = JSON.stringify(deps);

  const run = useCallback(
    async (mode: "load" | "refresh" = "load") => {
      if (!enabled) return;
      const mine = ++seq.current;
      if (mode === "refresh") setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const result = await loaderRef.current();
        if (mine === seq.current) setData(result);
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
    // Buscar dados ao montar/ao mudar o filtro é exatamente o caso de efeito: o "carregando" é o estado da busca.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void run("load");
  }, [run, key]);

  return { data, setData, loading, refreshing, error, reload: () => run("load"), refresh: () => run("refresh") };
}
