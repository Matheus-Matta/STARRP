/** Raiz: carrega a sessão guardada (tokens no processo principal) e mostra o login ou o PDV. */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { toApiError } from "@/api/errors";
import ApprovalDialog from "@/components/ApprovalDialog";
import LoginPage from "@/pages/LoginPage";
import PdvPage from "@/pdv/PdvPage";
import { watchNet } from "@/state/net";
import { expire, loadSession, session } from "@/state/session";
import { useStore } from "@/state/store";
import { Button, Toaster } from "@/ui";

export default function App() {
  const state = useStore(session);
  const client = useQueryClient();
  const [offline, setOffline] = useState<string | null>(null);

  async function boot() {
    setOffline(null);
    try {
      await loadSession();
    } catch (error) {
      setOffline(toApiError(error).message);
    }
  }

  useEffect(() => {
    void boot();
    const stopNet = watchNet();
    const stopExpired = window.starrp.auth.onExpired(() => {
      client.clear();
      expire();
    });
    return () => {
      stopNet();
      stopExpired();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Trocar de operador/loja não pode reaproveitar dados em cache do anterior (as chaves de pedidos,
  // formas de pagamento e frete não levam a filial).
  useEffect(() => {
    if (state.status !== "ready") client.clear();
  }, [state.status, client]);
  const storeKey = state.status === "ready" ? state.storeId : null;
  const lastStore = useRef(storeKey);
  useEffect(() => {
    if (lastStore.current !== null && storeKey !== null && lastStore.current !== storeKey) client.clear();
    lastStore.current = storeKey;
  }, [storeKey, client]);

  let screen;
  if (offline) {
    screen = (
      <div className="grid h-full place-items-center p-6">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <span className="grid size-14 place-items-center rounded-full bg-warning-subtle text-xl text-warning-text"><i className="pi pi-wifi" /></span>
          <h1 className="text-lg font-bold text-strong">Servidor indisponível</h1>
          <p className="text-[13.5px] text-muted">{offline}</p>
          <p className="text-[12.5px] text-muted">Para vender sem o servidor, este PC precisa ter entrado online ao menos uma vez (guarda o catálogo e o operador).</p>
          <p className="text-[12.5px] text-subtle">{state.config?.serverUrl}</p>
          <div className="flex gap-2">
            <Button icon="pi pi-refresh" onClick={() => void boot()}>Tentar de novo</Button>
            <Button variant="secondary" onClick={() => { setOffline(null); expire(); }}>Trocar servidor</Button>
          </div>
        </div>
      </div>
    );
  } else if (state.status === "loading") {
    screen = <div className="grid h-full place-items-center text-muted"><i className="pi pi-spin pi-spinner text-2xl" /></div>;
  } else if (state.status === "anonymous" || !state.me) {
    screen = <LoginPage />;
  } else {
    // `key`: trocar de loja ou de operador remonta o PDV do zero (novo bootstrap).
    screen = <PdvPage key={`${state.me.id}:${state.storeId}`} />;
  }

  return (
    <>
      {screen}
      <ApprovalDialog />
      <Toaster />
    </>
  );
}
